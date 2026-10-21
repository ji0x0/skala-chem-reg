"""정기 브리핑 저장소 (data/app.db) — 주차별 브리핑과 검토 상태 (Step 10).

한 주(월~일)에 한 건. 생성되면 "검토 대기", 담당자가 읽고 "검토 완료"로 표시한다 (승인이 아니라 검토 기록).
처음 실행할 때 data/weekly/*.json(지난 주차 예시)으로 채운다.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = ("week_id", "period_start", "period_end", "status", "generated_at", "question", "content", "citations",
           "impacted", "documents", "references_count", "gaps", "run_id", "latency_ms", "tokens",
           "reviewer", "comment", "reviewed_at")
JSON_COLUMNS = {"citations", "gaps"}


class WeeklyDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS weekly_briefings (
                    week_id TEXT PRIMARY KEY,               -- ISO 주차 (예: 2026-W42)
                    period_start TEXT, period_end TEXT,     -- 월요일 ~ 일요일
                    status TEXT NOT NULL,                   -- pending_review | reviewed | failed
                    generated_at TEXT, question TEXT, content TEXT,
                    citations TEXT,                         -- JSON
                    impacted TEXT,                          -- 영향 제품 (쉼표 구분)
                    documents INTEGER DEFAULT 0,            -- 회사 관련 변경 문서 수
                    references_count INTEGER DEFAULT 0,     -- 관련 없는 변경 (참고) 수
                    gaps TEXT,                              -- JSON: 확인하지 못한 항목
                    run_id TEXT, latency_ms INTEGER, tokens INTEGER,
                    reviewer TEXT, comment TEXT, reviewed_at TEXT)""")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        out = dict(row)
        for key in JSON_COLUMNS:
            out[key] = json.loads(out[key]) if out.get(key) else []
        return out

    def save(self, record: dict) -> dict:
        values = [json.dumps(record.get(c), ensure_ascii=False) if c in JSON_COLUMNS else record.get(c) for c in COLUMNS]
        with closing(self._connect()) as conn, conn:
            conn.execute(f"INSERT OR REPLACE INTO weekly_briefings ({', '.join(COLUMNS)}) "
                         f"VALUES ({', '.join('?' * len(COLUMNS))})", values)
        return self.get(record["week_id"])

    def get(self, week_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            return self._row(conn.execute("SELECT * FROM weekly_briefings WHERE week_id = ?", (week_id,)).fetchone())

    def list(self) -> list[dict]:
        """목록용 — 본문·근거는 빼고 (최근 주차 먼저)."""
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT week_id, period_start, period_end, status, generated_at, impacted, documents, "
                                "references_count, reviewer, reviewed_at FROM weekly_briefings "
                                "ORDER BY period_start DESC").fetchall()
        return [dict(r) for r in rows]

    def review(self, week_id: str, reviewer: str, comment: str) -> dict | None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE weekly_briefings SET status = 'reviewed', reviewer = ?, comment = ?, reviewed_at = ? "
                         "WHERE week_id = ? AND status != 'failed'",
                         (reviewer, comment or None, datetime.now(timezone.utc).isoformat(timespec="seconds"), week_id))
        return self.get(week_id)

    def seed_if_empty(self, folder: Path) -> int:
        """지난 주차 예시(data/weekly/*.json)로 채운다 — 이미 있으면 건드리지 않는다."""
        with closing(self._connect()) as conn:
            if conn.execute("SELECT COUNT(*) FROM weekly_briefings").fetchone()[0]:
                return 0
        files = sorted(Path(folder).glob("*.json")) if Path(folder).exists() else []
        for path in files:
            self.save(json.loads(path.read_text(encoding="utf-8")))
        return len(files)
