"""대화 목록 저장소 (data/app.db) — 대화 이름·번호·마지막 사용 시각.

대화 내용과 승인 대기 상태는 LangGraph 체크포인터(checkpoints.db)가 가진다. 여기서는 화면의 대화 목록에
필요한 정보만 둔다. 새 대화는 "001 규제 브리핑", "002 규제 브리핑" … 순서로 이름을 붙이고, 사용자가 바꿀 수 있다.
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

DEFAULT_TITLE = "{seq:03d} 규제 브리핑"
MAX_TITLE = 60


class ThreadDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS threads (thread_id TEXT PRIMARY KEY, seq INTEGER UNIQUE, title TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, thread_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM threads ORDER BY updated_at DESC, seq DESC LIMIT ?", (limit,))
            return [dict(r) for r in rows.fetchall()]

    def create(self, thread_id: str | None = None) -> dict:
        """새 대화. 번호는 지금까지 가장 큰 번호 + 1 (이름을 바꿔도 번호는 유지)."""
        thread_id = thread_id or f"t-{uuid.uuid4().hex[:12]}"
        with closing(self._connect()) as conn, conn:
            seq = (conn.execute("SELECT COALESCE(MAX(seq), 0) FROM threads").fetchone()[0]) + 1
            conn.execute("INSERT INTO threads (thread_id, seq, title) VALUES (?, ?, ?)",
                         (thread_id, seq, DEFAULT_TITLE.format(seq=seq)))
        return self.get(thread_id)

    def register(self, thread_id: str) -> dict:
        """목록에 없으면 번호를 붙여 등록만 한다 (마지막 사용 시각은 바꾸지 않음) — 이 기능 이전에 만든 대화용."""
        return self.get(thread_id) or self.create(thread_id)

    def ensure(self, thread_id: str) -> dict:
        """질문이 들어온 대화가 목록에 없으면 등록하고, 있으면 마지막 사용 시각을 갱신한다."""
        if self.get(thread_id) is None:
            return self.create(thread_id)
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE threads SET updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?", (thread_id,))
        return self.get(thread_id)

    def rename(self, thread_id: str, title: str) -> dict:
        title = " ".join(title.split())[:MAX_TITLE]
        if not title:
            raise ValueError("대화 이름이 비어 있습니다.")
        with closing(self._connect()) as conn, conn:
            changed = conn.execute("UPDATE threads SET title = ? WHERE thread_id = ?", (title, thread_id)).rowcount
        if not changed:
            raise KeyError(thread_id)
        return self.get(thread_id)
