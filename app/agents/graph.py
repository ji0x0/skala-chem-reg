"""v2 Supervisor 그래프 (개선 버전). 경로를 한 갈래씩 붙여 간다.

route ─ chat ────▶ chat_answer ─────────────────────────────────────────────▶ finalize
      ├ lookup ──▶ lookup (물질·제품 → 등재 조회·코드 판정 → 근거 답변) ─────▶ finalize
      └ briefing ▶ plan ▶ gate ═Send═▶ [us_feed | kr_feed | regdb] (병렬) ▶ review ─부족─▶ (재조사)
                    ▶ summarize(요약·근거 번역·무결성) ▶ impact(코드 판정) ▶ write(스트리밍)
                    ▶ guard ▶ validate ─불합격(상한 내)─▶ write
                                      └─▶ approval(영향 제품 공유 승인, interrupt) ▶ finalize

모든 노드는 AgentDeps를 functools.partial로 주입받는 순수 비동기 함수다.
진행 상황은 get_stream_writer()로 이벤트를 보내고, Step 4에서 SSE로 화면에 흘려보낸다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date
from functools import partial, wraps

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from app.domain import integrity
from app.domain.cas import find_cas_numbers
from app.domain.citations import (citations_text, from_document, from_finding, from_listing,
                                  quote_in_source)
from app.domain.mentions import find_substance_mentions
from app.llm.fake import FakeLLM
from app.llm.schemas import DocumentSummary

from .deps import AgentDeps
from .state import RESET, AgentState, per_turn_reset
from .subagents import run_subagent
from .tooling import call_tool

log = logging.getLogger(__name__)
FALLBACK = FakeLLM()      # LLM 구조화 출력이 깨졌을 때 쓰는 코드 규칙

NODE_LABELS = {"route": "질문 분류", "chat_answer": "답변", "lookup": "규제 조회·판정",
               "plan": "브리핑 계획", "gate": "계획 검증", "review": "수집 결과 확인",
               "summarize": "문서 요약·근거 번역", "impact": "제품 영향 판정", "write": "브리핑 작성",
               "guard": "사실·근거 검사", "validate": "품질 검토", "approval": "담당자 승인",
               "finalize": "최종 정리"}
FEED_REGIONS = {"US"}                 # 변경 문서를 자동 수집하는 지역 (국내 KR은 키 설정 시)
REQUIRED_SECTIONS = ["요약", "규제 변경", "제품 영향", "할 일", "확인이 필요한"]

# 한글 물질명 중 일상어와 겹치는 것 (예: 납 ↔ 납품·납기) → 한글 이름 매칭에서 제외 (CAS·영문으로만 인정)
KO_AMBIGUOUS = {"7439-92-1"}


def node(name: str):
    """노드 시작을 진행 이벤트로 알리고, 소요 시간을 로그로 남긴다."""
    def deco(fn):
        @wraps(fn)
        async def wrapper(state, deps: AgentDeps):
            get_stream_writer()({"type": "node_start", "node": name, "label": NODE_LABELS.get(name, name)})
            started = time.perf_counter()
            result = await fn(state, deps)
            log.info("노드 완료", extra={"node": name,
                                       "latency_ms": int((time.perf_counter() - started) * 1000)})
            return result
        return wrapper
    return deco


def history_text(state: AgentState, turns: int = 6) -> str:
    return "\n".join(f"{m['role']}: {m['content'][:300]}" for m in state.get("history", [])[-turns:])


def token_writer(attempt: int = 1):
    writer = get_stream_writer()
    return lambda piece: writer({"type": "token", "delta": piece, "attempt": attempt})


# ── 1. 질문 분류 ─────────────────────────────────────────────────────────────
@node("route")
async def route_node(state: AgentState, deps: AgentDeps) -> dict:
    question = state["question"]
    decision, usage = await deps.llm.route(question)
    if decision is None:                                    # 형식 오류 → 코드 규칙
        decision, _ = await FALLBACK.route(question)
        decision.reasoning = "(LLM 형식 오류 — 코드 규칙으로 분류) " + decision.reasoning
    get_stream_writer()({"type": "route", "route": decision.route, "reasoning": decision.reasoning})
    return {**per_turn_reset(question), "route": decision.route, "route_reasoning": decision.reasoning,
            "usage": [RESET, usage]}


# ── 2. 일반 대화 ─────────────────────────────────────────────────────────────
SERVICE_GUIDE = """이 서비스가 할 수 있는 일:
1. 규제 조회: 물질 이름·CAS(예: 트리클로로에틸렌, 79-01-6)나 제품 ID(예: P003)가 국내외 어떤 규제에 해당하는지 판정과 근거를 알려 준다
2. 규제 브리핑: "이번 주 미국 EPA 규제 변경 브리핑해줘"처럼 요청하면 최근 규제 문서를 수집해 한국어로 요약하고, 회사 제품 영향과 할 일·기한을 정리한다
3. 다루는 규제: 국내 화학물질관리법·산업안전보건법, 미국 TSCA, EU REACH(SVHC·부속서 XVII)·CLP, 중국 우선관리 화학물질, 일본 화심법
4. 영향 제품을 사내에 공유하기 전에는 담당자 승인을 받는다"""


@node("chat_answer")
async def chat_answer_node(state: AgentState, deps: AgentDeps) -> dict:
    answer, usage = await deps.llm.answer(state["question"], context=SERVICE_GUIDE, citations="",
                                          history=history_text(state), on_token=token_writer())
    return {"final": answer, "usage": [usage]}


# ── 3. 규제 조회 (lookup) ────────────────────────────────────────────────────
def resolve_substances(question: str, deps: AgentDeps) -> list[str]:
    """질문 속 물질 → CAS. ① CAS 그대로 ② 영문 이름·약어 ③ 한글 이름 (모두 코드 규칙)."""
    found = find_cas_numbers(question)
    found += [m["cas"] for m in find_substance_mentions(question, deps.substances)]
    for s in deps.substances:
        core = re.sub(r"\s*\(.*?\)\s*", "", s.get("name_ko") or "").strip()
        if s["cas"] not in KO_AMBIGUOUS and len(core) >= 2 and core in question:
            found.append(s["cas"])
    return list(dict.fromkeys(found))


@node("lookup")
async def lookup_node(state: AgentState, deps: AgentDeps) -> dict:
    question = state["question"]
    errors: list[dict] = []
    cas_list = resolve_substances(question, deps)[:5]
    product_ids = [p for p in dict.fromkeys(re.findall(r"P\d{3}", question.upper()))
                   if p in deps.product_ids][:3]
    get_stream_writer()({"type": "plan", "substances": cas_list, "products": product_ids})

    context, citations, judgements = [], [], {}
    for cas in cas_list:
        found = await call_tool(deps, "lookup", "lookup_substance", {"keyword": cas}, errors)
        if not found or not found["listings"]:
            context.append(f"- CAS {cas}: 규제 DB에 등재 정보 없음")
            continue
        name = found["substances"][0]["name_ko"] if found["substances"] else cas
        context.append(f"- 물질 {name} (CAS {cas})의 등재 규제:")
        for lst in found["listings"]:
            c = from_listing(len(citations) + 1, lst)
            citations.append(c.to_dict())
            context.append(f"  [{c.id}] {lst['region']} {lst['list_name']} {lst.get('entry_ref') or ''} "
                           f"{lst.get('condition_ko') or ''}".rstrip())
    for pid in product_ids:
        judged = await call_tool(deps, "lookup", "judge_product_compliance", {"product_id": pid}, errors)
        if not judged:
            continue
        judgements[pid] = judged
        context.append(f"- 제품 {pid} {judged['product_name']} ({judged['product_form']}, "
                       f"수출 {', '.join(judged['export_regions'])}) 판정 {judged['summary']}:")
        for f in judged["findings"]:
            if f["outcome"] == "below":
                continue
            c = from_finding(len(citations) + 1, f)
            citations.append(c.to_dict())
            context.append(f"  [{c.id}] {f['outcome']} · {f['region']} {f['list_name']} · "
                           f"{f['substance']} {f['wt_pct']:g}% · {f['reason']}")
        for s in judged["skipped"][:5]:
            context.append(f"  (적용 제외) {s['substance']} · {s['reason']}")

    if not cas_list and not product_ids:
        context.append("질문에서 물질(이름·CAS)이나 제품 ID(P001 형식)를 찾지 못함. 사용자에게 물질 이름·CAS 또는 "
                       "제품 ID를 알려 달라고 요청할 것")
    answer, usage = await deps.llm.answer(question, context="\n".join(context),
                                          citations=citations_text(citations),
                                          history=history_text(state), on_token=token_writer())
    return {"final": answer, "citations": citations, "judgements": judgements, "errors": errors,
            "usage": [usage]}


# ── 4. 브리핑: 계획 ──────────────────────────────────────────────────────────
@node("plan")
async def plan_node(state: AgentState, deps: AgentDeps) -> dict:
    plan, usage = await deps.llm.plan(state["question"], date.today().isoformat())
    if plan is None:
        plan, _ = await FALLBACK.plan(state["question"], date.today().isoformat())
    return {"plan": plan.model_dump(), "usage": [usage]}


# ── 5. 브리핑: 계획 검증 (가드 게이트 — LLM 계획을 코드로 바로잡는다) ──────────
@node("gate")
async def gate_node(state: AgentState, deps: AgentDeps) -> dict:
    plan, question, corrections, gaps = dict(state["plan"]), state["question"], [], []

    products = [p for p in plan.get("product_ids", []) if p in deps.product_ids]
    if len(products) != len(plan.get("product_ids", [])):
        corrections.append(f"없는 제품 ID 제외: {set(plan['product_ids']) - set(products)}")
    for p in re.findall(r"P\d{3}", question.upper()):        # LLM이 놓친 제품 ID 보정
        if p in deps.product_ids and p not in products:
            products.append(p)
            corrections.append(f"질문의 제품 ID {p} 추가")
    cas_list = resolve_substances(" ".join(plan.get("substances", [])) + " " + question, deps)

    regions = plan.get("regions") or ["KR", "US"]
    tasks = []
    if "US" in regions:
        tasks.append({"agent": "us_feed", "days": plan.get("days", 7), "purpose": "미국 관보 TSCA 문서 수집"})
    if "KR" in regions:
        tasks.append({"agent": "kr_feed", "purpose": "국내 행정규칙 개정 수집"})
    no_feed = [r for r in regions if r not in FEED_REGIONS | {"KR"}]
    if no_feed:
        gaps.append(f"{', '.join(no_feed)} 변경 문서 자동 수집은 아직 지원하지 않음 — 등재 목록 대조로만 확인")
    if products or no_feed:
        # 언급 제품이 있으면 그 제품만, 수집이 안 되는 지역만 요청했으면 전체 제품을 목록 대조
        tasks.append({"agent": "regdb", "product_ids": products or deps.product_ids,
                      "purpose": "제품 규제 판정"})
    plan.update(product_ids=products, cas=cas_list, regions=regions)
    get_stream_writer()({"type": "plan", "days": plan.get("days"), "regions": regions, "products": products,
                         "substances": cas_list, "tasks": [t["agent"] for t in tasks],
                         "corrections": corrections})
    return {"plan": plan, "corrections": corrections, "tasks": tasks, "gaps": gaps}


def dispatch(state: AgentState) -> list[Send] | str:
    """tasks를 조사 에이전트로 동시에 보낸다 (fan-out)."""
    if not state.get("tasks"):
        return "summarize"
    return [Send("research", {"task": t}) for t in state["tasks"]]


# ── 6. 브리핑: 수집 결과 확인 (Dynamic Planning — 부족하면 범위를 넓혀 다시) ────
@node("review")
async def review_node(state: AgentState, deps: AgentDeps) -> dict:
    rnd = state.get("research_round", 0) + 1
    plan, tasks, reasons = state["plan"], [], []
    ran_us = any(t["agent"] == "us_feed" for t in state.get("tasks", []))
    if ran_us and not state.get("documents") and rnd < 2 and plan.get("days", 7) < 30:
        tasks.append({"agent": "us_feed", "days": 30, "purpose": "관련 문서가 없어 기간을 30일로 넓혀 재검색"})
        reasons.append(f"최근 {plan.get('days')}일에 회사 관련 문서가 없어 30일로 확대")
        plan = {**plan, "days": 30}
    gaps = list(state.get("gaps", []))
    for e in state.get("errors", []):
        gaps.append(e["error"] if e.get("kind") in ("disabled", "degraded") else f"{e['agent']}의 {e['tool']} 조회 실패")
    gaps = list(dict.fromkeys(gaps))
    get_stream_writer()({"type": "review", "round": rnd, "sufficient": not tasks, "reasons": reasons,
                         "documents": len(state.get("documents", [])), "gaps": gaps})
    return {"research_round": rnd, "tasks": tasks, "plan": plan, "gaps": gaps}


def after_review(state: AgentState) -> list[Send] | str:
    return dispatch(state) if state.get("tasks") else "summarize"


# ── 7. 브리핑: 문서 요약 + 근거 문장 번역 + 무결성 검사 ──────────────────────
def _doc_meta(doc: dict) -> str:
    dates = " / ".join(f"{d['label']}: {d['date']}" for d in doc.get("official_dates", []))
    return f"{doc['title']}\n기관: {doc.get('agency')} / 종류: {doc.get('type')} / {dates}"


@node("summarize")
async def summarize_node(state: AgentState, deps: AgentDeps) -> dict:
    writer = get_stream_writer()
    documents = state.get("documents", [])
    citations: list[dict] = []
    usage_all: list[dict] = []
    sem = asyncio.Semaphore(2)

    async def summarize(doc: dict):
        async with sem:
            quotes = doc["quotes"] or [doc["title"]]
            glossary = await call_tool(deps, "summarize", "glossary_lookup", {"text": " ".join(quotes)}) or []
            glossary_text = "\n".join(f"- {g['term']} → {g['ko']}" for g in glossary)
            summary, usage = await deps.llm.summarize_document(_doc_meta(doc), quotes, glossary_text)
            return doc, quotes, summary, usage

    summaries = []
    for doc, quotes, summary, usage in await asyncio.gather(*(summarize(d) for d in documents)):
        usage_all.append(usage)
        if summary is None:                                 # 형식 오류 → 원문 제목만으로 최소 요약
            summary = DocumentSummary(title_ko=doc["title"], summary_ko="(요약 형식 오류 — 근거 원문을 확인하세요)",
                                      action_ko="확인 필요")
        produced = " ".join([summary.summary_ko, summary.action_ko] + [d.date for d in summary.key_dates])
        check = integrity.check(" ".join(quotes), produced, reference=_doc_meta(doc))
        cite_ids = []
        for i, quote in enumerate(quotes):
            ko = summary.quote_ko[i] if i < len(summary.quote_ko) else ""
            # 근거 문장 번역도 같은 검사: 지어낸 숫자·날짜가 있으면 번역을 버리고 원문만 보여 준다
            if ko and not integrity.check(quote, ko).ok:
                ko = ""
            c = from_document(len(state.get("citations", [])) + len(citations) + 1, doc, quote)
            c.translation_ko = ko
            assert quote_in_source(quote, " ".join(quotes))
            citations.append(c.to_dict())
            cite_ids.append(c.id)
        item = {"document_number": doc["document_number"], "region": doc["region"],
                "title_ko": summary.title_ko, "summary_ko": summary.summary_ko, "action_ko": summary.action_ko,
                "official_dates": doc["official_dates"], "key_dates": [d.model_dump() for d in summary.key_dates],
                "mentions": [{"cas": m["cas"], "name_ko": m["name_ko"]} for m in doc["mentions"]],
                "citation_ids": cite_ids, "integrity": check.to_dict(), "url": doc.get("html_url")}
        summaries.append(item)
        # 요약은 일부 날짜를 생략할 수 있다: 지어낸 사실은 오류, 빠진 날짜는 경고로만 알린다
        invented = {k: v for k, v in check.to_dict().items() if k.startswith("extra_") and v}
        item["integrity"] = {"invented": invented, "omitted_dates": check.missing_dates,
                             "omitted_cas": check.missing_cas}
        writer({"type": "summary", "document_number": doc["document_number"], "title_ko": summary.title_ko,
                "invented": invented, "omitted_dates": check.missing_dates,
                "translations_kept": sum(1 for c in citations[-len(cite_ids):] if c["translation_ko"]),
                "citations": len(cite_ids)})
    return {"summaries": summaries, "citations": citations, "usage": usage_all}


# ── 8. 브리핑: 제품 영향 판정 (코드) ─────────────────────────────────────────
@node("impact")
async def impact_node(state: AgentState, deps: AgentDeps) -> dict:
    plan = state["plan"]
    judgements = dict(state.get("judgements", {}))
    impacts, citations = [], []
    base_id = len(state.get("citations", []))

    def add_impact(pid: str, findings: list[dict], document: str | None):
        for f in findings:
            c = from_finding(base_id + len(citations) + 1, f)
            citations.append(c.to_dict())
            f["citation_id"] = c.id
        j = judgements[pid]
        impacts.append({"product_id": pid, "product_name": j["product_name"], "document_number": document,
                        "export_regions": j["export_regions"], "findings": findings})

    # ① 수집 문서에 언급된 물질이 들어간 제품 → 그 문서 지역의 판정만
    for s in state.get("summaries", []):
        cas = [m["cas"] for m in s["mentions"]]
        hits = await call_tool(deps, "impact", "find_products_by_cas", {"cas_numbers": cas}) or []
        for pid in sorted({h["product_id"] for h in hits}):
            if pid not in judgements:
                judgements[pid] = await call_tool(deps, "impact", "judge_product_compliance",
                                                  {"product_id": pid})
            findings = [f for f in judgements[pid]["findings"]
                        if f["cas"] in cas and f["region"] == s["region"] and f["outcome"] != "below"]
            if findings:
                add_impact(pid, findings, s["document_number"])
    # ② 질문에 언급된 제품·물질 → 요청 지역의 판정
    for pid, j in state.get("judgements", {}).items():
        findings = [f for f in j["findings"] if f["region"] in plan["regions"] and f["outcome"] != "below"
                    and (not plan.get("cas") or f["cas"] in plan["cas"] or pid in plan.get("product_ids", []))]
        if findings and not any(i["product_id"] == pid and i["document_number"] is None for i in impacts):
            add_impact(pid, findings, None)
    get_stream_writer()({"type": "impact", "products": sorted({i["product_id"] for i in impacts}),
                         "findings": sum(len(i["findings"]) for i in impacts)})
    return {"impacts": impacts, "judgements": judgements, "citations": citations}


# ── 9. 브리핑: 작성 (토큰 스트리밍) ──────────────────────────────────────────
def _summaries_text(state: AgentState) -> str:
    lines = []
    for s in state.get("summaries", []):
        dates = ", ".join(f"{d['label']} {d['date']}" for d in s["official_dates"])
        lines.append(f"- [{s['region']}] {s['title_ko']} ({dates})\n  요약: {s['summary_ko']}\n"
                     f"  할 일: {s['action_ko']}\n  근거: {', '.join(f'[{i}]' for i in s['citation_ids'])}")
    return "\n".join(lines) or "(기간 내 회사 관련 규제 문서 없음)"


def _impacts_text(state: AgentState) -> str:
    lines = []
    for i in state.get("impacts", []):
        src = f"관보 {i['document_number']}" if i["document_number"] else "질문 언급 제품"
        lines.append(f"- {i['product_id']} {i['product_name']} (수출 {', '.join(i['export_regions'])}, {src})")
        for f in i["findings"]:
            lines.append(f"  [{f['citation_id']}] {f['outcome']} · {f['region']} {f['list_name']} · "
                         f"{f['substance']} {f['wt_pct']:g}% · {f['reason']}")
    gaps = state.get("gaps", [])
    if gaps:
        lines.append("확인하지 못한 항목: " + " / ".join(gaps))
    return "\n".join(lines) or "(영향 제품 없음)"


@node("write")
async def write_node(state: AgentState, deps: AgentDeps) -> dict:
    attempt = state.get("writing_attempts", 0) + 1        # 성공·실패와 무관하게 항상 증가 (무한 루프 방지)
    get_stream_writer()({"type": "draft_start", "attempt": attempt})
    draft, usage = await deps.llm.write_briefing(
        state["question"], _summaries_text(state), _impacts_text(state),
        citations_text(state.get("citations", [])), state.get("validation_feedback"),
        on_token=token_writer(attempt))
    return {"draft": strip_code_fence(draft), "writing_attempts": attempt, "usage": [usage]}


def strip_code_fence(text: str) -> str:
    """모델이 답 전체를 ```markdown ... ``` 으로 감싸면 화면에 Markdown이 그대로 보인다 → 벗긴다."""
    m = re.fullmatch(r"\s*```[a-zA-Z]*\n(.*?)\n?```\s*", text, flags=re.DOTALL)
    return m.group(1) if m else text


# ── 10. 브리핑: 사실·근거 검사 (코드) ────────────────────────────────────────
@node("guard")
async def guard_node(state: AgentState, deps: AgentDeps) -> dict:
    draft = state["draft"]
    citations = state.get("citations", [])
    source = " ".join([c["quote"] for c in citations] + [c.get("translation_ko", "") for c in citations]
                      + [_summaries_text(state), _impacts_text(state)])
    reference = " ".join(_doc_meta(d) for d in state.get("documents", [])) + f" {date.today().isoformat()}"
    report = integrity.check(source, draft, reference=reference)
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", draft)}
    valid_ids = {c["id"] for c in citations}
    result = {"invented": {k: v for k, v in report.to_dict().items() if k.startswith("extra_") and v},
              "unknown_citations": sorted(cited - valid_ids),
              "missing_sections": [s for s in REQUIRED_SECTIONS if s not in draft],
              "uncited": not cited and bool(citations)}
    get_stream_writer()({"type": "guard", **result})
    return {"guard": result}


# ── 11. 브리핑: 품질 검토 (LLM-as-Judge + 코드 검사) ─────────────────────────
@node("validate")
async def validate_node(state: AgentState, deps: AgentDeps) -> dict:
    attempts = state.get("validation_attempts", 0) + 1
    g = state.get("guard", {})
    code_problems = []
    if g.get("invented"):
        code_problems.append(f"근거에 없는 사실 {g['invented']}을(를) 제거할 것")
    if g.get("unknown_citations"):
        code_problems.append(f"없는 근거 번호 {g['unknown_citations']}를 쓰지 말 것")
    if g.get("missing_sections"):
        code_problems.append(f"필수 절 누락: {', '.join(g['missing_sections'])}")
    if g.get("uncited"):
        code_problems.append("근거 번호 [n]을 붙일 것")
    judgement, usage = await deps.llm.judge(state["question"], state["draft"],
                                            citations_text(state.get("citations", [])),
                                            json.dumps(code_problems, ensure_ascii=False) if code_problems else "문제 없음")
    llm_ok = judgement.is_acceptable if judgement else True
    passed = llm_ok and not code_problems
    feedback = None
    if not passed:
        feedback = " / ".join(code_problems + ([judgement.feedback] if judgement and not llm_ok and judgement.feedback else []))
    scores = judgement.model_dump(exclude={"feedback", "is_acceptable"}) if judgement else {}
    get_stream_writer()({"type": "validation", "attempt": attempts, "passed": passed, "scores": scores,
                         "feedback": feedback})
    return {"validation_attempts": attempts, "validation_feedback": feedback,
            "judgement": {**scores, "passed": passed}, "usage": [usage] if usage else []}


def after_validate(state: AgentState, max_writing: int = 2, max_validation: int = 3) -> str:
    if state.get("validation_feedback") is None:
        return "approval"
    if state.get("writing_attempts", 0) >= max_writing or state.get("validation_attempts", 0) >= max_validation:
        return "approval"                                  # 상한 도달 → 미달 사실을 알리고 진행
    return "write"


# ── 12. 브리핑: 담당자 승인 (Human-in-the-loop) ──────────────────────────────
@node("approval")
async def approval_node(state: AgentState, deps: AgentDeps) -> dict:
    impacted = [{"product_id": i["product_id"], "product_name": i["product_name"],
                 "document_number": i["document_number"],
                 "outcomes": sorted({f["outcome"] for f in i["findings"]})} for i in state.get("impacts", [])]
    if not impacted:
        return {"approval": {"required": False}}
    # interrupt: 그래프가 여기서 멈추고 체크포인터에 상태를 저장한다.
    # API가 Command(resume={...})로 승인 결과를 넣으면 이 줄부터 이어서 실행된다.
    decision = interrupt({"type": "approval_required", "impacted_products": impacted,
                          "message": "영향 제품을 영업·생산·고객 대응 담당에게 공유하기 전에 규제 담당자 승인이 필요합니다."})
    decision = decision if isinstance(decision, dict) else {"approved": bool(decision)}
    return {"approval": {"required": True, "impacted_products": impacted,
                         "approved": bool(decision.get("approved")),
                         "approver": decision.get("approver", "규제 담당자"),
                         "comment": decision.get("comment", "")}}


# ── 마지막. 최종 정리 ────────────────────────────────────────────────────────
@node("finalize")
async def finalize_node(state: AgentState, deps: AgentDeps) -> dict:
    final = state.get("final") or state.get("draft") or "죄송합니다. 요청을 처리하지 못했습니다."
    judgement = state.get("judgement") or {}
    if state.get("draft") and judgement and not judgement.get("passed", True):
        final += ("\n\n---\n> ⚠️ 브리핑이 품질 기준을 완전히 충족하지 못했습니다 "
                  f"(검토 의견: {state.get('validation_feedback')}). 근거 원문을 직접 확인해 주세요.")
    approval = state.get("approval") or {}
    if approval.get("required"):
        status = "승인 — 관련 부서에 공유" if approval.get("approved") else "반려 — 공유하지 않음"
        final += f"\n\n## 승인 결과\n- {approval.get('approver')}: **{status}**"
        if approval.get("comment"):
            final += f" ({approval['comment']})"
    if any(c.get("status") != "official" for c in state.get("citations", [])):
        final += "\n\n> ℹ️ 규제 목록 근거 일부는 공식 원본 확인 전 데이터입니다. 법률 자문이 아니며 최종 판단은 담당자가 합니다."
    usage = state.get("usage", [])
    meta = {"tokens": sum(u.get("tokens", 0) for u in usage),
            "usd": round(sum(u.get("usd", 0.0) for u in usage), 6)}
    get_stream_writer()({"type": "final", "content": final, "citations": state.get("citations", []),
                         "usage": meta})
    return {"final": final, "history": [{"role": "user", "content": state["question"]},
                                        {"role": "assistant", "content": final}]}


def after_route(state: AgentState) -> str:
    return {"chat": "chat_answer", "lookup": "lookup", "briefing": "plan"}.get(state["route"], "chat_answer")


def build_graph(deps: AgentDeps, checkpointer=None):
    g = StateGraph(AgentState)
    bind = lambda fn: partial(fn, deps=deps)   # noqa: E731 — 명시적 의존성 주입
    g.add_node("route", bind(route_node))
    g.add_node("chat_answer", bind(chat_answer_node))
    g.add_node("lookup", bind(lookup_node))
    for name, fn in [("plan", plan_node), ("gate", gate_node), ("research", run_subagent),
                     ("review", review_node), ("summarize", summarize_node), ("impact", impact_node),
                     ("write", write_node), ("guard", guard_node), ("validate", validate_node),
                     ("approval", approval_node)]:
        g.add_node(name, bind(fn))
    g.add_node("finalize", bind(finalize_node))

    g.add_edge(START, "route")
    g.add_conditional_edges("route", after_route, ["chat_answer", "lookup", "plan"])
    g.add_edge("chat_answer", "finalize")
    g.add_edge("lookup", "finalize")
    g.add_edge("plan", "gate")
    g.add_conditional_edges("gate", dispatch, ["research", "summarize"])
    g.add_edge("research", "review")                       # 병렬 에이전트가 모두 끝나면 한 번 실행 (fan-in)
    g.add_conditional_edges("review", after_review, ["research", "summarize"])
    g.add_edge("summarize", "impact")
    g.add_edge("impact", "write")
    g.add_edge("write", "guard")
    g.add_edge("guard", "validate")
    s = deps.settings
    g.add_conditional_edges("validate", partial(after_validate, max_writing=2, max_validation=3),
                            ["write", "approval"])
    g.add_edge("approval", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
