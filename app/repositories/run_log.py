"""실행 기록 저장소 (data/app.db) — 관리자 화면의 처리량·비용·승인 이력.

대화 내용은 체크포인터가 갖지만, "몇 건을 처리했고 얼마나 걸렸고 무엇을 승인·반려했는가"는 어디에도 남지 않는다.
요청(질문 1건 또는 승인·반려 1건)이 끝날 때마다 한 줄씩 남긴다. 상세 추적은 LangSmith 트레이스(run_id로 연결).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

COLUMNS = ("run_id", "thread_id", "kind", "route", "question", "status", "latency_ms", "tokens", "usd",
           "quality_passed", "impacted", "approved", "approver", "comment")


class RunLog:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
                    kind TEXT NOT NULL,                 -- question | approval
                    route TEXT, question TEXT,
                    status TEXT NOT NULL,               -- completed | awaiting_approval | failed
                    latency_ms INTEGER, tokens INTEGER DEFAULT 0, usd REAL DEFAULT 0,
                    quality_passed INTEGER,             -- 브리핑 품질 검토 통과 여부 (브리핑만)
                    impacted TEXT,                      -- 승인 요청에 오른 제품 (쉼표 구분)
                    approved INTEGER, approver TEXT, comment TEXT,   -- 승인·반려 기록 (kind=approval)
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, **row) -> None:
        values = [row.get(c) for c in COLUMNS]
        with closing(self._connect()) as conn, conn:
            conn.execute(f"INSERT OR REPLACE INTO runs ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                         values)

    def recent(self, limit: int = 50, kind: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM runs", []
        if kind:
            sql, args = sql + " WHERE kind = ?", [kind]
        with closing(self._connect()) as conn:
            rows = conn.execute(sql + " ORDER BY created_at DESC, rowid DESC LIMIT ?", (*args, limit))
            return [dict(r) for r in rows.fetchall()]

    def for_thread(self, thread_id: str) -> list[dict]:
        """한 대화의 실행 기록 (오래된 순)."""
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM runs WHERE thread_id = ? ORDER BY created_at, rowid", (thread_id,))
            return [dict(r) for r in rows.fetchall()]

    def summary(self) -> dict:
        """경로별 처리량·평균 시간, 전체 토큰·비용, 승인·반려 수, 품질 검토 통과율."""
        with closing(self._connect()) as conn:
            by_route = [dict(r) for r in conn.execute("""
                SELECT COALESCE(route, '(미분류)') AS route, COUNT(*) AS runs,
                       SUM(status = 'failed') AS failed, CAST(AVG(latency_ms) AS INTEGER) AS avg_latency_ms
                FROM runs WHERE kind = 'question' GROUP BY route ORDER BY runs DESC""")]
            totals = dict(conn.execute("""
                SELECT COUNT(*) AS runs, COUNT(DISTINCT thread_id) AS threads,
                       COALESCE(SUM(tokens), 0) AS tokens, ROUND(COALESCE(SUM(usd), 0), 6) AS usd,
                       SUM(status = 'failed') AS failed,
                       SUM(status = 'awaiting_approval') AS approval_requests,
                       SUM(kind = 'approval' AND approved = 1) AS approved,
                       SUM(kind = 'approval' AND approved = 0) AS rejected,
                       AVG(quality_passed) AS quality_pass_rate
                FROM runs""").fetchone())
            daily = [dict(r) for r in conn.execute("""
                SELECT DATE(created_at) AS day, COUNT(*) AS runs, COALESCE(SUM(tokens), 0) AS tokens
                FROM runs GROUP BY day ORDER BY day DESC LIMIT 14""")]
        rate = totals.pop("quality_pass_rate")              # 브리핑이 없으면 None ("0%"가 아니라 "기록 없음")
        totals = {k: (v or 0) for k, v in totals.items()}
        totals["quality_pass_rate"] = round(rate, 3) if rate is not None else None
        return {"totals": totals, "by_route": by_route, "daily": daily}
