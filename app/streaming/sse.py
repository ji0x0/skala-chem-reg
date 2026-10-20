"""SSE 형식 변환 — 이벤트 하나를 `event: 이름\\ndata: JSON\\n\\n` 문자열로.

빈 줄(\\n\\n)이 이벤트 하나의 끝이다. 화면은 이 경계로 잘라 읽는다.
"""
import json

from .events import StreamEvent


def format_sse(event: StreamEvent) -> str:
    data = json.dumps(event.payload(), ensure_ascii=False, default=str)
    return f"event: {event.event}\ndata: {data}\n\n"
