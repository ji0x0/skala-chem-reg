"""대화 API — 질문 스트리밍, 대화 상태, 피드백."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .schemas import ChatRequest, FeedbackRequest, HealthResponse, ThreadRename

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
    thread_id = body.thread_id or service(request).threads.create()["thread_id"]   # 새 대화 → 001 규제 브리핑 …
    return StreamingResponse(service(request).stream_chat(body.message, thread_id),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/threads", summary="대화 목록 (최근 사용 순)")
async def list_threads(request: Request):
    return service(request).threads.list()


@router.post("/threads", status_code=201, summary="새 대화 (이름: 001 규제 브리핑, 002 규제 브리핑 …)")
async def create_thread(request: Request):
    return service(request).threads.create()


@router.patch("/threads/{thread_id}", summary="대화 이름 바꾸기")
async def rename_thread(request: Request, thread_id: str, body: ThreadRename):
    try:
        return service(request).threads.rename(thread_id, body.title)
    except KeyError:
        raise HTTPException(404, "없는 대화입니다.")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.delete("/threads/{thread_id}", status_code=204,
               summary="대화 삭제 — 목록에서 숨김 (실행 기록·LangSmith 트레이스는 남음)")
async def delete_thread(request: Request, thread_id: str):
    try:
        await service(request).delete_thread(thread_id)
    except KeyError:
        raise HTTPException(404, "없는 대화입니다.")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.get("/threads/{thread_id}", summary="대화 상태·근거")
async def thread_state(request: Request, thread_id: str):
    return await service(request).thread_state(thread_id)


@router.post("/feedback", summary="👍/👎 피드백")
async def feedback(request: Request, body: FeedbackRequest):
    return await service(request).feedback(body.run_id, body.score, body.comment)
