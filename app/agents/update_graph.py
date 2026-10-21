"""규제 DB 갱신 제안 그래프 (Step 12) — 목록 하나를 감시하는 에이전트.

    detect ─(새 버전 없음·이미 올린 버전)─▶ END
      └▶ compare(새 버전 행 · 바뀐 행 · 후보 DB로 제품 재판정) ─(행 변화 없음)─▶ END
          └▶ explain(LLM: 승인 담당자용 설명) ▶ propose(후보 저장) ▶ approval(interrupt) ▶ apply ▶ END

판단은 코드가 한다: 버전 비교, 행 비교, 판정 변화. LLM은 그 사실을 사람이 읽기 쉽게 설명만 하고,
설명에 사실에 없는 숫자·날짜가 있으면 버리고 코드 요약을 쓴다.
DB를 바꾸는 것은 담당자가 승인한 뒤 apply 노드뿐이다 — 승인 대기는 체크포인터에 남아 서버를 재시작해도 이어진다.
"""
from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.core.config import Settings
from app.domain import integrity
from app.llm.base import AgentLLM
from app.regupdate import compare, sources
from app.repositories.product_db import ProductDB
from app.repositories.reg_db import RegDB
from app.repositories.update_db import UpdateDB, now
from scripts.build_reg_db import build

EXPLAIN_QUESTION = ("아래는 규제 DB 갱신 후보를 코드가 비교한 결과다. 승인 담당자가 반영 여부를 판단할 수 있게 "
                    "3~4문장으로 설명하라: 무엇이 바뀌었나, 회사 제품 판정이 어떻게 바뀌나, 기준일(적용 예정 여부)을 "
                    "고려할 점. 결과에 없는 사실·숫자는 쓰지 않는다. 근거 번호는 붙이지 않는다.")


@dataclass
class UpdateDeps:
    settings: Settings
    llm: AgentLLM
    products: ProductDB
    updates: UpdateDB


class UpdateState(TypedDict, total=False):
    reg_id: str
    thread_id: str
    today: str
    current: str | None
    latest: str
    effective: str
    outcome: str                 # 끝난 이유: no_new_version | already_proposed | no_change | proposed | applied | rejected | failed
    message: str
    diff: dict
    company: list
    products: list
    facts: str
    summary: str
    candidate_path: str
    update_id: int
    decision: dict               # 담당자 결정 (interrupt 재개 값)
    usage: list


def _progress(text: str, **extra) -> None:
    get_stream_writer()({"type": "progress", "message": text, **extra})


async def detect_node(state: UpdateState, deps: UpdateDeps) -> dict:
    w = sources.BY_REG[state["reg_id"]]
    current = sources.current_version(deps.settings, w)
    try:
        latest = await asyncio.to_thread(sources.latest_version, w, deps.settings.http_timeout_s * 3)
    except Exception as exc:                                   # 감지 실패는 DB를 건드리지 않고 끝낸다
        return {"current": current, "outcome": "failed", "message": f"최신 버전 확인 실패 ({type(exc).__name__})"}
    _progress(f"{w.label}: 지금 {current} · 최신 {latest}")
    if current and latest <= current:
        return {"current": current, "latest": latest, "outcome": "no_new_version", "message": "새 버전 없음"}
    if deps.updates.find(w.reg_id, latest):
        return {"current": current, "latest": latest, "outcome": "already_proposed", "message": "이미 올린 버전"}
    return {"current": current, "latest": latest, "effective": sources.version_date(latest)}


async def compare_node(state: UpdateState, deps: UpdateDeps) -> dict:
    w, s = sources.BY_REG[state["reg_id"]], deps.settings
    new_rows = await asyncio.to_thread(sources.fetch_rows, w, state["latest"], state["today"])
    old_rows = sources.read_rows(sources.effective_file(s, w))
    diff = compare.diff_rows(old_rows, new_rows)
    c = compare.counts(diff)
    _progress(f"{w.label}: 추가 {c['added']} · 삭제 {c['removed']} · 변경 {c['changed']}")
    if not any(c.values()):                                    # 기록해 두어 같은 버전을 다시 받지 않는다
        deps.updates.create({"reg_id": w.reg_id, "label": w.label, "current_version": state["current"],
                             "new_version": state["latest"], "effective_date": state["effective"],
                             "detected_at": now(), "status": "no_change", "counts": c})
        return {"diff": diff, "outcome": "no_change", "message": "새 버전이지만 이 목록의 행은 그대로"}

    candidate = sources.write_rows(s.reg_updates_dir / "candidates" / f"{w.reg_id}-{state['latest']}.csv", new_rows)
    preview = s.reg_updates_dir / "candidates" / "preview.db"     # 후보를 얹은 DB로 전체 제품을 다시 판정
    await asyncio.to_thread(build, s, preview, {w.bulk_file: candidate})
    ingredients = deps.products.ingredient_names()
    try:
        changes = compare.judge_changes(RegDB(s.reg_db_path, deps.products), RegDB(preview, deps.products),
                                        {w.reg_id}, ingredients)
    finally:
        preview.unlink(missing_ok=True)
    company = compare.company_rows(diff, ingredients)
    facts = compare.facts_text(w.label, state["current"], state["latest"], state["effective"], state["today"],
                               diff, company, changes)
    return {"diff": diff, "company": company, "products": changes, "facts": facts, "candidate_path": str(candidate)}


async def explain_node(state: UpdateState, deps: UpdateDeps) -> dict:
    text, usage = await deps.llm.answer(EXPLAIN_QUESTION, state["facts"], "", "")
    text = re.sub(r"\s*\[\d+\]", "", text).strip()
    report = integrity.check(state["facts"], text, reference=state["today"])
    if report.extra_cas or report.extra_dates or report.extra_numbers:   # 사실에 없는 CAS·날짜·숫자 → 코드 요약만
        text = ""
    return {"summary": text, "usage": [usage]}


async def propose_node(state: UpdateState, deps: UpdateDeps) -> dict:
    w = sources.BY_REG[state["reg_id"]]
    record = deps.updates.create({
        "reg_id": w.reg_id, "label": w.label, "current_version": state["current"], "new_version": state["latest"],
        "effective_date": state["effective"], "detected_at": now(), "status": "pending",
        "counts": compare.counts(state["diff"]), "diff": state["diff"], "company": state["company"],
        "products": state["products"], "facts": state["facts"], "summary": state["summary"],
        "candidate_path": state["candidate_path"], "thread_id": state.get("thread_id")})
    _progress(f"{w.label}: 갱신 후보 #{record['id']} — 담당자 승인 대기")
    return {"update_id": record["id"], "outcome": "proposed"}


async def approval_node(state: UpdateState, deps: UpdateDeps) -> dict:
    decision = interrupt({"update_id": state["update_id"], "reg_id": state["reg_id"], "new_version": state["latest"]})
    return {"decision": decision}


async def apply_node(state: UpdateState, deps: UpdateDeps) -> dict:
    d: dict[str, Any] = state["decision"]
    who, comment = d.get("approver") or "담당자", d.get("comment") or ""
    if not d.get("approved"):
        deps.updates.decide(state["update_id"], "rejected", who, comment)
        return {"outcome": "rejected", "message": "반려 — DB 그대로"}
    w, s = sources.BY_REG[state["reg_id"]], deps.settings
    target = s.reg_updates_dir / "bulk" / w.bulk_file
    backup = target.with_suffix(".csv.bak") if target.exists() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup:
        shutil.copyfile(target, backup)
    shutil.copyfile(state["candidate_path"], target)
    try:
        counts = await asyncio.to_thread(build, s)            # 검증 → 임시 DB → 한 번에 바꿔 끼움
    except Exception as exc:                                   # 검증 실패: 반영 파일을 되돌리고 DB는 그대로
        if backup:
            shutil.move(backup, target)
        else:
            target.unlink(missing_ok=True)
        deps.updates.decide(state["update_id"], "failed", who, f"{comment} (반영 실패: {exc})".strip())
        return {"outcome": "failed", "message": f"반영 실패 — DB 그대로 ({type(exc).__name__})"}
    if backup:
        backup.unlink(missing_ok=True)
    deps.updates.decide(state["update_id"], "applied", who, comment,
                        {"listings": counts["listings"], "substances": counts["substances"]})
    return {"outcome": "applied", "message": f"반영 — 등재 {counts['listings']}행"}


def after_detect(state: UpdateState) -> str:
    return END if state.get("outcome") else "compare"


def after_compare(state: UpdateState) -> str:
    return END if state.get("outcome") else "explain"


def build_update_graph(deps: UpdateDeps, checkpointer=None):
    g = StateGraph(UpdateState)
    bind = lambda fn: partial(fn, deps=deps)   # noqa: E731
    for name, fn in [("detect", detect_node), ("compare", compare_node), ("explain", explain_node),
                     ("propose", propose_node), ("approval", approval_node), ("apply", apply_node)]:
        g.add_node(name, bind(fn))
    g.add_edge(START, "detect")
    g.add_conditional_edges("detect", after_detect, ["compare", END])
    g.add_conditional_edges("compare", after_compare, ["explain", END])
    g.add_edge("explain", "propose")
    g.add_edge("propose", "approval")
    g.add_edge("approval", "apply")
    g.add_edge("apply", END)
    return g.compile(checkpointer=checkpointer)


def initial_state(reg_id: str, thread_id: str) -> UpdateState:
    return {"reg_id": reg_id, "today": date.today().isoformat(), "thread_id": thread_id}
