"""Step 7 — 관리자 API: 토큰 잠금, 실행 기록(질문·승인), 피드백 연결, 평가 결과."""
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
from tests.test_api import sse

TOKEN = "test-admin-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def make_client(monkeypatch, tmp_path, admin_token=TOKEN):
    settings = Settings(_env_file=None, llm_backend="fake", app_db_path=tmp_path / "app.db", admin_token=admin_token)
    products = ProductDB(settings.app_db_path)
    products.seed_if_empty(settings.products_path)
    regdb = RegDB(get_settings().reg_db_path, products)
    for module in (product_server, reg_db_server, reg_feed_server):
        monkeypatch.setattr(module, "db", regdb)
    monkeypatch.setattr(reg_feed_server.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    monkeypatch.setattr(reg_feed_server, "CACHE_DIR", tmp_path / "cache")
    app = create_app(settings, llm=FakeLLM(), tools=InMemoryToolProvider(), checkpointer=InMemorySaver())
    return TestClient(app)


@pytest.fixture
def client(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as c:
        yield c


def test_admin_requires_token(monkeypatch, tmp_path, client):
    assert client.get("/api/v1/admin/overview").status_code == 401
    assert client.get("/api/v1/admin/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    empty = client.get("/api/v1/admin/overview", headers=AUTH).json()
    assert empty["runs"]["totals"]["runs"] == 0 and empty["runs"]["totals"]["quality_pass_rate"] is None


def test_admin_closed_when_token_not_configured(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path / "x", admin_token=None) as c:
        assert c.get("/api/v1/admin/overview", headers=AUTH).status_code == 503


def test_runs_approvals_and_feedback_are_recorded(client):
    events = sse(client.post("/api/v1/chat/stream", json={"message": "트리클로로에틸렌 해당 규제 알려줘"}).text)
    run_id = events[0][1]["run_id"]
    client.post("/api/v1/feedback", json={"run_id": run_id, "score": 1, "comment": "정확함"})

    events = sse(client.post("/api/v1/chat/stream", json={"message": "이번 주 미국 EPA 규제 변경 브리핑해줘"}).text)
    thread = events[0][1]["thread_id"]
    assert any(e == "approval_required" for e, _ in events)
    pending = client.get("/api/v1/admin/approvals", headers=AUTH).json()["pending"]
    assert [p["thread_id"] for p in pending] == [thread] and pending[0]["impacted"]

    sse(client.post(f"/api/v1/threads/{thread}/approval", json={"approved": False, "comment": "근거 재확인",
                                                                "approver": "팀장"}).text)
    approvals = client.get("/api/v1/admin/approvals", headers=AUTH).json()
    assert approvals["pending"] == []
    decided = approvals["history"][0]
    assert decided["approved"] == 0 and decided["approver"] == "팀장" and decided["comment"] == "근거 재확인"
    assert decided["impacted"] and decided["title"].endswith("규제 브리핑")

    runs = client.get("/api/v1/admin/runs", headers=AUTH).json()
    assert [r["kind"] for r in runs] == ["approval", "question", "question"]
    assert runs[2]["route"] == "lookup" and runs[2]["tokens"] > 0 and runs[2]["latency_ms"] >= 0
    assert runs[1]["status"] == "awaiting_approval" and runs[1]["tokens"] == 0   # 사용량은 승인 후 final에 한 번
    assert runs[0]["quality_passed"] is None and runs[1]["quality_passed"] is not None   # 품질 검토는 브리핑 질문에만

    overview = client.get("/api/v1/admin/overview", headers=AUTH).json()
    assert overview["runs"]["totals"]["rejected"] == 1 and overview["pending_approvals"] == 0
    assert overview["feedback"] == {"total": 1, "up": 1, "down": 0}
    assert overview["regulations"]["count"] == 11 and overview["regulations"]["unverified"] == 0

    feedback = client.get("/api/v1/admin/feedback", headers=AUTH).json()
    assert feedback[0]["question"].startswith("트리클로로에틸렌") and feedback[0]["route"] == "lookup"


def test_evaluations_list_before_after_results(client):
    items = client.get("/api/v1/admin/evaluations", headers=AUTH).json()
    assert items and "briefing" in items[0]["summary"] and items[0]["name"] >= items[-1]["name"]
