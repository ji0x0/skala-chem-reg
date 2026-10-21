"""v2 Supervisor 그래프 (개선 버전). 경로를 한 갈래씩 붙여 간다.

route ─ chat ────▶ chat_answer ─────────────────────────────────────────────▶ finalize
      ├ lookup ──▶ lookup (물질·제품 → 등재 조회·코드 판정 → 근거 답변) ─────▶ finalize
      └ briefing ▶ plan ▶ gate ═Send═▶ [us_feed | kr_feed | regdb] (병렬) ▶ review ─부족─▶ (재조사)
                    ▶ summarize(요약·근거 번역·무결성) ▶ impact(코드 판정) ▶ write(스트리밍)
                    ▶ guard ▶ validate ─불합격(상한 내)─▶ write
                                      └─▶ finalize
(대화 답변에는 승인이 없다 — 2026-10-21 결정. 사람의 확인은 규제 DB 갱신 반영·정기 브리핑 검토에만)

모든 노드는 AgentDeps를 functools.partial로 주입받는 순수 비동기 함수다.
진행 상황은 get_stream_writer()로 이벤트를 보내고, Step 4에서 SSE로 화면에 흘려보낸다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from functools import partial

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.domain import integrity
from app.domain.coverage import SUPPORTED, SUPPORTED_TEXT, regions_in
from app.domain.citations import (citations_text, from_document, from_finding, from_listing, from_regulation,
                                  quote_in_source)
from app.domain.judge import OUTCOME_KO
from app.llm.fake import FakeLLM
from app.llm.schemas import DocumentSummary

from .deps import AgentDeps
from .state import RESET, AgentState, per_turn_reset
from .common import history_text, node, resolve_substances, token_writer
from .subagents import run_subagent
from .understand import VERIFIED_ON, understand_node
from .tooling import call_tool

log = logging.getLogger(__name__)
FALLBACK = FakeLLM()      # LLM 구조화 출력이 깨졌을 때 쓰는 코드 규칙

FEED_REGIONS = {"US", "KR"}           # 변경 문서를 자동 수집하는 지역 (미국 연방 관보, 국내 법제처 행정규칙)
KR_MIN_DAYS, KR_WIDE_DAYS = 90, 365   # 국내 고시는 개정이 드물다 → 최소 90일, 없으면 1년으로 넓혀 다시
REQUIRED_SECTIONS = ["요약", "규제 변경", "제품 영향", "할 일", "확인이 필요한"]



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
4. 다루는 지역: 국내·미국·EU·중국·일본. 변경 자동 수집: 미국 연방 관보(최근 30일)·국내 법제처 고시(최근 1년)
5. 규제 목록 확인일: """ + VERIFIED_ON + """ (공식 원본에서 가져오거나 대조한 9,351행)
6. 다루지 않는 것: 그 밖의 국가·제도(RoHS 등), 물성·독성 수치, 대체 물질 추천, 법률 판단"""


@node("chat_answer")
async def chat_answer_node(state: AgentState, deps: AgentDeps) -> dict:
    answer, usage = await deps.llm.answer(state["question"], context=SERVICE_GUIDE, citations="",
                                          history=history_text(state), on_token=token_writer())
    return {"final": answer, "usage": [usage]}


# ── 3. 규제 조회 (lookup) ────────────────────────────────────────────────────
@node("lookup")
async def lookup_node(state: AgentState, deps: AgentDeps) -> dict:
    question = state["question"]
    errors: list[dict] = []
    slots = state.get("slots") or {}
    if slots:                                   # Step 9: 이해 노드가 뽑은 대상 (후속 질문이면 앞 턴 대상)
        cas_list, product_ids = slots.get("cas", [])[:5], slots.get("products", [])[:3]
        unknown, unsupported = slots.get("unknown_products", []), slots.get("unsupported", [])
    else:
        cas_list = resolve_substances(question, deps)[:5]
        asked = list(dict.fromkeys(re.findall(r"P\d{3}", question.upper())))
        product_ids = [p for p in asked if p in deps.product_ids][:3]
        unknown = [p for p in asked if p not in deps.product_ids]
        _, unsupported = regions_in(question)
    get_stream_writer()({"type": "plan", "substances": cas_list, "products": product_ids})

    base = len(state.get("citations", []))     # 앞 노드(inform)의 근거 다음 번호부터
    context, citations, judgements, holder_lines = [], [], {}, {}
    for pid in unknown:                     # 없는 제품을 "못 찾음"으로 뭉개지 않고 명확히 알린다 (판정을 지어내지 않게)
        context.append(f"- 제품 {pid}: 등록되지 않은 제품 — 판정할 수 없음. 제품 관리 화면에서 먼저 등록해야 함")
    for cas in cas_list:
        found = await call_tool(deps, "lookup", "lookup_substance", {"keyword": cas}, errors)
        if not found or not found["listings"]:
            context.append(f"- CAS {cas}: 규제 DB에 등재 정보 없음")
            continue
        name = found["substances"][0]["name_ko"] if found["substances"] else cas
        # "이 물질이 든 제품"을 등재 목록보다 먼저 — 목록이 길면 모델이 뒤쪽의 제품 줄을 빠뜨린다 (재측정 L2에서 발견)
        holders = await call_tool(deps, "lookup", "find_products_by_cas", {"cas_numbers": [cas]}, errors) or []
        held = "; ".join(f"{h['product_id']} {h['product_name']} ({h['ingredient_name']} {h['wt_pct']:g} wt%, "
                         f"수출 {h['export_regions'].replace(';', ', ')})" for h in holders)
        context.append(f"- 물질 {name} (CAS {cas})")
        context.append("  이 물질을 함유한 회사 제품: " + (held or "없음"))
        if holders:
            holder_lines[name] = (held, [h["product_id"] for h in holders])
        context.append("  등재 규제:")
        for lst in found["listings"]:
            c = from_listing(base + len(citations) + 1, lst)
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
            c = from_finding(base + len(citations) + 1, f)
            citations.append(c.to_dict())
            context.append(f"  [{c.id}] {OUTCOME_KO[f['outcome']]} · {f['region']} {f['list_name']} · "
                           f"{f['substance']} {f['wt_pct']:g}% · {f['reason']}")
        for s in judged["skipped"][:5]:
            context.append(f"  (적용 제외) {s['substance']} · {s['reason']}")
        if not any(f["outcome"] != "below" for f in judged["findings"]):
            context.append(f"  → 다루는 지역({SUPPORTED_TEXT})의 등재 목록 기준 해당 항목 없음. "
                           "수출 허가·적합 판정이 아니므로 '수출 가능'이라고 쓰지 말 것")

    if unsupported:       # 규제 DB에 없는 국가 → "확인 불가" (판정 0건을 "수출 가능"으로 읽지 않게)
        context.insert(0, f"- {', '.join(unsupported)}: 이 서비스의 규제 DB에 없는 지역 — 규제 해당 여부를 확인할 수 "
                          f"없음 (다루는 지역: {SUPPORTED_TEXT}). 이 국가에 대해 '수출 가능'·'문제 없음'이라고 쓰지 말 것")
    if not cas_list and not product_ids and not unknown and not unsupported:
        context.append("질문에서 물질(이름·CAS)이나 제품 ID(P001 형식)를 찾지 못함. 사용자에게 물질 이름·CAS 또는 "
                       "제품 ID를 알려 달라고 요청할 것")
    answer, usage = await deps.llm.answer(question, context="\n".join(context),
                                          citations=citations_text(citations),
                                          history=history_text(state), on_token=token_writer())
    answer = drop_unknown_refs(normalize_refs(answer), {c["id"] for c in state.get("citations", []) + citations})
    # 8B 모델이 근거 목록만 옮겨 적고 함유 제품을 빠뜨리는 경우가 있어(재측정에서 발견) 코드가 보장한다
    missing = [f"- **{name} 함유 제품**: {held}" for name, (held, ids) in holder_lines.items()
               if not any(pid in answer for pid in ids)]
    if missing:
        answer = "\n".join(missing) + "\n\n" + answer
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
    # 요청 범위: 질문의 물질 + 질문의 제품에 든 성분. 범위가 있으면 수집·요약·영향 판정 모두 이 범위로 제한
    focus = set(cas_list)
    for pid in products:
        detail = await call_tool(deps, "gate", "get_product", {"product_id": pid}) or {}
        focus.update(i["cas"] for i in detail.get("ingredients", []))
    focus_cas = sorted(focus) if (cas_list or products) else []

    slots = state.get("slots") or {}
    regions = slots.get("change_regions") or plan.get("regions") or ["KR", "US"]
    asked, unsupported = regions_in(question)
    if slots.get("change_regions"):             # Step 9: 수집 가능한 지역만 (안내·불가는 이해 노드가 처리)
        asked, unsupported = regions, []
    if asked and set(asked) != set(regions):      # 질문에 지역이 명시돼 있으면 LLM 계획보다 질문을 따른다
        corrections.append(f"질문의 지역으로 바로잡음: {regions} → {asked}")
        regions = asked
    unsupported += [r for r in regions if r not in SUPPORTED and r not in unsupported]   # LLM 계획의 미지원 코드
    regions = [r for r in regions if r in SUPPORTED] or ["KR", "US"]
    if unsupported:
        gaps.append(f"{', '.join(unsupported)}: 이 서비스의 규제 DB에 없는 지역 — 규제 변경·해당 여부를 확인할 수 없음")
    tasks = []
    if "US" in regions:
        tasks.append({"agent": "us_feed", "days": plan.get("days", 7), "focus_cas": focus_cas,
                      "purpose": "미국 관보 TSCA 문서 수집" + (" (요청 범위 우선)" if focus_cas else "")})
    if "KR" in regions:
        names = {s["cas"]: s for s in deps.substances}
        tasks.append({"agent": "kr_feed", "days": max(plan.get("days", 7), KR_MIN_DAYS), "focus_cas": focus_cas,
                      "substances": [names[c] for c in focus_cas if c in names], "question": question,
                      "purpose": "국내 행정규칙(고시) 개정 수집" + (" (요청 범위 우선)" if focus_cas else "")})
    no_feed = [r for r in regions if r not in FEED_REGIONS | {"KR"}]
    if no_feed:
        gaps.append(f"{', '.join(no_feed)} 변경 문서 자동 수집은 아직 지원하지 않음 — 등재 목록 대조로만 확인")
    if products:                                # 언급 제품만 목록 대조 (변경 요청을 "전체 목록 대조"로 바꾸지 않는다)
        tasks.append({"agent": "regdb", "product_ids": products, "purpose": "제품 규제 판정"})
    plan.update(product_ids=products, cas=cas_list, regions=regions, focus_cas=focus_cas, unsupported=unsupported)
    get_stream_writer()({"type": "plan", "days": plan.get("days"), "regions": regions, "products": products,
                         "substances": cas_list, "tasks": [t["agent"] for t in tasks],
                         "corrections": corrections})
    return {"plan": plan, "corrections": corrections, "tasks": tasks, "gaps": gaps, "scope_note": ""}


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
    ran = {t["agent"]: t for t in state.get("tasks", [])}
    ran_feeds = ({"US"} if "us_feed" in ran else set()) | ({"KR"} if "kr_feed" in ran else set())
    if any(e["agent"] == "kr_feed" and e.get("kind") == "disabled" for e in state.get("errors", [])):
        ran_feeds.discard("KR")                     # 키가 없어 꺼진 수집은 "검색했지만 없음"이 아니다
    feeds = set(plan.get("feeds_ran") or []) | ran_feeds
    focus = plan.get("focus_cas") or []
    scoped = {d["region"] for d in state.get("documents", []) if d.get("in_scope", True)}
    what = "요청 범위 관련" if focus else "회사 관련"
    if "US" in ran_feeds and "US" not in scoped and rnd < 2 and plan.get("days", 7) < 30:
        tasks.append({"agent": "us_feed", "days": 30, "focus_cas": focus,
                      "purpose": f"{what} 문서가 없어 기간을 30일로 넓혀 재검색"})
        reasons.append(f"최근 {plan.get('days')}일에 {what} 미국 문서가 없어 30일로 확대")
        plan = {**plan, "days": 30}
    if "KR" in ran_feeds and "KR" not in scoped and rnd < 2:
        tasks.append({**ran["kr_feed"], "days": KR_WIDE_DAYS,
                      "purpose": f"{what} 국내 고시가 없어 기간을 1년으로 넓혀 재검색"})
        reasons.append(f"최근 {ran['kr_feed'].get('days')}일에 {what} 국내 고시가 없어 1년으로 확대")
        plan = {**plan, "kr_days": KR_WIDE_DAYS}
    plan = {**plan, "feeds_ran": sorted(feeds)}
    scope_note = ""
    if feeds and focus and not (scoped & feeds) and not tasks:
        basis = " · ".join(([f"미국 연방 관보 EPA TSCA 최근 {plan.get('days', 7)}일"] if "US" in feeds else [])
                           + ([f"국내 법제처 행정규칙 최근 {plan.get('kr_days', KR_MIN_DAYS)}일"] if "KR" in feeds else []))
        scope_note = (f"요청한 범위({_scope_names(plan, deps)})와 관련된 규제 변경 문서를 찾지 못했습니다 "
                      f"({basis} 검색 기준).")
    gaps = list(state.get("gaps", []))
    for e in state.get("errors", []):
        gaps.append(e["error"] if e.get("kind") in ("disabled", "degraded") else f"{e['agent']}의 {e['tool']} 조회 실패")
    gaps = list(dict.fromkeys(gaps))
    get_stream_writer()({"type": "review", "round": rnd, "sufficient": not tasks, "reasons": reasons,
                         "documents": len(state.get("documents", [])), "gaps": gaps})
    return {"research_round": rnd, "tasks": tasks, "plan": plan, "gaps": gaps, "scope_note": scope_note}


def _scope_names(plan: dict, deps: AgentDeps) -> str:
    names = {s["cas"]: s.get("name_ko") or s["cas"] for s in deps.substances}
    return ", ".join(plan.get("product_ids", []) + [names.get(c, c) for c in plan.get("cas", [])]) or "요청 물질"


def _unique_documents(state: AgentState, in_scope: bool) -> list[dict]:
    """재조사로 같은 문서가 두 번 들어올 수 있으므로 문서 번호로 중복 제거."""
    seen, out = set(), []
    for d in state.get("documents", []):
        if d["document_number"] in seen or d.get("in_scope", True) != in_scope:
            continue
        seen.add(d["document_number"])
        out.append(d)
    return out


def after_review(state: AgentState) -> list[Send] | str:
    return dispatch(state) if state.get("tasks") else "summarize"


# ── 7. 브리핑: 문서 요약 + 근거 문장 번역 + 무결성 검사 ──────────────────────
def _doc_meta(doc: dict) -> str:
    dates = " / ".join(f"{d['label']}: {d['date']}" for d in doc.get("official_dates", []))
    return f"{doc['title']}\n기관: {doc.get('agency')} / 종류: {doc.get('type')} / {dates}"


@node("summarize")
async def summarize_node(state: AgentState, deps: AgentDeps) -> dict:
    writer = get_stream_writer()
    documents = _unique_documents(state, in_scope=True)     # 범위 밖 문서는 요약·영향 분석 없이 참고 목록으로만
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
            ko = summary.quote_ko[i] if i < len(summary.quote_ko) and doc["region"] != "KR" else ""   # 국내는 원문이 한국어
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
        # 요약은 일부 날짜를 생략할 수 있다: 지어낸 사실은 오류, 빠진 날짜는 경고로만 알린다
        invented = {k: v for k, v in check.to_dict().items() if k.startswith("extra_") and v}
        if invented:                # 지어낸 사실이 있는 요약은 버린다 → 작성 단계는 근거 원문·번역만 쓴다
            item["summary_ko"] = "(요약에서 원문에 없는 사실이 감지되어 제외 — 아래 근거 원문을 따른다)"
            item["action_ko"] = "근거 원문 확인 필요"
        summaries.append(item)
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

    focus = set(plan.get("focus_cas") or [])
    only = set(plan.get("product_ids") or [])
    unresolved: dict[str, dict] = {}
    # ① 수집 문서에 언급된 물질이 들어간 제품 → 그 문서 지역의 판정만 (요청 범위가 있으면 그 물질·제품만)
    for s in state.get("summaries", []):
        cas = [m["cas"] for m in s["mentions"] if not focus or m["cas"] in focus]
        if not cas:
            continue
        hits = await call_tool(deps, "impact", "find_products_by_cas", {"cas_numbers": cas}) or []
        for pid in sorted({h["product_id"] for h in hits}):
            if only and pid not in only:
                continue
            if judgements.get(pid) is None:
                judgements[pid] = await call_tool(deps, "impact", "judge_product_compliance",
                                                  {"product_id": pid})
            if judgements[pid] is None:         # 판정 실패 ≠ 영향 없음 → "판정 확인 불가"로 남긴다
                name = next(h["product_name"] for h in hits if h["product_id"] == pid)
                unresolved.setdefault(pid, {"product_id": pid, "product_name": name, "export_regions": [],
                                            "document_number": s["document_number"], "findings": [],
                                            "unresolved": True})
                continue
            findings = [f for f in judgements[pid]["findings"]
                        if f["cas"] in cas and f["region"] == s["region"] and f["outcome"] != "below"]
            if findings:
                add_impact(pid, findings, s["document_number"])
    impacts.extend(unresolved.values())
    gaps = list(state.get("gaps", [])) + [f"{pid} 판정 확인 불가 (규제 판정 도구 오류) — 영향 여부 미확인"
                                          for pid in unresolved]
    judgements = {k: v for k, v in judgements.items() if v is not None}
    # ② 질문에 언급된 제품·물질 → 요청 지역의 판정
    for pid, j in state.get("judgements", {}).items():
        findings = [f for f in j["findings"] if f["region"] in plan["regions"] and f["outcome"] != "below"
                    and (not plan.get("cas") or f["cas"] in plan["cas"] or pid in plan.get("product_ids", []))]
        if findings and not any(i["product_id"] == pid and i["document_number"] is None for i in impacts):
            add_impact(pid, findings, None)
    get_stream_writer()({"type": "impact", "products": sorted({i["product_id"] for i in impacts}),
                         "findings": sum(len(i["findings"]) for i in impacts)})
    return {"impacts": impacts, "judgements": judgements, "citations": citations, "gaps": list(dict.fromkeys(gaps))}


# ── 9. 브리핑: 작성 (토큰 스트리밍) ──────────────────────────────────────────
def _summaries_text(state: AgentState) -> str:
    """LLM에 주는 문서 요약 — 범위 안 문서만. 범위 안내·범위 밖 참고 목록은 코드가 넣는다 (_add_scope)."""
    lines = []
    for s in state.get("summaries", []):
        dates = ", ".join(f"{d['label']} {d['date']}" for d in s["official_dates"])
        lines.append(f"- [{s['region']}] {s['title_ko']} ({dates})\n  요약: {s['summary_ko']}\n"
                     f"  할 일: {s['action_ko']}\n  근거: {', '.join(f'[{i}]' for i in s['citation_ids'])}")
    return "\n".join(lines) or "(요청 범위와 관련된 규제 변경 문서 없음)"


def _add_scope(draft: str, state: AgentState) -> str:
    """범위 안내(요약 첫 문장)와 범위 밖 참고 목록(규제 변경 끝)을 코드가 넣는다.
    LLM에 옮겨 쓰게 했더니 실모델이 안내 문구를 범위 안 문서에 붙이고, 핵심 변경을 "범위 밖"으로 표시했다."""
    if state.get("scope_note"):
        line = f"**요청 범위 확인 결과**: {state['scope_note']}\n\n"
        draft = draft.replace("## 요약\n", "## 요약\n" + line, 1) if "## 요약\n" in draft else line + draft
    others = _unique_documents(state, in_scope=False)
    if others:
        label = ("참고: 요청 범위 밖의 변경" if (state.get("plan") or {}).get("focus_cas")
                 else "참고: 회사 제품 성분과 관련 없는 변경")
        block = (f"\n**{label}** (영향 분석 제외)\n"
                 + "\n".join(f"- {d['title']} ({d.get('ref_label') or '관보 ' + d['document_number']}, "
                             f"{'발령' if d.get('region') == 'KR' else '게시'} {d.get('publication_date')})"
                             + (f" — {d['note']}" if d.get("note") else "") for d in others) + "\n\n")
        marker = "## 우리 제품 영향"
        draft = draft.replace(marker, block + marker, 1) if marker in draft else draft + "\n" + block
    return draft


def _doc_label(state: AgentState, number: str) -> str:
    """문서 표기: 미국은 '관보 2026-20964', 국내는 '화학물질안전원고시 제2026-2호'."""
    doc = next((d for d in state.get("documents", []) if d["document_number"] == number), {})
    return doc.get("ref_label") or f"관보 {number}"


def _impacts_text(state: AgentState) -> str:
    lines = []
    for i in state.get("impacts", []):
        src = _doc_label(state, i["document_number"]) if i["document_number"] else "질문 언급 제품"
        if i.get("unresolved"):
            lines.append(f"- {i['product_id']} {i['product_name']} ({src}): 판정 확인 불가 (도구 오류) — 영향 여부 미확인")
            continue
        lines.append(f"- {i['product_id']} {i['product_name']} (수출 {', '.join(i['export_regions'])}, {src})")
        for f in i["findings"]:
            lines.append(f"  [{f['citation_id']}] {OUTCOME_KO[f['outcome']]} · {f['region']} {f['list_name']} · "
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
    return {"draft": _add_scope(normalize_refs(strip_code_fence(draft)), state), "writing_attempts": attempt,
            "usage": [usage]}


def drop_unknown_refs(text: str, valid_ids: set[int]) -> str:
    """근거 목록에 없는 번호 [n]을 지운다 (근거가 없는 답변에 모델이 [1]을 붙이던 문제)."""
    return re.sub(r"\s?\[(\d+)\]", lambda m: m.group(0) if int(m.group(1)) in valid_ids else "", text)


def normalize_refs(text: str) -> str:
    """모델이 '[근거 1]', '[근거 1, 2]'처럼 쓰면 '[1]', '[1][2]'로 — 화면 링크·가드·채점이 같은 형식을 쓴다."""
    return re.sub(r"\[근거\s*([\d,\s]+)\]",
                  lambda m: "".join(f"[{n}]" for n in re.findall(r"\d+", m.group(1))), text)


def strip_code_fence(text: str) -> str:
    """모델이 답 전체를 ```markdown ... ``` 으로 감싸면 화면에 Markdown이 그대로 보인다 → 벗긴다."""
    m = re.fullmatch(r"\s*```[a-zA-Z]*\n(.*?)\n?```\s*", text, flags=re.DOTALL)
    return m.group(1) if m else text


# ── 10. 브리핑: 사실·근거 검사 (코드) ────────────────────────────────────────
@node("guard")
async def guard_node(state: AgentState, deps: AgentDeps) -> dict:
    draft = state["draft"]
    citations = state.get("citations", [])
    # 사실의 기준 = 원문 근거(+무결성 통과 번역) · 코드 판정 · 공식 메타데이터. LLM 요약은 기준에서 뺀다
    # (요약이 지어낸 사실을 브리핑이 옮겨 써도 "요약에 있으니 통과"되던 문제)
    source = " ".join([c["quote"] for c in citations] + [c.get("translation_ko", "") for c in citations]
                      + [_impacts_text(state)])
    # 관보 번호·게시일도 공식 메타데이터 — 범위 밖 참고 목록에 코드가 넣은 번호를 "지어낸 숫자"로 잡던 문제 (재측정 B5)
    reference = (" ".join(f"{_doc_meta(d)} {d.get('document_number', '')} {d.get('publication_date', '')}"
                          for d in state.get("documents", []))
                 + f" {date.today().isoformat()} " + state.get("scope_note", ""))
    # 근거 번호 [n]은 숫자 사실이 아니다 — "없는 번호" 검사는 아래에서 따로 한다
    # ("[1], [2], … [6]"처럼 나열하면 4·5를 지어낸 숫자로 잡아 재작성을 반복했다)
    report = integrity.check(source, re.sub(r"\[\d+\]", " ", draft), reference=reference)
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
        return "finalize"
    if state.get("writing_attempts", 0) >= max_writing or state.get("validation_attempts", 0) >= max_validation:
        return "finalize"                                  # 상한 도달 → 미달 사실을 알리고 진행
    return "write"


# ── Step 9. 안내: 규제 설명 · 목록 조회 · 앞 답변 근거 (이해 노드가 정한 일만) ────────────
def _list_section(ov: dict, cid: int, holders: list[dict]) -> str:
    """목록 조회는 코드가 쓴다 — 등재 수·확인일·최근 추가·함유 제품 (LLM이 숫자를 바꿀 여지가 없게)."""
    lines = [f"## {ov['region']} {ov['list_name']} — 등재 현황 (규제 DB 확인일 {ov.get('verified_on') or '-'})",
             f"- 등재 {ov['listing_count']:,}행 · 물질 {ov['substance_count']:,}종 [{cid}]"]
    for r in ov.get("recent_additions", []):
        shown = list(dict.fromkeys(x["name"][:60] for x in r["substances"]))[:4]   # 염류처럼 이름이 비슷하면 한 번만
        names = ", ".join(shown)
        more = f" 외 {r['count'] - len(shown)}종" if r["count"] > len(shown) else ""
        lines.append(f"- {r['date']} 추가: {names}{more} [{cid}]")
    if not ov.get("recent_additions"):
        lines.append("- 이 목록은 원본에 등재일 정보가 없어 최근 추가 물질을 알 수 없습니다")
    elif holders:
        lines.append("- 최근 추가 물질을 함유한 회사 제품: " + "; ".join(
            f"{h['product_id']} {h['product_name']} ({h['ingredient_name']} {h['wt_pct']:g} wt%)" for h in holders))
    else:
        lines.append("- 최근 추가 물질을 함유한 회사 제품: 없음")
    return "\n".join(lines)


@node("inform")
async def inform_node(state: AgentState, deps: AgentDeps) -> dict:
    todo = state.get("inform") or {}
    if not todo:
        return {}
    errors: list[dict] = []
    citations = [dict(c) for c in todo.get("prev_citations", [])]          # 앞 답변 근거는 번호 그대로
    sections, usage = [], []
    if citations:
        sections.append("## 앞 답변의 근거\n" + "\n".join(
            f"- [{c['id']}] {c['title']} — {c['quote'][:200]}" for c in citations))
    reg_ids = list(dict.fromkeys(todo.get("explain", []) + todo.get("list", [])))
    overviews, cite_of = {}, {}
    for reg_id in reg_ids:
        ov = await call_tool(deps, "inform", "regulation_overview", {"reg_id": reg_id}, errors)
        if ov:
            c = from_regulation(len(citations) + 1, ov)
            citations.append(c.to_dict())
            overviews[reg_id], cite_of[reg_id] = ov, c.id
    for reg_id in todo.get("list", []):
        if reg_id not in overviews:
            continue
        recent = [x["cas"] for r in overviews[reg_id].get("recent_additions", []) for x in r["substances"]]
        holders = await call_tool(deps, "inform", "find_products_by_cas", {"cas_numbers": recent}, errors) or [] \
            if recent else []
        sections.append(_list_section(overviews[reg_id], cite_of[reg_id], holders))
    explain = [r for r in todo.get("explain", []) if r in overviews]
    if explain or todo.get("glossary"):
        context = ["규제 설명 요청 — 아래 카탈로그·용어집에 있는 의무·적용 범위만 쓴다. 없는 의무(등록 톤수 등)는 쓰지 않는다. "
                   "질문에 '최근 변경'이 있어도 설명에서는 변경을 쓰지 않는다 (변경·등재 현황은 다른 절에서 코드가 답한다)."]
        for reg_id in explain:
            ov = overviews[reg_id]
            context.append(f"[{cite_of[reg_id]}] {ov['region']} {ov['law']} {ov['list_name']}: 의무 {ov.get('obligation_ko')} "
                           f"/ 적용 {ov.get('applies_when')} / 기본 기준 {ov.get('default_threshold_wt_pct') or '물질별'} wt% "
                           f"/ {ov.get('listing_note') or ''} / 등재 {ov['substance_count']:,}종")
        context += [f"- 용어 {g['term']}({g['ko']}): {g.get('definition_ko') or ''}" for g in todo.get("glossary", [])]
        answer, u = await deps.llm.answer(state["question"], context="\n".join(context),
                                          citations=citations_text(citations), history="", on_token=token_writer())
        usage.append(u)
        answer = drop_unknown_refs(normalize_refs(answer), {c["id"] for c in citations})
        sections.insert(0, "## 규제 설명\n" + answer)
    return {"sections": sections, "citations": citations, "errors": errors, "usage": usage}


# ── 마지막. 최종 정리 ────────────────────────────────────────────────────────
@node("finalize")
async def finalize_node(state: AgentState, deps: AgentDeps) -> dict:
    main = state.get("final") or state.get("draft") or ""
    judgement = state.get("judgement") or {}
    if state.get("draft") and judgement and not judgement.get("passed", True):
        main += ("\n\n---\n> ⚠️ 브리핑이 품질 기준을 완전히 충족하지 못했습니다 "
                 f"(검토 의견: {state.get('validation_feedback')}). 근거 원문을 직접 확인해 주세요.")
    # Step 9 합성: 범위 밖·확인 불가 안내(코드) → 설명·목록 절 → 본 답변
    parts = list(state.get("notices", [])) + list(state.get("sections", [])) + ([main] if main else [])
    final = "\n\n".join(parts) or "죄송합니다. 요청을 처리하지 못했습니다."
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
    return {"chat": "chat_answer", "lookup": "lookup", "briefing": "plan", "inform": "finalize"}.get(
        state["route"], "chat_answer")


def build_graph(deps: AgentDeps, checkpointer=None):
    g = StateGraph(AgentState)
    bind = lambda fn: partial(fn, deps=deps)   # noqa: E731 — 명시적 의존성 주입
    g.add_node("understand", bind(understand_node))
    g.add_node("inform", bind(inform_node))
    g.add_node("chat_answer", bind(chat_answer_node))
    g.add_node("lookup", bind(lookup_node))
    for name, fn in [("plan", plan_node), ("gate", gate_node), ("research", run_subagent),
                     ("review", review_node), ("summarize", summarize_node), ("impact", impact_node),
                     ("write", write_node), ("guard", guard_node), ("validate", validate_node)]:
        g.add_node(name, bind(fn))
    g.add_node("finalize", bind(finalize_node))

    g.add_edge(START, "understand")
    g.add_edge("understand", "inform")                      # 설명·목록·앞 근거 (할 일이 없으면 그냥 통과)
    g.add_conditional_edges("inform", after_route, ["chat_answer", "lookup", "plan", "finalize"])
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
    g.add_conditional_edges("validate", partial(after_validate, max_writing=2, max_validation=3),
                            ["write", "finalize"])
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
