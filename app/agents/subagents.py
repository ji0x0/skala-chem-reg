"""병렬 조사 에이전트 3개 — Supervisor가 Send로 동시에 실행한다.

- us_feed  (해외 수집): 미국 관보 검색 → 문서별 본문 → 우리 규제 DB 물질이 언급된 문서만 → 근거 문장 추출
- kr_feed  (국내 수집): 법제처 행정규칙 검색 (LAW_API_OC 없으면 비활성 → "확인하지 못한 항목")
- regdb    (규제 DB 대조): 지정된 제품을 코드 규칙으로 판정

각 에이전트는 실패해도 예외를 밖으로 던지지 않는다 (call_tool이 errors에 기록). 한 에이전트가
실패해도 나머지 결과는 그대로 남는다 (task 단위 에러 격리).
"""
from __future__ import annotations

import asyncio

from langgraph.config import get_stream_writer

from app.domain.citations import extract_quotes, official_dates
from app.domain.mentions import ABBREVIATIONS, name_variants

from .deps import AgentDeps
from .tooling import call_tool

AGENT_LABELS = {"us_feed": "해외 수집 에이전트 (미국 관보)",
                "kr_feed": "국내 수집 에이전트 (법제처 행정규칙)",
                "regdb": "규제 DB 대조 에이전트"}


async def _us_feed(task: dict, deps: AgentDeps, errors: list[dict]) -> dict:
    agent = "us_feed"
    found = await call_tool(deps, agent, "search_federal_register",
                            {"days": task["days"], "limit": task.get("limit", 15)}, errors)
    candidates = (found or {}).get("documents", [])[: task.get("max_docs", 8)]
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
        mentions = full["substance_mentions"][:6]
        terms = [t for m in mentions for t in name_variants(m["name_en"]) + ABBREVIATIONS.get(m["cas"], [])]
        documents.append({
            "region": "US", "agency": "EPA", "source": full["source"], "text_source": full["text_source"],
            **{k: full.get(k) for k in ("document_number", "title", "type", "publication_date",
                                        "comments_close_on", "effective_on", "html_url")},
            "mentions": mentions, "quotes": extract_quotes(full["text"], terms),
            "official_dates": official_dates(full),
        })
    return {"documents": documents,
            "summary": f"문서 {len(candidates)}건 중 회사 관련 물질 언급 {len(documents)}건"}


async def _kr_feed(task: dict, deps: AgentDeps, errors: list[dict]) -> dict:
    result = await call_tool(deps, "kr_feed", "search_kr_admin_rules",
                             {"query": task.get("query", "유해화학물질")}, errors)
    if result and result.get("source") == "disabled":
        errors.append({"agent": "kr_feed", "tool": "search_kr_admin_rules", "kind": "disabled",
                       "error": "국내 실시간 조회 비활성 (법제처 Open API 키 LAW_API_OC 미설정)"})
        return {"summary": "비활성 — 키 미설정"}
    # 키 발급 후 실제 응답 형식을 확인해 문서로 바꾼다 (Day2). 지금은 건수만 기록
    return {"summary": "조회 완료 (응답 형식 확인 전 — 문서 변환 미지원)"}


async def _regdb(task: dict, deps: AgentDeps, errors: list[dict]) -> dict:
    judgements = {}
    for pid in task["product_ids"]:
        judged = await call_tool(deps, "regdb", "judge_product_compliance", {"product_id": pid}, errors)
        if judged:
            judgements[pid] = judged
    return {"judgements": judgements, "summary": f"제품 {len(judgements)}개 판정"}


RUNNERS = {"us_feed": _us_feed, "kr_feed": _kr_feed, "regdb": _regdb}


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
    return update
