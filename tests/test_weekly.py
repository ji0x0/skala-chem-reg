"""Step 10 — 정기 브리핑: 주차 계산, 기간 검색, 생성·저장, 검토 완료, API, 예시 시드.

네트워크 없이: 관보·법제처 스냅샷 + Fake LLM.
"""
import json
from datetime import date, datetime, timezone

import pytest

from app.repositories.weekly_db import WeeklyDB
from app.weekly import WeeklyScheduler, last_complete_weeks, week_of
from mcp_servers import reg_feed_server
from tests.test_admin import AUTH, make_client

tool = lambda t: getattr(t, "fn", t)  # noqa: E731


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(reg_feed_server.settings, "feed_mode", "snapshot")
    with make_client(monkeypatch, tmp_path) as c:
        yield c


def test_week_math():
    assert week_of(date(2026, 10, 14)) == ("2026-W42", date(2026, 10, 12), date(2026, 10, 18))
    weeks = last_complete_weeks(date(2026, 10, 21), 3)                   # 수요일 기준 끝난 주 3개
    assert [w[0] for w in weeks] == ["2026-W42", "2026-W41", "2026-W40"] and weeks[2][1] == date(2026, 9, 28)


def test_period_search_on_snapshots(monkeypatch):
    monkeypatch.setattr(reg_feed_server.settings, "feed_mode", "snapshot")
    us = tool(reg_feed_server.search_federal_register)(since="2026-10-12", until="2026-10-18")
    assert us["documents"] and all("2026-10-12" <= d["publication_date"] <= "2026-10-18" for d in us["documents"])
    assert tool(reg_feed_server.search_federal_register)(since="2026-09-28", until="2026-10-04")["documents"] == []
    kr = tool(reg_feed_server.search_kr_admin_rules)("화학물질", since="2026-03-01", until="2026-03-31")
    assert all("2026-03-01" <= d["issued_on"] <= "2026-03-31" for d in kr["documents"])


def test_run_review_and_list(client):
    assert client.post("/api/v1/weekly/run", json={"start": "2026-10-12"}).status_code == 401   # 생성은 관리자만
    week = client.post("/api/v1/weekly/run", json={"start": "2026-10-12"}, headers=AUTH).json()
    assert week["week_id"] == "2026-W42" and week["status"] == "pending_review"
    assert week["documents"] >= 1 and "P003" in (week["impacted"] or "") and week["citations"]
    assert "2026-10-12~2026-10-18" in week["question"]

    empty = client.post("/api/v1/weekly/run", json={"start": "2026-09-28"}, headers=AUTH).json()
    assert empty["documents"] == 0 and not empty["impacted"]
    assert "**이번 주 확인 결과**: 이 기간(2026-09-28~2026-10-04)에 회사 제품 성분과 관련된 규제 변경 문서가 없습니다" in empty["content"]

    listed = [w["week_id"] for w in client.get("/api/v1/weekly").json()]
    assert listed == ["2026-W42", "2026-W41", "2026-W40"]                 # 예시(data/weekly) 시드 + 새로 만든 주는 덮어씀
    done = client.post("/api/v1/weekly/2026-W42/review", json={"reviewer": "팀장", "comment": "P003 공지"}).json()
    assert done["status"] == "reviewed" and done["reviewer"] == "팀장" and done["reviewed_at"]
    assert client.get("/api/v1/weekly/2026-W99").status_code == 404
    assert client.post("/api/v1/weekly/run", json={"start": "2026-10-13"}, headers=AUTH).status_code == 422  # 월요일만

    runs = client.get("/api/v1/admin/runs", headers=AUTH).json()
    assert {r["kind"] for r in runs} == {"weekly"}                       # 관리자 실행 기록에도 남는다


def test_seed_and_scheduler(tmp_path):
    db = WeeklyDB(tmp_path / "app.db")
    folder = tmp_path / "weekly"
    folder.mkdir()
    (folder / "2026-W42.json").write_text(json.dumps({"week_id": "2026-W42", "period_start": "2026-10-12",
                                                      "period_end": "2026-10-18", "status": "pending_review",
                                                      "content": "예시", "citations": [], "gaps": []}))
    assert db.seed_if_empty(folder) == 1 and db.seed_if_empty(folder) == 0   # 이미 있으면 건드리지 않음

    class Svc:
        weekly = db
    scheduler = WeeklyScheduler(Svc(), hour=9)
    monday_10_kst = datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)      # 월 10:00 KST
    assert scheduler.due(monday_10_kst) is None                           # 지난주(W42)는 이미 있음
    assert scheduler.due(datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc))[0] == "2026-W43"
    assert scheduler.due(datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc)) is None    # 화요일 08시 KST
