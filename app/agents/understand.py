"""Step 9 — 질문 이해와 범위 판정 (설계: docs/routing-architecture.md).

질문 하나를 한 번만 이해하고, 실행하기 전에 "무엇을 할 수 있고 무엇을 할 수 없는지"를 코드가 정한다.
  ① 코드 추출: 지역·제도·물질·제품·연도·범위 밖 표현 (결정적, LLM보다 우선)
  ② 의도 분해: LLM 구조화 출력(최대 3개) → 형식 오류면 코드 규칙 → 코드가 보정
  ③ 후속 질문: 대상이 없으면 앞 턴의 대상·의도·근거를 이어받는다
  ④ 범위 판정: 범위 밖·확인 불가는 실행하지 않고 코드 문구로 답한다 (다른 질문으로 대신 답하지 않는다)
"""
from __future__ import annotations

import re
from datetime import date

from langgraph.config import get_stream_writer

from app.domain.cas import is_valid_cas
from app.domain.coverage import (CHANGE_WORDS, DOMAIN_WORDS, FEED_REGIONS, GENERAL_KNOWLEDGE, LEGAL_ADVICE, SECURITY,
                                 SUPPORTED, regimes_in, regions_in, unsupported_notice, years_in)
from app.domain import responses
from app.llm.fake import FakeLLM

from .common import history_text, node, resolve_substances
from .deps import AgentDeps
from .state import RESET, AgentState, per_turn_reset
from .tooling import call_tool

FALLBACK = FakeLLM()
INTENT_KO = {"service_help": "서비스 안내", "explain_regulation": "규제 설명", "list_query": "목록 조회",
             "substance_lookup": "물질 조회", "product_check": "제품 확인", "change_briefing": "변경 브리핑",
             "followup": "후속 질문", "out_of_scope": "범위 밖"}
REG_REGION = {"EU_REACH_SVHC": "EU", "EU_REACH_XVII": "EU", "EU_CLP_ANNEX_VI": "EU", "US_TSCA_S6": "US",
              "CN_PRIORITY": "CN", "JP_CSCL_C1": "JP"}          # 그 밖(KR_*)은 국내
EVIDENCE_WORDS = r"근거|출처|원문"
COVERED_LISTS = "국내 화관법 유해화학물질·제한물질·금지물질, 산안법 관리대상·특별관리물질, 미국 TSCA 제6조, " \
                "EU REACH SVHC·부속서 XVII·CLP 부속서 VI, 중국 우선관리, 일본 화심법 제1종"
VERIFIED_ON = "2026-10-20"                                    # 규제 목록 확인일 (docs/regulation-verification.md)


def _region_of(reg_id: str) -> str:
    return REG_REGION.get(reg_id, "KR")


async def _intents(question: str, state: AgentState, deps: AgentDeps):
    plan, usage = await deps.llm.understand(question, history_text(state))
    how = "LLM"
    if plan is None:                                         # 형식 오류 → 코드 규칙
        plan, _ = await FALLBACK.understand(question, "")
        how = "코드 규칙 (LLM 형식 오류)"
    return [i.type for i in plan.intents], [i.topic for i in plan.intents], usage, how


@node("understand")
async def understand_node(state: AgentState, deps: AgentDeps) -> dict:
    question = state["question"]
    prev = state.get("last_targets") or {}

    # ① 코드 추출
    regions, unsupported = regions_in(question)
    regs, out_regs = regimes_in(question)
    cas_list = resolve_substances(question, deps)[:5]
    asked = list(dict.fromkeys(re.findall(r"P\d{3}", question.upper())))
    products = [p for p in asked if p in deps.product_ids]
    unknown_products = [p for p in asked if p not in deps.product_ids]
    invalid_cas = [c for c in re.findall(r"(?<![\d-])\d{2,7}-\d{2}-\d(?![\d-])", question) if not is_valid_cas(c)]
    years = years_in(question)

    # ② 의도 분해 + 코드 보정
    types, topics, usage, how = await _intents(question, state, deps)
    if state.get("period"):                                  # Step 10 정기 브리핑: 기간이 정해진 국내외 변경 브리핑
        types, how = ["change_briefing"], "정기 브리핑"
        regions = sorted(FEED_REGIONS)                       # 변경을 수집할 수 있는 모든 지역 (국내·미국)
    asked_types = list(dict.fromkeys(types))                 # 사용자가 요청한 것 (진행 표시용 — 처리 못 해도 그대로 보인다)
    glossary = await call_tool(deps, "understand", "glossary_lookup", {"text": question}) or []
    if "explain_regulation" in types and not (regs or out_regs or glossary):
        types.remove("explain_regulation")                   # 설명할 규제·용어가 질문에 없다 (예: "그 근거는 무엇인가요")
    if products and not set(types) & {"product_check", "change_briefing", "followup"}:
        types.append("product_check")
    if cas_list and not set(types) & {"substance_lookup", "product_check", "change_briefing", "explain_regulation",
                                      "list_query", "followup"}:
        types.append("substance_lookup")

    # ③ 후속 질문: 대상이 없으면 앞 턴을 이어받는다
    inform: dict = {}
    inherited = False                                                 # 앞 턴 의도를 그대로 이어받았나 ("더 자세히")
    if "followup" in types:
        types.remove("followup")
        if re.search(EVIDENCE_WORDS, question) and not (products or cas_list or regs):
            inform["prev_citations"] = state.get("citations", [])      # 앞 답변의 근거를 다시 보여 준다
        elif products or cas_list:                                    # "그럼 P004는?" → 새 대상을 조회 (지역은 앞 턴)
            types.append("product_check" if products else "substance_lookup")
            regions = regions or prev.get("regions", [])
        elif prev:                                                    # "더 자세히" → 앞 턴 대상·의도 그대로
            products, cas_list = prev.get("products", []), prev.get("cas", [])
            regions, regs = regions or prev.get("regions", []), regs or prev.get("regs", [])
            types += [t for t in prev.get("intents", []) if t != "followup"]
            inherited = True
    if ("change_briefing" in types and not state.get("period") and not inherited
            and not re.search(CHANGE_WORDS, question, re.IGNORECASE)):
        types.remove("change_briefing")                               # 변경을 묻지 않았다 (재평가 L3에서 발견)
        if products and "product_check" not in types:
            types.append("product_check")
        elif cas_list and not set(types) & {"substance_lookup", "explain_regulation", "list_query"}:
            types.append("substance_lookup")
    types = list(dict.fromkeys(types))[:3]

    # ④ 범위 판정
    notices: list[str] = []
    if re.search(SECURITY, question):                                 # O9 — 실행하지 않고 끝
        notices.append(responses.security())
        return _result(question, "inform", asked_types, how, usage, notices, {}, {}, prev)
    if unsupported:
        notices.append(unsupported_notice(unsupported))               # O1
    if out_regs:
        notices.append(responses.unsupported_regimes(out_regs, COVERED_LISTS))   # O2
    if re.search(GENERAL_KNOWLEDGE, question):
        notices.append(responses.general_knowledge())                 # O5
    if re.search(LEGAL_ADVICE, question):
        notices.append(responses.legal_advice())                      # O6
    if invalid_cas:
        notices.append(f"> ⚠️ **{', '.join(invalid_cas)}**는 CAS 번호의 체크 디지트가 맞지 않습니다 (유효하지 않은 번호).")

    change_regions: list[str] = []
    if "change_briefing" in types:
        stale = [y for y in years if y < date.today().year - 1]
        if stale:                                                     # O3 — 수집하지 않는 기간
            notices.append(responses.out_of_window(stale, VERIFIED_ON))
            types.remove("change_briefing")
        else:
            # 다루지 않는 국가만 물었으면 기본 지역(국내·미국)으로 채우지 않는다 — 다른 질문에 대신 답하지 않기
            wanted = regions or sorted({_region_of(r) for r in regs}) or ([] if unsupported else ["KR", "US"])
            change_regions = [r for r in wanted if r in FEED_REGIONS]
            no_feed = [r for r in wanted if r not in FEED_REGIONS and r in SUPPORTED]
            if no_feed:                                               # O4 — 수집기 없는 지역: 다른 지역 문서로 채우지 않는다
                notices.append(responses.no_feed(no_feed, VERIFIED_ON))
                inform.setdefault("list", []).extend(r for r in (regs or []) if _region_of(r) in no_feed)
                if not inform.get("list"):                            # 제도 언급이 없으면 그 지역의 대표 목록
                    inform["list"] = [r for r, region in REG_REGION.items() if region in no_feed][:2]
            if not change_regions:
                types.remove("change_briefing")
            if "EU" in change_regions and "EU_REACH_SVHC" in regs:   # SVHC 추가는 법령이 아니라 수집에 안 보인다 → DB 기준
                inform.setdefault("list", []).append("EU_REACH_SVHC")

    if "explain_regulation" in types:
        inform["explain"] = regs[:4]
        inform["glossary"] = glossary[:6]
    if "list_query" in types:
        inform.setdefault("list", []).extend(regs[:3])
    if inform.get("list"):
        inform["list"] = list(dict.fromkeys(inform["list"]))

    lookup = bool(products or cas_list or unknown_products) and \
        bool(set(types) & {"product_check", "substance_lookup"})
    route = ("briefing" if "change_briefing" in types else "lookup" if lookup
             else "inform" if (inform or notices) and "service_help" not in types else "chat")

    # 되묻기 (O10): 규제 질문인데 대상이 없고, 할 일도 없을 때
    if route == "chat" and "service_help" not in types:
        if re.search(DOMAIN_WORDS, question) and not (products or cas_list or regs or notices):
            notices.append(responses.clarify(["제품", "물질", "지역"]))
        elif not notices:
            notices.append(responses.off_topic())                     # O8
        route = "inform"

    slots = {"regions": regions, "unsupported": unsupported, "regs": regs, "out_regs": out_regs,
             "cas": cas_list, "products": products, "unknown_products": unknown_products,
             "change_regions": change_regions, "years": years}
    return _result(question, route, asked_types, how, usage, notices, slots, inform, prev, done=types)


def _result(question, route, types, how, usage, notices, slots, inform, prev, done=()):
    """types: 사용자가 요청한 의도(표시·평가용), done: 실제로 실행하는 의도 (범위 밖·확인 불가는 빠짐)."""
    reasoning = " · ".join(INTENT_KO.get(t, t) for t in types) + f" ({how})"
    get_stream_writer()({"type": "route", "route": route, "reasoning": reasoning, "intents": types,
                         "notices": len(notices)})
    # 다음 턴의 후속 질문이 이어받을 대상 (대상이 없는 턴이면 앞 턴 것을 유지)
    has_target = slots and any(slots.get(k) for k in ("products", "cas", "regs"))
    targets = ({k: slots.get(k, []) for k in ("products", "cas", "regions", "regs")} | {"intents": list(done)}
               if has_target else prev)
    return {**per_turn_reset(question), "route": route, "route_reasoning": reasoning, "intents": types,
            "slots": slots, "notices": notices, "inform": inform, "last_targets": targets,
            "usage": [RESET, usage]}
