"""구조화 로그 — 로그 한 줄을 JSON 한 개로 남긴다.

사람이 읽는 문장 로그는 검색·집계가 어렵다. JSON으로 남기고 필드명을 통일해 두면
(thread_id, run_id, node, latency_ms …) 서버 로그와 LangSmith 트레이스를 같은 키로 찾아 연결할 수 있다.
"""
import json
import logging
import sys
from datetime import datetime, timezone

# 로그에 실을 수 있는 공통 필드. 이 이름만 쓰도록 약속한다.
CONTEXT_FIELDS = ("thread_id", "run_id", "node", "agent", "tool", "latency_ms", "event")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # logger.info("...", extra={"node": "plan"})로 넘긴 값은 record의 속성이 된다
        for key in CONTEXT_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """앱 시작 시 한 번 호출한다. 모든 로그를 JSON 한 줄로 표준 출력에 쓴다."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
