"""LangGraph astream 출력 → SSE 이벤트.

stream_mode=["custom", "updates"]로 실행하면 (mode, payload)가 나온다.
- custom: 노드가 get_stream_writer()로 보낸 진행 이벤트·토큰·최종 결과
- updates: 노드가 끝날 때의 상태 변화. interrupt가 걸리면 "__interrupt__" 키가 온다 → 승인 요청
"""
from __future__ import annotations

from typing import Any, Iterator

from .events import ApprovalRequired, Final, Progress, StreamEvent, Token, ToolCallEnd, ToolCallStart


def convert(mode: str, payload: Any, thread_id: str) -> Iterator[StreamEvent]:
    if mode == "custom":
        kind = payload.get("type")
        if kind == "token":
            yield Token(delta=payload["delta"], attempt=payload.get("attempt", 1))
        elif kind == "tool_call_start":
            yield ToolCallStart(agent=payload["agent"], tool=payload["tool"], args=payload["args"])
        elif kind == "tool_call_end":
            yield ToolCallEnd(agent=payload["agent"], tool=payload["tool"], ok=payload["ok"],
                              summary=payload.get("summary", ""), latency_ms=payload.get("latency_ms"))
        elif kind == "final":
            yield Final(content=payload["content"], citations=payload.get("citations", []),
                        usage=payload.get("usage", {}))
        else:
            yield Progress(kind=kind, data={k: v for k, v in payload.items() if k != "type"})
    elif mode == "updates" and "__interrupt__" in payload:
        for intr in payload["__interrupt__"]:
            value = getattr(intr, "value", intr) or {}
            yield ApprovalRequired(thread_id=thread_id, impacted_products=value.get("impacted_products", []),
                                   message=value.get("message", ""))
