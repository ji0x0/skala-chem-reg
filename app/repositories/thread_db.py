"""대화 목록 저장소 (data/app.db) — 대화 이름·번호·마지막 사용 시각.

대화 내용은 LangGraph 체크포인터(checkpoints.db)가 가진다. 여기서는 화면의 대화 목록에
필요한 정보만 둔다. 새 대화는 "001 규제 브리핑", "002 규제 브리핑" … 순서로 이름을 붙이고, 사용자가 바꿀 수 있다.

삭제는 목록에서 숨기는 것이다 (deleted_at). 사용자는 다시 열거나 이어 질문할 수 없지만, 실행 기록·피드백(관리자 페이지),
대화 내용(체크포인터), LangSmith 트레이스는 그대로 남는다 — 무엇을 답했는지 나중에 확인할 수 있게.
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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TEXT)""")
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(threads)")}
            if "deleted_at" not in columns:                    # 삭제 기능 이전에 만든 DB
                conn.execute("ALTER TABLE threads ADD COLUMN deleted_at TEXT")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, thread_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 100, include_deleted: bool = False) -> list[dict]:
        where = "" if include_deleted else "WHERE deleted_at IS NULL "
        with closing(self._connect()) as conn:
            rows = conn.execute(f"SELECT * FROM threads {where}ORDER BY updated_at DESC, seq DESC LIMIT ?", (limit,))
            return [dict(r) for r in rows.fetchall()]

    def is_deleted(self, thread_id: str) -> bool:
        row = self.get(thread_id)
        return bool(row and row["deleted_at"])

    def delete(self, thread_id: str) -> dict:
        """목록에서 숨긴다 (기록은 지우지 않음). 이미 삭제한 대화는 그대로 돌려준다."""
        if self.get(thread_id) is None:
            raise KeyError(thread_id)
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE threads SET deleted_at = CURRENT_TIMESTAMP WHERE thread_id = ? AND deleted_at IS NULL",
                         (thread_id,))
        return self.get(thread_id)

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
            changed = conn.execute("UPDATE threads SET title = ? WHERE thread_id = ? AND deleted_at IS NULL",
                                   (title, thread_id)).rowcount
        if not changed:
            raise KeyError(thread_id)
        return self.get(thread_id)
