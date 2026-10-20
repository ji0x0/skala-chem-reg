"""LangSmith 연동 (관리자 대시보드) — 키가 없으면 전부 건너뛴다.

트레이스는 LangChain·LangGraph가 환경변수(LANGSMITH_TRACING, LANGSMITH_API_KEY, LANGSMITH_PROJECT)를 보고
자동으로 보낸다. 여기서는 그 밖의 것만 다룬다.
- 👍/👎 → 해당 Run의 feedback (R41). SSE의 run_id = 그래프 실행 config의 run_id = LangSmith 루트 Run ID
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
FEEDBACK_KEY = "user_score"


def langsmith_enabled() -> bool:
    return bool(os.getenv("LANGSMITH_API_KEY")) and os.getenv("LANGSMITH_TRACING", "").lower() == "true"


def project_name() -> str:
    return os.getenv("LANGSMITH_PROJECT", "default")


def send_feedback(run_id: str, score: int, comment: str = "") -> tuple[bool, str]:
    """(성공 여부, 사유). 네트워크 호출이므로 서비스에서는 별도 스레드로 부른다."""
    if not langsmith_enabled():
        return False, "LangSmith 미설정 (LANGSMITH_TRACING=true, LANGSMITH_API_KEY 필요)"
    try:
        from langsmith import Client
        Client().create_feedback(run_id=run_id, key=FEEDBACK_KEY, score=score, comment=comment or None)
        return True, ""
    except Exception as exc:                 # 피드백 실패가 화면 동작을 막지 않게 (로컬 기록은 이미 됨)
        log.warning("LangSmith 피드백 전송 실패", extra={"run_id": run_id})
        return False, f"{type(exc).__name__}: {exc}"[:200]
