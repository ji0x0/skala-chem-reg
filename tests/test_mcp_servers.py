"""Step 2 — MCP 서버를 실제 MCP 클라이언트로 호출한다.

fastmcp.Client(server)는 프로세스를 띄우지 않고 메모리 안에서 MCP 프로토콜로 연결한다(빠른 테스트).
stdio로 실제 프로세스를 띄우는 확인은 docs/lab/step02-mcp.md의 확인 명령에서 한다.
네트워크가 필요한 실시간 관보 호출은 테스트에서 하지 않는다 (스냅샷 대체 경로만 확인).
"""
import json

import httpx
import pytest
from fastmcp import Client

from app.domain.mentions import find_substance_mentions
from mcp_servers import product_server, reg_db_server, reg_feed_server


def data(result):
    """도구 결과(구조화 데이터 또는 텍스트)를 파이썬 값으로."""
    if result.data is not None:
        return result.data
    return json.loads(result.content[0].text)


async def test_product_server_tools():
    async with Client(product_server.mcp) as client:
        names = {t.name for t in await client.list_tools()}
        assert names == {"list_products", "get_product", "find_products_by_cas"}
        hits = data(await client.call_tool("find_products_by_cas", {"cas_numbers": ["79-01-6"]}))
        assert [h["product_id"] for h in hits] == ["P003"]


async def test_reg_db_server_tool_resource_prompt():
    async with Client(reg_db_server.mcp) as client:
        judged = data(await client.call_tool("judge_product_compliance", {"product_id": "P002"}))
        assert judged["summary"]["exceeds"] == 3 and judged["unverified_data"] is False    # Entry 51 ×2 + 국내 이산화티타늄

        terms = data(await client.call_tool("glossary_lookup",
                                            {"text": "SVHC on the Candidate List; 优先控制化学品"}))
        assert {"SVHC", "Candidate List", "优先控制化学品"} <= {t["term"] for t in terms}

        card = await client.read_resource("regulation://EU_REACH_SVHC")
        assert "고위험 우려물질" in card[0].text and "117-81-7" in card[0].text

        prompt = await client.get_prompt("briefing_procedure", {"period": "2026-10-13 ~ 2026-10-20"})
        assert "숫자·CAS·날짜는 원문과 같아야" in prompt.messages[0].content.text


async def test_unknown_product_returns_tool_error():
    async with Client(reg_db_server.mcp) as client:
        with pytest.raises(Exception, match="등록되지 않은 제품"):
            await client.call_tool("judge_product_compliance", {"product_id": "P999"})


async def test_feed_falls_back_to_snapshot_when_offline(monkeypatch, tmp_path):
    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(reg_feed_server.httpx, "get", offline)
    monkeypatch.setattr(reg_feed_server, "CACHE_DIR", tmp_path)          # 본문 캐시 없음
    monkeypatch.setattr(reg_feed_server, "FULLTEXT_DIR", tmp_path / "none")
    async with Client(reg_feed_server.mcp) as client:
        result = data(await client.call_tool("search_federal_register", {}))
        assert result["source"] == "snapshot" and result["documents"]
        doc = data(await client.call_tool("get_federal_register_document",
                                          {"document_number": "2026-20964"}))
        assert doc["source"] == "snapshot" and doc["text_source"] == "abstract"
        assert "제목·요약만 사용" in doc["text_warning"]            # 대체했다는 사실을 숨기지 않는다
        assert doc["substance_mentions"][0]["cas"] == "79-01-6"    # 제목·요약의 이름으로 TCE 식별

        # 본문 캐시가 있으면 오프라인에서도 본문을 쓴다
        (tmp_path / "2026-20964.txt").write_text("Trichloroethylene (TCE) full text ...", encoding="utf-8")
        cached = data(await client.call_tool("get_federal_register_document",
                                             {"document_number": "2026-20964"}))
        assert cached["text_source"] == "full_text" and cached["text_warning"] is None


async def test_new_document_full_text_is_downloaded_and_cached(monkeypatch, tmp_path):
    """외부 검토 ①: 저장본이 없는 새 문서의 본문을 받으면 저장 단계에서 NameError가 나던 문제."""
    meta = {"document_number": "2099-00001", "title": "Trichloroethylene (TCE) test rule", "type": "Rule",
            "abstract": "", "publication_date": "2099-01-01", "html_url": "https://example.gov/d",
            "raw_text_url": "https://example.gov/raw.txt", "effective_on": None, "comments_close_on": None}

    class Resp:
        def __init__(self, status, body=None, text=""):
            self.status_code, self._body, self.text, self.headers = status, body, text, {}
        def json(self):
            return self._body
        def raise_for_status(self):
            pass

    calls = []
    def fake_get(url, **kwargs):
        calls.append(url)
        return Resp(200, meta) if url.endswith(".json") else Resp(200, text="<pre>Trichloroethylene (TCE) full text</pre>")
    monkeypatch.setattr(reg_feed_server.httpx, "get", fake_get)
    monkeypatch.setattr(reg_feed_server, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(reg_feed_server, "FULLTEXT_DIR", tmp_path / "none")
    async with Client(reg_feed_server.mcp) as client:
        doc = data(await client.call_tool("get_federal_register_document", {"document_number": "2099-00001"}))
        assert doc["text_source"] == "full_text" and "full text" in doc["text"] and doc["text_warning"] is None
        assert (tmp_path / "2099-00001.txt").exists()                      # 저장됨
        downloads = sum(not u.endswith(".json") for u in calls)
        await client.call_tool("get_federal_register_document", {"document_number": "2099-00001"})
        assert sum(not u.endswith(".json") for u in calls) == downloads    # 두 번째는 저장본 사용


async def test_snapshot_mode_uses_frozen_inputs_without_network(monkeypatch):
    """평가용: FEED_MODE=snapshot이면 네트워크를 전혀 쓰지 않고 저장된 목록·본문만 쓴다."""
    def no_network(*args, **kwargs):
        raise AssertionError("스냅샷 모드에서 네트워크 호출")
    monkeypatch.setattr(reg_feed_server.httpx, "get", no_network)
    monkeypatch.setattr(reg_feed_server, "settings", reg_feed_server.settings.model_copy(update={"feed_mode": "snapshot"}))
    async with Client(reg_feed_server.mcp) as client:
        result = data(await client.call_tool("search_federal_register", {"days": 7}))
        assert result["source"] == "snapshot" and len(result["documents"]) == 4
        doc = data(await client.call_tool("get_federal_register_document", {"document_number": "2026-20964"}))
        assert doc["text_source"] == "full_text" and "December 31, 2027" in doc["text"]


async def test_kr_feed_disabled_without_key():
    async with Client(reg_feed_server.mcp) as client:
        result = data(await client.call_tool("search_kr_admin_rules", {"query": "유해화학물질"}))
        assert result["source"] in ("disabled", "live")


def test_name_matching_avoids_common_word_false_positive():
    subs = [{"cas": "7439-92-1", "name_en": "Lead", "name_ko": "납"},
            {"cas": "117-81-7", "name_en": "Bis(2-ethylhexyl) phthalate (DEHP)", "name_ko": "DEHP"}]
    assert find_substance_mentions("This may lead to delays.", subs) == []
    hits = {m["cas"] for m in find_substance_mentions("Restriction of Lead (Pb) and DEHP in PVC", subs)}
    assert hits == {"7439-92-1", "117-81-7"}
