"""Step 11 — EU 수집: REACH·CLP 개정 법령 검색·본문, 물질명 경계, 브리핑 (EU 스냅샷, 네트워크 없이)."""
import httpx
import pytest

from app.domain.mentions import find_substance_mentions
from mcp_servers import reg_feed_server
from tests.test_graph import make_graph, run

tool = lambda t: getattr(t, "fn", t)  # noqa: E731


@pytest.fixture(autouse=True)
def snapshot_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(reg_feed_server.settings, "feed_mode", "snapshot")
    monkeypatch.setattr(reg_feed_server.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))


def test_eu_search_window_and_period():
    search = tool(reg_feed_server.search_eu_acts)
    assert search(days=90)["documents"] == []                                    # 스냅샷 받은 날 기준 90일
    assert [a["number"] for a in search(days=365)["documents"]] == ["2026/1168", "2026/859"]
    assert [a["number"] for a in search(since="2026-04-01", until="2026-04-30")["documents"]] == ["2026/859"]


def test_eu_act_dates_and_mentions():
    act = tool(reg_feed_server.get_eu_act)("32025R1988")
    assert act["adopted_on"] == "2025-10-02" and act["published_on"] == "2025-10-03"
    assert [m["cas"] for m in act["substance_mentions"]] == ["335-67-1"]           # PFOA (회사 제품 성분)
    assert act["html_url"].endswith("CELEX:32025R1988")


def test_name_inside_larger_substance_name_is_not_a_mention():
    subs = [{"cas": "108-95-2", "name_en": "Phenol", "name_ko": ""}, {"cas": "79-01-6", "name_en": "Trichloroethylene (TCE)",
                                                                       "name_ko": ""}]
    assert find_substance_mentions("salt with 4,4'-[…]bis[phenol] (1:1)", subs) == []
    found = find_substance_mentions("Phenol is classified; use of trichloroethylene (TCE)", subs)
    assert {m["cas"] for m in found} == {"108-95-2", "79-01-6"}                   # 단독 이름·괄호 약어는 인정


async def test_eu_change_briefing_lists_acts_and_svhc_gap():
    graph, tools = await make_graph()
    _, _, snap = await run(graph, "최근 EU 규제 변경 브리핑해줘", thread="eu1")
    v = snap.values
    assert v["plan"]["regions"] == ["EU"] and v["plan"].get("eu_days") == 365          # 90일에 없어 1년으로
    assert {d["document_number"] for d in v["documents"]} == {"32026R1168", "32026R0859"}
    assert not any(d["in_scope"] for d in v["documents"]) and not v["impacts"]
    assert "회사 제품 성분과 관련 없는 변경" in v["final"] and "EU 2026/1168" in v["final"]
    assert any("ECHA 결정" in g for g in v["gaps"])
    await tools.stop()


async def test_focused_eu_question_without_matching_act_says_so_first():
    graph, tools = await make_graph()
    _, _, snap = await run(graph, "PFOA 관련 EU REACH 최근 변경 있어? 브리핑해줘", thread="eu2")
    v = snap.values
    assert "EU REACH·CLP 개정 법령 최근 365일" in v["scope_note"]                       # 1년 안에는 PFOA 개정이 없다
    assert v["final"].count("요청 범위 확인 결과") == 1
    await tools.stop()
