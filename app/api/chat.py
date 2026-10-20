"""대화 API — 질문 스트리밍, 대화 상태, 승인, 피드백."""
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .schemas import ApprovalRequest, ChatRequest, FeedbackRequest, HealthResponse

router = APIRouter(prefix="/api/v1", tags=["chat"])
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}   # 프록시 버퍼링 끄기


def service(request: Request):
    return request.app.state.service


@router.get("/health", response_model=HealthResponse)
async def health(request: Request):
    svc = service(request)
    return HealthResponse(status="ok", instance_id=svc.instance_id, pipeline=svc.pipeline,
                          llm_backend=svc.settings.llm_backend, fast_model=svc.deps.llm.fast_name,
                          quality_model=svc.deps.llm.quality_name, tools=svc.tools.tool_names(),
                          products=len(svc.deps.product_ids), substances=len(svc.deps.substances))


@router.post("/chat/stream", summary="질문 → SSE 스트림")
async def chat_stream(request: Request, body: ChatRequest):
    thread_id = body.thread_id or f"t-{uuid.uuid4().hex[:12]}"
    return StreamingResponse(service(request).stream_chat(body.message, thread_id),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/threads/{thread_id}", summary="대화 상태·승인 대기 여부·근거")
async def thread_state(request: Request, thread_id: str):
    return await service(request).thread_state(thread_id)


@router.post("/threads/{thread_id}/approval", summary="승인·반려 → SSE로 이어서 실행")
async def approval(request: Request, thread_id: str, body: ApprovalRequest):
    svc = service(request)
    if not (await svc.thread_state(thread_id))["awaiting_approval"]:
        raise HTTPException(409, "승인 대기 중인 항목이 없습니다.")
    return StreamingResponse(svc.stream_approval(thread_id, body.approved, body.comment, body.approver),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/feedback", summary="👍/👎 피드백")
async def feedback(request: Request, body: FeedbackRequest):
    return await service(request).feedback(body.run_id, body.score, body.comment)
