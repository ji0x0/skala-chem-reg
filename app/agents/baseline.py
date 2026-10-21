"""Before(baseline) 그래프 — "LLM 단독" 방식. 개선 효과를 같은 입력으로 비교하기 위해 남겨 둔다.

v2와 같은 문서를 수집하지만 그 다음을 전부 LLM에게 맡긴다.
- 근거 문장 추출 없음: 문서 원문 앞부분을 통째로 넣는다
- 코드 판정 없음: 제품 배합 표를 주고 영향 여부를 LLM이 판단한다
- 무결성 검사·가드·검토·근거 번호 없음

질문 분류는 Step 3b의 route 노드를 그대로 쓰고(v2는 Step 9부터 understand), briefing만 이 경로로 처리한다 (chat·lookup은 v2와 동일하게 비교하지 않는다).
"""
from __future__ import annotations

from functools import partial

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from .deps import AgentDeps
from .graph import finalize_node, node, route_node, token_writer
from .state import AgentState
from .tooling import call_tool

DOC_CHARS = 6000          # 문서당 원문 앞부분 (LLM 입력 상한을 고려한 단순 자르기)


@node("collect")
async def collect_node(state: AgentState, deps: AgentDeps) -> dict:
    """v2와 같은 관보 검색 + 본문. 순차 실행, 관련 문서 선별 없음."""
    found = await call_tool(deps, "baseline", "search_federal_register", {"days": 7, "limit": 15}) or {}
    documents = []
    for d in found.get("documents", [])[:3]:
        full = await call_tool(deps, "baseline", "get_federal_register_document",
                               {"document_number": d["document_number"], "max_chars": DOC_CHARS})
        if full:
            documents.append({"document_number": full["document_number"], "title": full["title"],
                              "publication_date": full["publication_date"], "html_url": full.get("html_url"),
                              "text": full["text"]})
    get_stream_writer()({"type": "plan", "documents": len(documents), "mode": "baseline"})
    return {"documents": documents}


@node("llm_only")
async def llm_only_node(state: AgentState, deps: AgentDeps) -> dict:
    docs = "\n\n".join(f"### {d['title']} ({d['publication_date']})\n{d['text']}" for d in state.get("documents", []))
    products = []
    for p in await call_tool(deps, "baseline", "list_products", {}) or []:
        detail = await call_tool(deps, "baseline", "get_product", {"product_id": p["product_id"]})
        if detail:
            rows = ", ".join(f"{i['ingredient_name']}({i['cas']}) {i['wt_pct']}%" for i in detail["ingredients"])
            products.append(f"- {detail['product_id']} {detail['product_name']} [{detail['product_form']}, "
                            f"수출 {', '.join(detail['export_regions'])}]: {rows}")
    draft, usage = await deps.llm.baseline_briefing(state["question"], docs or "(문서 없음)",
                                                    "\n".join(products), on_token=token_writer())
    return {"draft": draft, "final": draft, "usage": [usage]}


def build_baseline_graph(deps: AgentDeps, checkpointer=None):
    g = StateGraph(AgentState)
    bind = lambda fn: partial(fn, deps=deps)   # noqa: E731
    g.add_node("route", bind(route_node))
    g.add_node("collect", bind(collect_node))
    g.add_node("llm_only", bind(llm_only_node))
    g.add_node("finalize", bind(finalize_node))
    g.add_edge(START, "route")
    g.add_edge("route", "collect")
    g.add_edge("collect", "llm_only")
    g.add_edge("llm_only", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
