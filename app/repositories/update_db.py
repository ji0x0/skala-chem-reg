"""규제 DB 갱신 후보 저장소 (data/app.db) — Step 12.

목록·새 버전마다 한 건. 감지되면 "승인 대기", 담당자가 승인하면 "반영", 반려하면 "반려".
같은 버전은 다시 올리지 않는다 (반려한 버전도) — 더 새 버전이 나와야 새 후보가 생긴다.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = ("reg_id", "label", "current_version", "new_version", "effective_date", "detected_at", "status",
           "counts", "diff", "company", "products", "facts", "summary", "candidate_path", "thread_id",
           "decided_by", "comment", "decided_at", "applied_counts")
JSON_COLUMNS = {"counts", "diff", "company", "products", "applied_counts"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UpdateDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reg_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reg_id TEXT NOT NULL, label TEXT,
                    current_version TEXT, new_version TEXT NOT NULL,   -- 통합본 CELEX
                    effective_date TEXT,                    -- 새 버전의 기준일 (오늘보다 뒤면 적용 예정 판)
                    detected_at TEXT,
                    status TEXT NOT NULL,                   -- pending | applied | rejected | failed | no_change
                    counts TEXT, diff TEXT, company TEXT, products TEXT,   -- JSON: 바뀐 행 수·행·회사 성분·제품 판정 변화
                    facts TEXT, summary TEXT,               -- 코드가 만든 사실 / 승인 담당자용 설명
                    candidate_path TEXT,                    -- 새 버전 행 (승인하면 이 파일이 bulk 파일을 대신)
                    thread_id TEXT,                         -- 승인 대기 중인 갱신 그래프 (체크포인터)
                    decided_by TEXT, comment TEXT, decided_at TEXT,
                    applied_counts TEXT,                    -- JSON: 반영 후 DB 행 수
                    UNIQUE (reg_id, new_version))""")

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
            out[key] = json.loads(out[key]) if out.get(key) else None
        return out

    def create(self, record: dict) -> dict:
        values = [json.dumps(record.get(c), ensure_ascii=False) if c in JSON_COLUMNS else record.get(c) for c in COLUMNS]
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(f"INSERT INTO reg_updates ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                               values)
        return self.get(cur.lastrowid)

    def get(self, update_id: int) -> dict | None:
        with closing(self._connect()) as conn:
            return self._row(conn.execute("SELECT * FROM reg_updates WHERE id = ?", (update_id,)).fetchone())

    def find(self, reg_id: str, new_version: str) -> dict | None:
        with closing(self._connect()) as conn:
            return self._row(conn.execute("SELECT * FROM reg_updates WHERE reg_id = ? AND new_version = ?",
                                          (reg_id, new_version)).fetchone())

    def list(self, status: str | None = None) -> list[dict]:
        """목록용 — 바뀐 행 전체(diff)는 빼고 (최근 먼저)."""
        cols = [c for c in COLUMNS if c != "diff"]
        sql = f"SELECT id, {', '.join(cols)} FROM reg_updates" + (" WHERE status = ?" if status else "")
        with closing(self._connect()) as conn:
            rows = conn.execute(sql + " ORDER BY id DESC", (status,) if status else ()).fetchall()
        return [self._row(r) for r in rows]

    def pending_count(self) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM reg_updates WHERE status = 'pending'").fetchone()[0]

    def decide(self, update_id: int, status: str, decided_by: str, comment: str,
               applied_counts: dict | None = None) -> dict | None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE reg_updates SET status = ?, decided_by = ?, comment = ?, decided_at = ?, "
                         "applied_counts = ? WHERE id = ?",
                         (status, decided_by, comment or None, now(),
                          json.dumps(applied_counts, ensure_ascii=False) if applied_counts else None, update_id))
        return self.get(update_id)
