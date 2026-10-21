"""병렬 조사 에이전트 4개 — Supervisor가 Send로 동시에 실행한다.

- us_feed  (해외 수집): 미국 관보 검색 → 문서별 본문 → 우리 규제 DB 물질이 언급된 문서만 → 근거 문장 추출
- eu_feed  (해외 수집): EU REACH·CLP를 개정한 법령(Cellar) → 본문의 회사 물질 → 관련 없는 개정은 참고 (Step 11)
- kr_feed  (국내 수집): 법제처 행정규칙 — LLM이 검색어를 정해 도구를 직접 부르는 ReAct + 코드 안전장치
            (물질 지정 고시는 항상 확인, 영향 여부는 "이번 개정 내용"의 회사 물질로 코드가 판단)
- regdb    (규제 DB 대조): 지정된 제품을 코드 규칙으로 판정

각 에이전트는 실패해도 예외를 밖으로 던지지 않는다 (call_tool이 errors에 기록). 한 에이전트가
실패해도 나머지 결과는 그대로 남는다 (task 단위 에러 격리).
"""
from __future__ import annotations

import asyncio
import re

from langchain.agents import create_agent
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.llm import prompts

from app.domain.citations import extract_quotes, official_dates
from app.domain.mentions import ABBREVIATIONS, name_variants

from .deps import AgentDeps
from .tooling import call_tool

AGENT_LABELS = {"us_feed": "해외 수집 에이전트 (미국 관보)", "eu_feed": "해외 수집 에이전트 (EU 법령)",
                "kr_feed": "국내 수집 에이전트 (법제처 행정규칙)",
                "regdb": "규제 DB 대조 에이전트"}


async def _us_feed(task: dict, deps: AgentDeps, errors: list[dict]) -> dict:
    agent = "us_feed"
    period = {k: task[k] for k in ("since", "until") if task.get(k)}         # 정기 브리핑: 고정 기간
    found = await call_tool(deps, agent, "search_federal_register",
                            {"days": task["days"], "limit": task.get("limit", 15), **period}, errors)
    candidates = (found or {}).get("documents", [])[: task.get("max_docs", 8)]
    focus = set(task.get("focus_cas") or [])
    sem = asyncio.Semaphore(3)                       # 동시 3건 (본문 다운로드는 서버 쪽에서 1건씩 + 캐시)

    async def fetch(doc: dict) -> dict | None:
        async with sem:
            return await call_tool(deps, agent, "get_federal_register_document",
                                   {"document_number": doc["document_number"], "max_chars": 200000}, errors)

    documents = []
    for full in await asyncio.gather(*(fetch(d) for d in candidates)):
        if not full or not full["substance_mentions"]:
            continue                                   # 우리 규제 DB 물질이 언급되지 않은 문서는 제외
        if full.get("text_warning"):                   # 본문 대신 요약본을 쓴 사실을 숨기지 않는다
            errors.append({"agent": agent, "tool": "get_federal_register_document", "kind": "degraded",
                           "error": f"{full['document_number']}: {full['text_warning']}"})
        in_scope = not focus or any(m["cas"] in focus for m in full["substance_mentions"])
        # 요청 범위가 있으면 그 물질의 문장을 근거로 뽑는다
        mentions = ([m for m in full["substance_mentions"] if m["cas"] in focus] if focus and in_scope
                    else full["substance_mentions"])[:6]
        terms = [t for m in mentions for t in name_variants(m["name_en"]) + ABBREVIATIONS.get(m["cas"], [])]
        documents.append({
            "region": "US", "agency": "EPA", "source": full["source"], "text_source": full["text_source"],
            **{k: full.get(k) for k in ("document_number", "title", "type", "publication_date",
                                        "comments_close_on", "effective_on", "html_url")},
            "mentions": mentions, "quotes": extract_quotes(full["text"], terms),
            "official_dates": official_dates(full), "in_scope": in_scope,
        })
    scoped = sum(d["in_scope"] for d in documents)
    return {"documents": documents,
            "summary": f"문서 {len(candidates)}건 중 회사 관련 물질 언급 {len(documents)}건"
                       + (f" · 요청 범위 {scoped}건" if focus else "")}


# ── EU 수집 (Step 11) — REACH·CLP 개정 법령 ─────────────────────────────────
SVHC_GAP = ("EU SVHC 후보 목록 추가는 법령이 아니라 ECHA 결정이라 자동 수집하지 않음 — "
            "규제 DB(확인일 기준)의 SVHC 최근 등재를 참고")


async def _eu_feed(task: dict, deps: AgentDeps, errors: list[dict]) -> dict:
    agent = "eu_feed"
    period = {k: task[k] for k in ("since", "until") if task.get(k)}
    found = await call_tool(deps, agent, "search_eu_acts", {"days": task.get("days", 90), "limit": 8, **period}, errors)
    acts = (found or {}).get("documents", [])[:6]
    focus = set(task.get("focus_cas") or [])
    errors.append({"agent": agent, "tool": "search_eu_acts", "kind": "degraded", "error": SVHC_GAP})
    documents = []
    for act in acts:
        full = await call_tool(deps, agent, "get_eu_act", {"celex": act["celex"], "max_chars": 200000}, errors)
        if not full:
            continue
        mentions = full["substance_mentions"]
        in_scope = bool(mentions) and (not focus or any(m["cas"] in focus for m in mentions))
        if focus and in_scope:
            mentions = [m for m in mentions if m["cas"] in focus]
        terms = [t for m in mentions[:6] for t in name_variants(m["name_en"]) + ABBREVIATIONS.get(m["cas"], [])]
        adopted = full["adopted_on"] or act["adopted_on"]
        documents.append({
            "region": "EU", "agency": "European Commission", "source": full["source"], "text_source": "full_text",
            "document_number": full["celex"], "title": act.get("title") or full["title"],
            "type": f"Commission Regulation ({', '.join(act.get('amends') or full.get('amends') or [])} 개정)",
            "publication_date": full["published_on"] or adopted, "effective_on": None, "comments_close_on": None,
            "html_url": full["html_url"], "ref_label": f"EU {full['number']}",
            "mentions": mentions[:6], "quotes": extract_quotes(full["text"], terms) if in_scope else [],
            "official_dates": [x for x in ({"label": "채택일", "date": adopted, "source": "EU 출판국"},
                                           {"label": "관보 게재일", "date": full["published_on"], "source": "EU 관보"})
                               if x["date"]],
            "in_scope": in_scope,
        })
    scoped = sum(d["in_scope"] for d in documents)
    return {"documents": documents,
            "summary": f"REACH·CLP 개정 법령 {len(acts)}건 중 회사 물질 언급 {scoped}건"}


# ── 국내 수집 (ReAct + 안전장치) ─────────────────────────────────────────────
# 안전장치: 물질 목록을 정하거나 바꾸는 고시는 LLM이 놓치거나 실패해도 항상 확인한다
# (시설·교육·업무처리 고시처럼 넓은 범위는 ReAct 에이전트가 찾는다)
KR_CORE_QUERIES = ["사고대비물질", "제한물질", "금지물질", "허가물질", "유해화학물질", "관리대상"]
KR_DESIGNATION = re.compile(r"지정|제한물질|금지물질|허가물질|분류 및 표시|관리대상|유해성심사")
KR_CHEMICAL = re.compile(r"화학|물질|유해|독성|위험물|산업안전|취급|사고대비|분류|표시")
KR_IRRELEVANT = re.compile(r"운영규정|운영지침|인사|조직|직제|공무원|위원회 운영|복무")
MAX_KR_DOCS = 10


def _kr_line(d: dict) -> str:
    return f"{d['serial']} | {d['issued_on']} | {d['agency']} | {d['title']} ({d['revision']})"


async def _kr_react(task: dict, deps: AgentDeps, errors: list[dict], seen: dict) -> tuple[list[str] | None, dict | None]:
    """LLM이 검색어를 정해 도구를 직접 부른다 (ReAct). (고른 일련번호 | 실패 시 None, 사용량)"""
    model = getattr(deps.llm, "agent_model", None)
    if model is None:
        return None, None
    days = task.get("days", 90)
    period = {k: task[k] for k in ("since", "until") if task.get(k)}
    outer = get_stream_writer()                       # 도구 호출이 화면 진행 패널에 보이도록 바깥 통로를 잡아 둔다

    @tool
    async def search_kr_admin_rules(query: str, body: bool = False) -> str:
        """법제처 국내 행정규칙(고시)을 최신 발령순으로 검색한다. body=true면 본문에서도 찾는다.
        결과 한 줄: 일련번호 | 발령일 | 소관부처 | 제목 (제개정 구분)"""
        found = await call_tool(deps, "kr_feed", "search_kr_admin_rules",
                                {"query": query, "days": days, "body": body, "limit": 10, **period}, errors,
                                writer=outer) or {}
        docs = found.get("documents", [])
        for d in docs:
            seen.setdefault(d["serial"], d)
        return "\n".join(_kr_line(d) for d in docs) or "결과 없음"

    names = sorted({(s.get("name_ko") or s["name_en"]).split(";")[0] for s in task.get("substances", [])})[:25]
    agent = create_agent(model, [search_kr_admin_rules],
                         system_prompt=prompts.KR_FEED_AGENT.format(
                             period_text=(f"{period['since']}~{period.get('until', '오늘')}" if period.get("since")
                                          else f"최근 {days}일"), substances=", ".join(names) or "(없음)"))
    try:
        out = await asyncio.wait_for(agent.ainvoke(
            {"messages": [{"role": "user", "content": task.get("question") or "최근 국내 화학물질 규제 변경을 찾아줘"}]},
            config={"recursion_limit": 12, "run_name": "kr_feed_react"}), timeout=deps.settings.llm_timeout_s)
    except Exception as exc:                          # 시간 초과·도구 호출 형식 오류·반복 상한 → 안전장치로
        errors.append({"agent": "kr_feed", "tool": "react", "kind": "degraded",
                       "error": f"국내 수집 에이전트(LLM) 실패({type(exc).__name__}) — 기본 검색어로 대신함"})
        return None, None
    messages = out["messages"]
    tokens = sum(int((getattr(m, "usage_metadata", None) or {}).get("total_tokens") or 0) for m in messages)
    usage = deps.llm.usage_for("kr_feed_agent", tokens)
    final = str(messages[-1].content)
    picked = [n for n in re.findall(r"\d{10,16}", final.split("선택:")[-1]) if n in seen]   # 도구가 준 번호만 인정
    return picked, usage


async def _kr_feed(task: dict, deps: AgentDeps, errors: list[dict]) -> dict:
    agent = "kr_feed"
    days = task.get("days", 90)
    period = {k: task[k] for k in ("since", "until") if task.get(k)}
    seen: dict[str, dict] = {}
    # ② 안전장치: 물질 지정 고시는 항상 찾는다 (키가 없으면 여기서 비활성을 알린다)
    core: list[str] = []
    for query in KR_CORE_QUERIES:
        found = await call_tool(deps, agent, "search_kr_admin_rules",
                                {"query": query, "days": days, "limit": 10, **period}, errors) or {}
        if found.get("source") == "disabled":
            errors.append({"agent": agent, "tool": "search_kr_admin_rules", "kind": "disabled",
                           "error": "국내 실시간 조회 비활성 (법제처 Open API 키 LAW_API_OC 미설정)"})
            return {"summary": "비활성 — 키 미설정"}
        for d in found.get("documents", []):
            seen.setdefault(d["serial"], d)
            if KR_DESIGNATION.search(d["title"]) and not KR_IRRELEVANT.search(d["title"]):
                core.append(d["serial"])
    # ① ReAct: LLM이 검색어를 더 정해 찾고 관련 고시를 고른다
    picked, usage = await _kr_react(task, deps, errors, seen)
    how = "LLM 선택" if picked is not None else "안전장치(기본 검색어)"
    # LLM이 고른 고시도 화학물질 관련 제목이어야 싣는다 (정기 예시 W41에서 "신의료기술 평가" 고시를 고름)
    picked = [s for s in (picked or []) if KR_CHEMICAL.search(seen[s]["title"]) and not KR_IRRELEVANT.search(seen[s]["title"])]
    core = sorted(dict.fromkeys(core), key=lambda n: seen[n]["issued_on"] or "", reverse=True)
    candidates = list(dict.fromkeys(picked + core))[:MAX_KR_DOCS]

    # ③ 확인: 본문을 받아 "이번 개정 내용"에 회사 물질이 있는지 코드가 판단
    focus = set(task.get("focus_cas") or [])
    sem = asyncio.Semaphore(2)

    async def fetch(serial: str) -> dict | None:
        async with sem:
            return await call_tool(deps, agent, "get_kr_admin_rule", {"serial": serial}, errors)

    documents = []
    for full in await asyncio.gather(*(fetch(s) for s in candidates)):
        if not full:
            continue
        mentions = full["substance_mentions"]
        in_scope = bool(mentions) and (not focus or any(m["cas"] in focus for m in mentions))
        if not in_scope and full["serial"] not in picked:
            continue                                   # 기본 검색에만 걸리고 회사 물질이 없는 고시는 싣지 않는다
        if focus and in_scope:
            mentions = [m for m in mentions if m["cas"] in focus]
        note = ""
        if not full["change_text_available"] and full["body_mentions"]:
            note = (f"개정 내용 미제공 — 현행 본문에 회사 물질 {len(full['body_mentions'])}종 언급, 바뀐 내용은 원문 확인 필요")
        terms = [t for m in mentions for t in m["matched_terms"] + [m["cas"]]]
        documents.append({
            "region": "KR", "agency": full["agency"], "source": full["source"], "text_source": "change_text",
            "document_number": full["serial"], "title": full["title"], "type": f"{full['kind']} {full['revision']}",
            "publication_date": full["issued_on"], "effective_on": full["effective_on"], "comments_close_on": None,
            "html_url": full["html_url"], "ref_label": f"{full['agency']}{full['kind']} 제{full['number']}호",
            "mentions": mentions[:6], "quotes": extract_quotes(full["change_text"], terms) if in_scope else [],
            "official_dates": [x for x in ({"label": "발령일", "date": full["issued_on"], "source": "법제처"},
                                           {"label": "시행일", "date": full["effective_on"], "source": "법제처"})
                               if x["date"]],
            "in_scope": in_scope, "note": note,
        })
    scoped = sum(d["in_scope"] for d in documents)
    return {"documents": documents, "usage": [usage] if usage else [],
            "summary": f"{how} · 고시 {len(candidates)}건 확인 · 회사 물질이 개정 내용에 있는 고시 {scoped}건"}


async def _regdb(task: dict, deps: AgentDeps, errors: list[dict]) -> dict:
    judgements = {}
    for pid in task["product_ids"]:
        judged = await call_tool(deps, "regdb", "judge_product_compliance", {"product_id": pid}, errors)
        if judged:
            judgements[pid] = judged
    return {"judgements": judgements, "summary": f"제품 {len(judgements)}개 판정"}


RUNNERS = {"us_feed": _us_feed, "eu_feed": _eu_feed, "kr_feed": _kr_feed, "regdb": _regdb}


async def run_subagent(payload: dict, deps: AgentDeps) -> dict:
    """Send로 호출되는 노드. payload = {"task": {...}}"""
    task = payload["task"]
    agent = task["agent"]
    writer = get_stream_writer()
    writer({"type": "agent_start", "agent": agent, "label": AGENT_LABELS[agent], "purpose": task.get("purpose", "")})
    errors: list[dict] = []
    try:
        result = await RUNNERS[agent](task, deps, errors)
    except Exception as exc:                          # 예상 못 한 오류도 이 에이전트 안에서 끝낸다
        errors.append({"agent": agent, "tool": "-", "error": f"{type(exc).__name__}: {exc}"[:300]})
        result = {"summary": "실패"}
    writer({"type": "agent_end", "agent": agent, "ok": not [e for e in errors if e.get("kind") != "disabled"],
            "summary": result.get("summary", "")})
    update = {"errors": errors}
    if result.get("documents"):
        update["documents"] = result["documents"]
    if result.get("judgements"):
        update["judgements"] = result["judgements"]
    if result.get("usage"):
        update["usage"] = result["usage"]
    return update
