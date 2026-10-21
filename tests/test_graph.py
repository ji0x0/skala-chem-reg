"""Step 3b — 그래프 경로별 실행 (FakeLLM + InMemoryToolProvider, 네트워크 없음).

관보는 오프라인으로 막아 스냅샷(제목·요약)을 쓰게 하고, 본문 캐시도 비운다 → 매번 같은 결과.
"""
import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.baseline import build_baseline_graph
from app.agents.deps import AgentDeps
from app.agents.graph import build_graph
from app.core.config import Settings
from app.llm.fake import FakeLLM
from app.tools.provider import InMemoryToolProvider
from mcp_servers import reg_feed_server

BRIEFING = "이번 주 미국 EPA랑 국내 규제 변경 브리핑해줘"


@pytest.fixture(autouse=True)
def offline_feed(monkeypatch, tmp_path):
    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(reg_feed_server.httpx, "get", offline)
    monkeypatch.setattr(reg_feed_server, "CACHE_DIR", tmp_path)


async def make_graph(llm=None, fail_tools=None, builder=build_graph):
    tools = InMemoryToolProvider(fail_tools=fail_tools)
    await tools.start()
    deps = AgentDeps(Settings(_env_file=None), llm or FakeLLM(), tools)
    await deps.load_catalog()
    return builder(deps, InMemorySaver()), tools


async def run(graph, question, thread="t"):
    cfg = {"configurable": {"thread_id": thread}}
    kinds = []
    async for mode, payload in graph.astream({"question": question}, cfg, stream_mode=["custom", "updates"]):
        if mode == "custom":
            kinds.append(payload["type"])
    return cfg, kinds, await graph.aget_state(cfg)


async def test_chat_path():
    graph, tools = await make_graph()
    _, kinds, snap = await run(graph, "안녕?")
    assert snap.values["route"] == "chat" and "token" in kinds
    assert "규제 브리핑" in snap.values["final"]
    await tools.stop()


async def test_lookup_path_cites_listings_and_judgements():
    graph, tools = await make_graph()
    _, kinds, snap = await run(graph, "트리클로로에틸렌이랑 P002 규제 문제 있어?")
    v = snap.values
    assert v["route"] == "lookup" and "P002" in v["judgements"]
    assert len(v["citations"]) >= 8 and all(c["kind"] == "listing" for c in v["citations"])
    assert "tool_call_end" in kinds
    await tools.stop()


async def test_lookup_lists_products_containing_substance_and_unknown_product():
    """Step 6 평가에서 발견: 물질 질문에 함유 제품이 빠짐 / 없는 제품을 '못 찾음'으로 뭉갬."""
    graph, tools = await make_graph()
    _, _, snap = await run(graph, "트리클로로에틸렌이 들어간 제품과 해당 규제 알려줘", thread="h1")
    assert "P003" in snap.values["final"] and "함유한 회사 제품" in snap.values["final"]
    _, _, snap = await run(graph, "P099 규제 문제 있어?", thread="h2")
    assert "P099: 등록되지 않은 제품" in snap.values["final"] and not snap.values["citations"]
    await tools.stop()


async def test_briefing_runs_parallel_agents_and_waits_for_approval():
    graph, tools = await make_graph()
    cfg, kinds, snap = await run(graph, BRIEFING)
    v = snap.values
    assert snap.next == ("approval",)                                  # 영향 제품 공유 승인 대기
    assert kinds.count("agent_start") == 2                             # us_feed ∥ kr_feed
    assert any("법제처" in g for g in v["gaps"])                        # 국내 비활성은 확인하지 못한 항목
    assert [i["product_id"] for i in v["impacts"]] == ["P003"]          # TCE 문서 → TCE 함유 제품
    kinds_of_cites = {c["kind"] for c in v["citations"]}
    assert kinds_of_cites == {"document", "listing"}                    # 원문 근거 + 등재 근거
    assert all(c["translation_ko"] for c in v["citations"] if c["kind"] == "document")

    async for _ in graph.astream(Command(resume={"approved": False, "comment": "추가 검토"}), cfg,
                                 stream_mode="updates"):
        pass
    final = (await graph.aget_state(cfg)).values["final"]
    assert "반려" in final and "추가 검토" in final
    await tools.stop()


async def test_tool_failure_is_isolated():
    graph, tools = await make_graph(fail_tools={"search_federal_register"})
    cfg, _, snap = await run(graph, BRIEFING)
    v = snap.values
    assert any("us_feed의 search_federal_register 조회 실패" in g for g in v["gaps"])
    assert v["documents"] == [] and v["draft"]                          # 실패해도 브리핑은 완성
    await tools.stop()


class ListOnlyLLM(FakeLLM):
    """근거 목록만 옮겨 적고 함유 제품을 빠뜨리는 LLM (재측정에서 qwen3:8b가 보인 답)."""

    async def answer(self, question, context, citations, history, on_token=None):
        _, usage = await super().answer(question, context, citations, history)
        return "[근거 1] EU 고위험 우려물질(SVHC) 후보 목록", usage


async def test_lookup_answer_always_names_holder_products():
    graph, tools = await make_graph(llm=ListOnlyLLM())
    _, _, snap = await run(graph, "트리클로로에틸렌 해당 규제 알려줘")
    final = snap.values["final"]
    assert final.startswith("- **") and "P003" in final and "[1] EU" in final
    await tools.stop()


class InventingLLM(FakeLLM):
    """브리핑에 원문에 없는 날짜를 지어 넣는 LLM."""

    async def write_briefing(self, question, summaries, judgements, citations, feedback, on_token=None):
        text, usage = await super().write_briefing(question, summaries, judgements, citations, feedback, on_token)
        return text + "\n- 신규 금지 시행일 2028-01-01 [1]", usage


async def test_guard_catches_invented_fact_and_retries_with_limit():
    graph, tools = await make_graph(llm=InventingLLM())
    cfg, kinds, snap = await run(graph, BRIEFING)
    if snap.next:                                                       # 승인 대기면 승인하고 끝까지
        async for _ in graph.astream(Command(resume={"approved": True}), cfg, stream_mode="updates"):
            pass
    v = (await graph.aget_state(cfg)).values
    assert v["guard"]["invented"]["extra_dates"] == ["2028-01-01"]
    assert v["writing_attempts"] == 2                                  # 재작성 1회 후 상한
    assert "품질 기준을 완전히 충족하지 못했습니다" in v["final"]
    await tools.stop()


class SummaryInventingLLM(FakeLLM):
    """요약 단계에서 원문에 없는 날짜를 만들고, 브리핑이 그 날짜를 옮겨 쓰는 LLM."""

    async def summarize_document(self, meta, quotes, glossary):
        summary, usage = await super().summarize_document(meta, quotes, glossary)
        return summary.model_copy(update={"summary_ko": summary.summary_ko + " 시행일 2028-01-01"}), usage

    async def write_briefing(self, question, summaries, judgements, citations, feedback, on_token=None):
        text, usage = await super().write_briefing(question, summaries, judgements, citations, feedback, on_token)
        return text + "\n- 시행일 2028-01-01 [1]", usage


async def test_summary_invention_is_dropped_and_caught_by_guard():
    """외부 검토 ③: 요약이 지어낸 사실이 '요약에 있으니까' 가드를 통과하던 문제."""
    graph, tools = await make_graph(llm=SummaryInventingLLM())
    cfg, _, snap = await run(graph, BRIEFING)
    v = snap.values
    assert all("2028" not in s["summary_ko"] for s in v["summaries"])          # 지어낸 요약은 버림
    assert v["guard"]["invented"]["extra_dates"] == ["2028-01-01"]             # 브리핑이 옮겨 써도 잡힘
    await tools.stop()


async def test_briefing_stays_within_requested_substance():
    """외부 검토 ②: DEHP를 물었는데 TCE 문서·P003이 영향으로 들어오던 문제."""
    graph, tools = await make_graph()
    _, _, snap = await run(graph, "최근 미국 관보에 DEHP 관련 변경 있어? 브리핑해줘")
    v = snap.values
    assert "117-81-7" in v["plan"]["focus_cas"]
    assert v["documents"] and not any(d["in_scope"] for d in v["documents"])
    assert v["impacts"] == [] and v["summaries"] == [] and not snap.next     # 영향 제품·승인 없음
    assert "찾지 못했습니다" in v["scope_note"] and v["plan"]["days"] == 30  # 기간을 넓혀 다시 찾고도 없음
    assert "요청 범위 확인 결과" in v["final"] and "참고: 요청 범위 밖의 변경" in v["final"]
    doc_no = v["documents"][0]["document_number"]
    assert doc_no in v["final"] and not v["guard"]["invented"]     # 참고 목록의 관보 번호는 지어낸 숫자가 아님 (재측정 B5)
    await tools.stop()


async def test_briefing_for_one_product_judges_only_that_product():
    graph, tools = await make_graph()
    _, _, snap = await run(graph, "P003 금속 탈지 세정제에 영향 주는 최근 미국 규제 변경 브리핑해줘")
    v = snap.values
    assert {i["product_id"] for i in v["impacts"]} == {"P003"}
    assert any(d["in_scope"] for d in v["documents"])
    await tools.stop()


async def test_judge_tool_failure_is_reported_not_treated_as_no_impact():
    """외부 검토 ④: 제품 판정 도구 실패 → TypeError로 전체가 멈추던 문제."""
    graph, tools = await make_graph(fail_tools={"judge_product_compliance"})
    _, _, snap = await run(graph, BRIEFING)
    v = snap.values
    assert any("P003 판정 확인 불가" in g for g in v["gaps"])
    assert [i["product_id"] for i in v["impacts"] if i.get("unresolved")] == ["P003"]
    pending = snap.tasks[0].interrupts[0].value                               # 확인 불가도 담당자에게
    assert pending["impacted_products"][0]["outcomes"] == ["unresolved"]
    await tools.stop()


async def test_follow_up_resets_per_turn_state():
    graph, tools = await make_graph()
    await run(graph, "트리클로로에틸렌 규제 알려줘", thread="same")
    _, _, snap = await run(graph, "안녕?", thread="same")
    v = snap.values
    assert v["route"] == "chat" and v["citations"] == [] and v["judgements"] == {}
    assert len(v["usage"]) == 2 and len(v["history"]) == 4
    await tools.stop()


async def test_baseline_graph_has_no_citations_or_checks():
    graph, tools = await make_graph(builder=build_baseline_graph)
    _, kinds, snap = await run(graph, BRIEFING)
    v = snap.values
    assert v["final"] and v.get("citations", []) == [] and not v.get("guard")
    assert "agent_start" not in kinds                                  # 병렬 에이전트 없음
    await tools.stop()


def test_scope_lines_are_added_by_code_with_matching_label():
    """실모델이 범위 안내를 범위 안 문서에 붙이고 핵심 변경을 '범위 밖'으로 표시하던 문제 → 코드가 넣는다."""
    from app.agents.graph import _add_scope
    draft = "## 요약\n변경 1건.\n\n## 규제 변경 (지역별)\n- TCE 기한 연장 [1]\n\n## 우리 제품 영향\n- P003"
    docs = [{"document_number": "2026-1", "title": "TCE", "in_scope": True},
            {"document_number": "2026-2", "title": "SNUR 26-1", "publication_date": "2026-10-15", "in_scope": False}]
    general = _add_scope(draft, {"documents": docs, "plan": {"focus_cas": []}, "scope_note": ""})
    assert "요청 범위 확인 결과" not in general and "요청 범위 밖" not in general
    assert general.index("회사 제품 성분과 관련 없는 변경") < general.index("## 우리 제품 영향")
    assert "SNUR 26-1 (관보 2026-2" in general and "- TCE 기한 연장 [1]" in general
    focused = _add_scope(draft, {"documents": docs, "plan": {"focus_cas": ["117-81-7"]}, "scope_note": "DEHP 문서 없음"})
    assert focused.startswith("## 요약\n**요청 범위 확인 결과**: DEHP 문서 없음") and "참고: 요청 범위 밖의 변경" in focused


class RefListingLLM(FakeLLM):
    """근거 번호를 '[1], [2], [3]'처럼 나열하는 LLM (재측정 B2·B4)."""

    async def write_briefing(self, question, summaries, judgements, citations, feedback, on_token=None):
        text, usage = await super().write_briefing(question, summaries, judgements, citations, feedback, on_token)
        refs = ", ".join(f"[{n}]" for n in range(1, citations.count("\n[") + 2))
        return text.replace("## 우리 제품 영향", f"- 근거 {refs}\n\n## 우리 제품 영향", 1), usage


async def test_citation_numbers_are_not_counted_as_invented_numbers():
    graph, tools = await make_graph(llm=RefListingLLM())
    _, _, snap = await run(graph, "이번 주 미국 EPA 규제 변경 브리핑해줘")
    v = snap.values
    assert len(v["citations"]) >= 6 and "[6]" in v["draft"]
    assert not v["guard"]["invented"] and v["writing_attempts"] == 1
    await tools.stop()
