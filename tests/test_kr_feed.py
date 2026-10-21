"""Step 8 — 국내 변경 수집: 한글 물질명·고유번호 매칭, 스냅샷 기간, 개정 내용 vs 본문, ReAct + 안전장치, 브리핑.

네트워크 없이: 법제처 스냅샷(data/feeds/kr_*)과 대본대로 도구를 부르는 가짜 모델을 쓴다.
"""
import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.domain.mentions import find_korean_mentions, korean_names
from app.llm.fake import FakeLLM
from mcp_servers import reg_feed_server
from tests.test_graph import make_graph, run

ACCIDENT_RULE = "2100000275070"        # 사고대비물질의 지정 (화학물질안전원고시 제2026-2호, 2026-03-10) — 부칙에 자일렌 CAS
HANDLING_RULE = "2100000282986"        # 유해화학물질별 구체적인 취급기준 (2026-07-27) — 개정문·신구 대비 없음
QUESTION = "최근 국내 화학물질 규제 변경 브리핑해줘"
tool = lambda t: getattr(t, "fn", t)  # noqa: E731  FastMCP 도구 객체 → 원래 함수


@pytest.fixture(autouse=True)
def snapshot_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(reg_feed_server.settings, "feed_mode", "snapshot")
    monkeypatch.setattr(reg_feed_server.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    monkeypatch.setattr(reg_feed_server, "KR_CACHE_DIR", tmp_path / "kr")


def test_korean_names_and_mentions():
    assert korean_names("디이소프로필아민; 디아이피에이(DIPA)") == ["디이소프로필아민", "디아이피에이"]
    assert korean_names("N-(1,3-디메틸부틸-N'-페닐-p-페닐렌디아민)") == ["N-(1,3-디메틸부틸-N'-페닐-p-페닐렌디아민)"]  # "N-"로 자르지 않음
    subs = [{"cas": "79-01-6", "name_en": "Trichloroethylene", "name_ko": "트리클로로에틸렌"},
            {"cas": "108-88-3", "name_en": "Toluene", "name_ko": "톨루엔"},
            {"cas": "7439-92-1", "name_en": "Lead", "name_ko": "납"}]
    found = find_korean_mentions("트리클로로에틸렌을 취급하는 자, 톨루엔디이소시아네이트, 납품 기한", subs)
    assert [m["cas"] for m in found] == ["79-01-6"]          # 조사는 허용, 다른 물질의 일부·일상어는 제외


def test_snapshot_search_honors_day_window():
    search = tool(reg_feed_server.search_kr_admin_rules)
    assert search("사고대비물질", days=90)["documents"] == []
    found = search("사고대비물질", days=365)
    assert found["source"] == "snapshot" and [d["serial"] for d in found["documents"]] == [ACCIDENT_RULE]
    assert "OC=" not in str(found)                            # 인증키가 든 상세 링크는 돌려주지 않는다


def test_change_mentions_are_separated_from_body_mentions():
    get = tool(reg_feed_server.get_kr_admin_rule)
    handling = get(HANDLING_RULE)
    assert not handling["change_text_available"] and handling["substance_mentions"] == []
    assert handling["body_mentions"]                          # 현행 본문엔 있지만 무엇이 바뀌었는지는 모른다 (스냅샷은 큰 별표 앞부분만)
    accident = get(ACCIDENT_RULE)
    xylene = next(m for m in accident["substance_mentions"] if m["cas"] == "1330-20-7")
    assert "1330-20-7" in xylene["matched_terms"]             # "자일렌"이라 이름은 다르지만 CAS로 연결
    assert accident["html_url"].endswith(f"admRulSeq={ACCIDENT_RULE}")


class Scripted(GenericFakeChatModel):
    """대본대로 도구를 부르는 채팅 모델 (ReAct 경로 시험용)."""

    def bind_tools(self, tools, **kwargs):
        return self


class ReactLLM(FakeLLM):
    def __init__(self, script):
        super().__init__()
        self.agent_model = Scripted(messages=iter(script))


def react_script():
    return [AIMessage(content="", tool_calls=[{"name": "search_kr_admin_rules", "args": {"query": "사고대비물질"}, "id": "c1"}]),
            AIMessage(content="선택: 2100000275070, 1234567890123")]       # 두 번째 번호는 지어낸 것


async def collect(graph, question):
    cfg = {"configurable": {"thread_id": "kr"}}
    events = []
    async for mode, payload in graph.astream({"question": question}, cfg, stream_mode=["custom", "updates"]):
        if mode == "custom":
            events.append(payload)
    return events, (await graph.aget_state(cfg)).values


async def test_react_agent_searches_and_picks_only_real_serials():
    graph, tools = await make_graph(llm=ReactLLM(react_script() * 2))      # 90일 → 1년, 두 번 실행
    events, v = await collect(graph, QUESTION)
    agent_queries = [e["args"]["query"] for e in events if e["type"] == "tool_call_start"
                     and e["tool"] == "search_kr_admin_rules" and "body" in e["args"]]
    assert "사고대비물질" in agent_queries                                  # LLM이 정한 검색어로 도구 호출
    ends = [e["summary"] for e in events if e["type"] == "agent_end" and e["agent"] == "kr_feed"]
    assert all(s.startswith("LLM 선택") for s in ends)
    assert {d["document_number"] for d in v["documents"]} == {ACCIDENT_RULE}  # 지어낸 번호는 버림
    await tools.stop()


async def test_safety_net_when_agent_fails():
    class Broken(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        async def _agenerate(self, *args, **kwargs):
            raise ValueError("tool call format")

    llm = FakeLLM()
    llm.agent_model = Broken(messages=iter([]))
    graph, tools = await make_graph(llm=llm)
    _, v = await collect(graph, QUESTION)
    assert any("국내 수집 에이전트(LLM) 실패" in e["error"] for e in v["errors"])
    assert [d["document_number"] for d in v["documents"] if d["in_scope"]] == [ACCIDENT_RULE]   # 안전장치가 찾음
    await tools.stop()


async def test_domestic_briefing_widens_window_and_judges_domestic_rules():
    graph, tools = await make_graph()                      # FakeLLM: 도구 호출 모델 없음 → 안전장치
    _, _, snap = await run(graph, QUESTION, thread="kr2")
    v = snap.values
    assert v["research_round"] == 2 and v["plan"]["kr_days"] == 365          # 90일에 없어 1년으로
    assert snap.next == ("approval",)
    assert sorted(i["product_id"] for i in v["impacts"]) == ["P004", "P012"]  # 크실렌 함유 제품
    assert all(f["region"] == "KR" for i in v["impacts"] for f in i["findings"])
    doc_cites = [c for c in v["citations"] if c["kind"] == "document"]
    assert doc_cites and all(c["translation_ko"] == "" for c in doc_cites)    # 국내 원문은 번역하지 않음
    assert "화학물질안전원고시 제2026-2호" in v["draft"] and "관보 2100000275070" not in v["draft"]
    await tools.stop()


async def test_question_region_overrides_llm_plan():
    """실모델 계획이 '국내' 질문에 미국까지 넣어 미국 문서·제품이 섞이던 문제 → 질문의 지역을 따른다."""
    from app.llm.schemas import BriefingPlan

    class BothRegions(FakeLLM):
        async def plan(self, question, today):
            plan, usage = await super().plan(question, today)
            return BriefingPlan(**{**plan.model_dump(), "regions": ["KR", "US"]}), usage

    graph, tools = await make_graph(llm=BothRegions())
    _, _, snap = await run(graph, QUESTION, thread="kr3")
    v = snap.values
    assert v["plan"]["regions"] == ["KR"] and any("질문의 지역으로 바로잡음" in c for c in v["corrections"])
    assert {d["region"] for d in v["documents"]} == {"KR"}
    await tools.stop()
