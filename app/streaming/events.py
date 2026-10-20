"""SSE로 내보내는 이벤트 스키마 (Pydantic).

화면은 event 이름으로 분기한다. 그래프 내부 이벤트(dict)는 converter가 이 스키마로 바꾼다.
스키마를 정해 두면 그래프 안쪽을 고쳐도 화면과의 약속은 깨지지 않는다.

    run_started → (progress | tool_call_start | tool_call_end | token)* → (approval_required | final) → done
    오류가 나면 error → done(status=failed)
"""
from typing import Any, Literal

from pydantic import BaseModel


class StreamEvent(BaseModel):
    event: str

    def payload(self) -> dict[str, Any]:
        return self.model_dump(exclude={"event"}, exclude_none=True)


class RunStarted(StreamEvent):
    event: Literal["run_started"] = "run_started"
    thread_id: str
    run_id: str


class Progress(StreamEvent):
    """노드·에이전트 진행 (node_start, route, plan, agent_start, agent_end, review, summary, impact,
    draft_start, guard, validation)."""
    event: Literal["progress"] = "progress"
    kind: str
    data: dict[str, Any]


class ToolCallStart(StreamEvent):
    event: Literal["tool_call_start"] = "tool_call_start"
    agent: str
    tool: str
    args: dict[str, Any]


class ToolCallEnd(StreamEvent):
    event: Literal["tool_call_end"] = "tool_call_end"
    agent: str
    tool: str
    ok: bool
    summary: str = ""
    latency_ms: int | None = None


class Token(StreamEvent):
    event: Literal["token"] = "token"
    delta: str
    attempt: int = 1                  # 재작성이면 2 → 화면이 새 초안으로 바꿔 그린다


class ApprovalRequired(StreamEvent):
    event: Literal["approval_required"] = "approval_required"
    thread_id: str
    impacted_products: list[dict[str, Any]]
    message: str
    draft: str = ""                          # 승인 대상 브리핑 (가드 통과본, 코드 블록 제거)
    citations: list[dict[str, Any]] = []     # 승인자가 근거를 보고 판단하도록 함께 보낸다


class Final(StreamEvent):
    event: Literal["final"] = "final"
    content: str
    citations: list[dict[str, Any]] = []     # 근거: 원문·번역·출처·기준일·검증 상태 (R56)
    usage: dict[str, Any] = {}


class Error(StreamEvent):
    event: Literal["error"] = "error"
    message: str


class Done(StreamEvent):
    event: Literal["done"] = "done"
    thread_id: str
    run_id: str
    status: Literal["completed", "awaiting_approval", "failed"]
