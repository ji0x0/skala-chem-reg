"""Step 4 — REST API + SSE (lifespan 포함, FakeLLM + 메모리 MCP, 네트워크 없음, 임시 DB)."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import Settings, get_settings
from app.llm.fake import FakeLLM
from app.main import create_app
from app.repositories.product_db import ProductDB
from app.repositories.reg_db import RegDB
from app.tools.provider import InMemoryToolProvider
from mcp_servers import product_server, reg_db_server, reg_feed_server

NEW = {"product_name": "시험용 세정제", "product_form": "mixture", "export_regions": ["US"],
       "ingredients": [{"cas": "127-18-4", "ingredient_name": "PCE", "role": "주용제", "wt_pct": 99},
                       {"cas": "106-88-7", "ingredient_name": "Butylene oxide", "role": "안정제", "wt_pct": 1}]}


@pytest.fixture
def client(monkeypatch, tmp_path):
    settings = Settings(_env_file=None, llm_backend="fake", app_db_path=tmp_path / "app.db")
    # MCP 서버들도 같은 임시 제품 DB를 보게 한다 (실제 data/app.db를 건드리지 않음)
    products = ProductDB(settings.app_db_path)
    products.seed_if_empty(settings.products_path)
    regdb = RegDB(get_settings().reg_db_path, products)
    for module in (product_server, reg_db_server, reg_feed_server):
        monkeypatch.setattr(module, "db", regdb)
    monkeypatch.setattr(reg_feed_server.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    monkeypatch.setattr(reg_feed_server, "CACHE_DIR", tmp_path / "cache")
    app = create_app(settings, llm=FakeLLM(), tools=InMemoryToolProvider(), checkpointer=InMemorySaver())
    with TestClient(app) as c:
        yield c


def sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_health_and_cors(client):
    h = client.get("/api/v1/health").json()
    assert h["status"] == "ok" and h["products"] == 20 and len(h["tools"]) == 12
    ok = client.options("/api/v1/chat/stream", headers={"Origin": "http://localhost:5173",
                                                       "Access-Control-Request-Method": "POST"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    bad = client.options("/api/v1/chat/stream", headers={"Origin": "http://evil.example",
                                                        "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_product_crud_with_validation_and_judgement(client):
    assert len(client.get("/api/v1/products").json()) == 20
    created = client.post("/api/v1/products", json=NEW)
    assert created.status_code == 201
    body = created.json()
    assert body["product"]["product_id"] == "P021"
    assert body["judgement"]["summary"]["listed"] == 1                 # PCE → 미국 TSCA 6조 등재

    bad = client.post("/api/v1/products", json={**NEW, "ingredients": [
        {"cas": "127-18-5", "ingredient_name": "오타", "role": "주용제", "wt_pct": 80}]})
    assert bad.status_code == 422
    errors = bad.json()["detail"]["errors"]
    assert any("CAS 번호 오류" in e for e in errors) and any("함량 합계 80" in e for e in errors)

    renamed = client.put("/api/v1/products/P021", json={**NEW, "product_name": "시험용 세정제 v2"})
    assert renamed.status_code == 200 and renamed.json()["product"]["product_name"] == "시험용 세정제 v2"
    assert client.get("/api/v1/products/P999").status_code == 404
    assert client.get("/api/v1/health").json()["products"] == 21           # 에이전트 목록도 갱신


def test_regulation_endpoints(client):
    regs = client.get("/api/v1/regulations").json()
    assert len(regs) == 11 and all(0 <= r["unverified"] <= r["listing_count"] for r in regs)
    clp = next(r for r in regs if r["reg_id"] == "EU_CLP_ANNEX_VI")
    assert clp["listing_count"] > 4000 and clp["unverified"] == 0           # 공식 전체 목록
    svhc = client.get("/api/v1/regulations/EU_REACH_SVHC").json()
    assert any(x["cas"] == "117-81-7" for x in svhc["listings"])
    found = client.get("/api/v1/substances", params={"q": "벤젠"}).json()
    assert {"P012"} <= {p["product_id"] for p in found["products"]}
    assert client.get("/api/v1/regulations/NOPE").status_code == 404


def test_lookup_stream_returns_citations(client):
    events = sse(client.post("/api/v1/chat/stream", json={"message": "P002 규제 문제 있어?",
                                                          "thread_id": "api-1"}).text)
    names = [e for e, _ in events]
    assert names[0] == "run_started" and names[-1] == "done"
    final = next(d for e, d in events if e == "final")
    assert final["citations"] and all("quote" in c and "url" in c for c in final["citations"])


def test_briefing_stream_approval_flow(client):
    events = sse(client.post("/api/v1/chat/stream", json={"message": "이번 주 미국 EPA랑 국내 규제 변경 브리핑해줘",
                                                          "thread_id": "api-2"}).text)
    names = [e for e, _ in events]
    assert "approval_required" in names and events[-1][1]["status"] == "awaiting_approval"
    assert {"progress", "tool_call_start", "tool_call_end", "token"} <= set(names)
    pending = next(d for e, d in events if e == "approval_required")
    assert "## 요약" in pending["draft"] and not pending["draft"].startswith("```") and pending["citations"]
    state = client.get("/api/v1/threads/api-2").json()
    assert state["awaiting_approval"] is True and state["draft"] == pending["draft"]

    events = sse(client.post("/api/v1/threads/api-2/approval", json={"approved": True}).text)
    final = next(d for e, d in events if e == "final")
    assert "승인" in final["content"] and events[-1][1]["status"] == "completed"
    assert {c["kind"] for c in final["citations"]} == {"document", "listing"}
    assert client.post("/api/v1/threads/api-2/approval", json={"approved": True}).status_code == 409


def test_threads_are_numbered_listed_and_renamed(client):
    first = client.post("/api/v1/threads").json()
    second = client.post("/api/v1/threads").json()
    assert first["title"] == "001 규제 브리핑" and second["title"] == "002 규제 브리핑"
    events = sse(client.post("/api/v1/chat/stream", json={"message": "P002 규제 문제 있어?"}).text)   # 새 대화 자동 등록
    started = events[0][1]
    assert started["title"] == "003 규제 브리핑"
    renamed = client.patch(f"/api/v1/threads/{first['thread_id']}", json={"title": "  P003 TCE   대응 "}).json()
    assert renamed["title"] == "P003 TCE 대응" and renamed["seq"] == 1                # 이름을 바꿔도 번호 유지
    listed = client.get("/api/v1/threads").json()
    assert {t["title"] for t in listed} == {"P003 TCE 대응", "002 규제 브리핑", "003 규제 브리핑"}
    assert listed[0]["thread_id"] == started["thread_id"]                            # 최근 사용 순
    assert client.patch("/api/v1/threads/none", json={"title": "x"}).status_code == 404
    assert client.patch(f"/api/v1/threads/{first['thread_id']}", json={"title": ""}).status_code == 422
    assert client.options("/api/v1/threads/x", headers={"Origin": "http://localhost:5173",
                                                       "Access-Control-Request-Method": "PATCH"}).status_code == 200


def test_input_validation(client):
    assert client.post("/api/v1/chat/stream", json={"message": ""}).status_code == 422
    assert client.post("/api/v1/feedback", json={"run_id": "x", "score": 5}).status_code == 422
