"""노드·에이전트 공통 도구 호출 헬퍼.

- 도구 호출 전후로 진행 이벤트(tool_call_start / tool_call_end)를 보낸다 → 화면의 진행 패널
- 재시도 규칙(call_with_retry)을 적용한다
- 실패하면 예외를 던지지 않고 None을 돌려주며 errors에 기록한다 → 한 도구 실패가 요청 전체를 멈추지 않는다
"""
from __future__ import annotations

import logging
import time
from typing import Any

from langgraph.config import get_stream_writer

from app.tools.provider import ToolError, call_with_retry

from .deps import AgentDeps

log = logging.getLogger(__name__)


def _summary(result: Any) -> str:
    if isinstance(result, dict):
        if "documents" in result:
            return f"문서 {len(result['documents'])}건 ({result.get('source', '')})"
        if "summary" in result and isinstance(result["summary"], dict):
            return " · ".join(f"{k} {v}" for k, v in result["summary"].items())
        if "listings" in result:
            return f"등재 {len(result['listings'])}건"
        if "title" in result:
            return str(result["title"])[:80]
        if "source" in result:
            return str(result["source"])
    if isinstance(result, list):
        return f"{len(result)}건"
    return str(result)[:80]


async def call_tool(deps: AgentDeps, agent: str, name: str, args: dict,
                    errors: list[dict] | None = None) -> Any:
    writer = get_stream_writer()
    writer({"type": "tool_call_start", "agent": agent, "tool": name, "args": args})
    started = time.perf_counter()
    try:
        result, retries = await call_with_retry(deps.tools, name, args,
                                                timeout=deps.settings.tool_timeout_s)
    except ToolError as exc:
        ms = int((time.perf_counter() - started) * 1000)
        writer({"type": "tool_call_end", "agent": agent, "tool": name, "ok": False,
                "summary": str(exc)[:200], "latency_ms": ms})
        log.warning("도구 실패", extra={"agent": agent, "tool": name, "latency_ms": ms})
        if errors is not None:
            errors.append({"agent": agent, "tool": name, "error": str(exc)[:300]})
        return None
    writer({"type": "tool_call_end", "agent": agent, "tool": name, "ok": True,
            "summary": _summary(result), "retries": retries,
            "latency_ms": int((time.perf_counter() - started) * 1000)})
    return result
