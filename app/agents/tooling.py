"""노드·에이전트 공통 도구 호출 헬퍼.

- 도구 호출 전후로 진행 이벤트(tool_call_start / tool_call_end)를 보낸다 → 화면의 진행 패널
- 재시도 규칙(call_with_retry)을 적용한다
- 실패하면 예외를 던지지 않고 None을 돌려주며 errors에 기록한다 → 한 도구 실패가 요청 전체를 멈추지 않는다
- LangSmith 트레이스에 도구 Run으로 남긴다 (MCP 세션을 직접 부르므로 자동으로는 안 남음). 키가 없으면 그냥 통과
"""
from __future__ import annotations

import logging
import time
from typing import Any

from langgraph.config import get_stream_writer
from langsmith import traceable

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


async def _invoke(tools, name: str, args: dict, timeout: float):
    return await call_with_retry(tools, name, args, timeout=timeout)


def _traced(agent: str, name: str):
    """도구 Run: 입력은 인자만, 출력은 요약만 (관보 본문 같은 큰 결과를 트레이스에 통째로 올리지 않음)."""
    return traceable(run_type="tool", name=f"mcp:{name}", metadata={"agent": agent, "tool": name},
                     process_inputs=lambda i: dict(i.get("args") or {}),
                     process_outputs=lambda o: {"summary": _summary(o[0] if isinstance(o, tuple) else o),
                                                "retries": o[1] if isinstance(o, tuple) else None})(_invoke)


async def call_tool(deps: AgentDeps, agent: str, name: str, args: dict,
                    errors: list[dict] | None = None, writer=None) -> Any:
    """writer: 진행 이벤트를 보낼 통로. ReAct 에이전트(노드 안의 작은 그래프) 안에서 부를 때는 바깥 그래프의
    통로를 넘긴다 — 안에서 get_stream_writer()를 부르면 화면까지 가지 않는 안쪽 통로가 잡힌다."""
    writer = writer or get_stream_writer()
    writer({"type": "tool_call_start", "agent": agent, "tool": name, "args": args})
    started = time.perf_counter()
    try:
        result, retries = await _traced(agent, name)(deps.tools, name, args, deps.settings.tool_timeout_s)
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
