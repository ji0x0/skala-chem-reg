"""LangGraph astream 출력 → SSE 이벤트.

stream_mode=["custom", "updates"]로 실행하면 (mode, payload)가 나온다.
- custom: 노드가 get_stream_writer()로 보낸 진행 이벤트·토큰·최종 결과
- updates: 노드가 끝날 때의 상태 변화 (지금은 화면으로 보내지 않음)
"""
from __future__ import annotations

from typing import Any, Iterator

from .events import Final, Progress, StreamEvent, Token, ToolCallEnd, ToolCallStart


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
