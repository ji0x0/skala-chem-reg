"""FastAPI 진입점.

    uv run uvicorn app.main:app --port 8000

lifespan에서 AgentService(MCP 연결·체크포인터·그래프)를 프로세스당 한 번 만든다.
화면(:5173)과 API(:8000)는 출처가 달라 CORS 허용 출처를 명시한다 ("*" 금지).
"""
from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import ROOT_DIR, Settings, get_settings
from app.core.logging import setup_logging

load_dotenv(ROOT_DIR / ".env")     # OPENAI_API_KEY, LANGSMITH_* 는 라이브러리가 환경변수에서 직접 읽는다


def create_app(settings: Settings | None = None, **service_overrides) -> FastAPI:
    """service_overrides: 테스트에서 llm·tools·checkpointer를 바꿔 끼울 때 쓴다 (의존성 주입)."""
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.service import AgentService
        async with AsyncExitStack() as stack:
            app.state.service = await AgentService.create(
                settings, stack, pipeline=settings.pipeline_version, **service_overrides)
            yield                                    # 여기서 요청을 받는다. 종료 시 stack이 MCP·DB를 정리

    app = FastAPI(title="국내외 화학물질 규제 브리핑·영향 분석 에이전트", version="0.1.0", lifespan=lifespan,
                  description="LangGraph 멀티에이전트 + MCP + SSE. 법률 자문이 아니며 최종 판단은 담당자가 합니다.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list,
                       allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["Content-Type", "Authorization"])   # Authorization: 관리자 토큰

    from app.api import admin, chat, products, regulations
    for module in (chat, products, regulations, admin):
        app.include_router(module.router)
    return app


app = create_app()
