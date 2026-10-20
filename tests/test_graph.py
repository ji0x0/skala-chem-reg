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
