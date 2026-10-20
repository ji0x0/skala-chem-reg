"""AgentService — API와 그래프 사이의 서비스 계층.

FastAPI lifespan에서 한 번 만들어 app.state에 두고 모든 요청이 공유한다 (싱글턴, 캡스톤 FastAPI 실습).
LLM·MCP 연결·체크포인터·컴파일된 그래프를 요청마다 다시 만들지 않는다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from typing import AsyncIterator

from langgraph.types import Command

from app.agents.baseline import build_baseline_graph
from app.agents.deps import AgentDeps
from app.agents.graph import build_graph
from app.core.config import DATA_DIR, Settings
from app.llm.base import AgentLLM
from app.llm.langchain_llm import build_llm
from app.repositories.product_db import ProductDB
from app.repositories.reg_db import RegDB
from app.streaming.converter import convert
from app.streaming.events import ApprovalRequired, Done, Error, RunStarted
from app.streaming.sse import format_sse
from app.tools.provider import ToolProvider

log = logging.getLogger(__name__)
FEEDBACK_LOG = DATA_DIR / "feedback.jsonl"


class AgentService:
    def __init__(self, settings: Settings, llm: AgentLLM, tools: ToolProvider, checkpointer,
                 pipeline: str = "v2"):
        self.settings = settings
        self.tools = tools
        self.pipeline = pipeline
        self.products = ProductDB(settings.app_db_path)
        self.products.seed_if_empty(settings.products_path)
        self.regdb = RegDB(settings.reg_db_path, self.products)
        self.deps = AgentDeps(settings, llm, tools)
        builder = build_baseline_graph if pipeline == "baseline" else build_graph
        self.graph = builder(self.deps, checkpointer=checkpointer)
        self.instance_id = id(self)
        self._locks: dict[str, asyncio.Lock] = {}

    @classmethod
    async def create(cls, settings: Settings, stack: AsyncExitStack, *, llm: AgentLLM | None = None,
                     tools: ToolProvider | None = None, checkpointer=None,
                     pipeline: str = "v2") -> "AgentService":
        if tools is None:
            from app.tools.provider import MCPToolProvider
            tools = MCPToolProvider(settings)
        await tools.start()                                 # 실서비스: MCP 프로세스 / 테스트: 메모리 연결
        stack.push_async_callback(tools.stop)               # 서버 종료 시 정리
        if checkpointer is None:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            checkpointer = await stack.enter_async_context(
                AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path)))
        service = cls(settings, llm or build_llm(settings), tools, checkpointer, pipeline)
        await service.deps.load_catalog()
        return service

    async def refresh_catalog(self) -> None:
        """제품이 추가·수정되면 에이전트의 제품 ID 목록을 다시 받는다."""
        await self.deps.load_catalog()

    # ── 대화 실행 (SSE) ─────────────────────────────────────────────────────
    def _config(self, thread_id: str, run_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "run_id": run_id,
                "run_name": f"chem-reg:{self.pipeline}", "tags": [self.pipeline, self.settings.llm_backend],
                "metadata": {"thread_id": thread_id}, "max_concurrency": 4}

    async def _run(self, graph_input, thread_id: str) -> AsyncIterator[str]:
        run_id = str(uuid.uuid4())
        lock = self._locks.setdefault(thread_id, asyncio.Lock())
        if lock.locked():                                   # 같은 대화에서 동시에 두 요청 방지
            yield format_sse(Error(message="이 대화에서 이미 처리 중인 요청이 있습니다."))
            yield format_sse(Done(thread_id=thread_id, run_id=run_id, status="failed"))
            return
        async with lock:
            yield format_sse(RunStarted(thread_id=thread_id, run_id=run_id))
            status = "completed"
            try:
                config = self._config(thread_id, run_id)
                async for mode, payload in self.graph.astream(graph_input, config, stream_mode=["custom", "updates"]):
                    for event in convert(mode, payload, thread_id):
                        if event.event == "approval_required":
                            status = "awaiting_approval"
                            event = await self._with_draft(event, config)
                        yield format_sse(event)
            except Exception as exc:                        # 스트림 중간 실패도 이벤트로 알리고 정상 종료
                log.exception("그래프 실행 실패", extra={"thread_id": thread_id, "run_id": run_id})
                status = "failed"
                yield format_sse(Error(message=f"처리 중 오류가 발생했습니다 ({type(exc).__name__})"))
            yield format_sse(Done(thread_id=thread_id, run_id=run_id, status=status))

    async def _with_draft(self, event: ApprovalRequired, config: dict) -> ApprovalRequired:
        """승인 대기에서는 final 이벤트가 없다 → 승인할 브리핑과 근거를 상태에서 꺼내 함께 보낸다.
        (토큰 스트림은 모델 원문이라 코드 블록 감싸기 등이 남아 있을 수 있다)"""
        values = (await self.graph.aget_state(config)).values or {}
        return event.model_copy(update={"draft": values.get("draft", ""), "citations": values.get("citations", [])})

    def stream_chat(self, message: str, thread_id: str) -> AsyncIterator[str]:
        return self._run({"question": message}, thread_id)

    def stream_approval(self, thread_id: str, approved: bool, comment: str, approver: str) -> AsyncIterator[str]:
        return self._run(Command(resume={"approved": approved, "comment": comment, "approver": approver}),
                         thread_id)

    async def thread_state(self, thread_id: str) -> dict:
        snap = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        values = snap.values or {}
        pending = None
        for task in snap.tasks or []:
            for intr in getattr(task, "interrupts", []) or []:
                pending = intr.value
        return {"thread_id": thread_id, "exists": bool(values), "awaiting_approval": pending is not None,
                "pending_approval": pending, "history": values.get("history", []),
                "draft": values.get("draft", "") if pending else "",
                "last": {k: values.get(k) for k in ("route", "plan", "impacts", "gaps", "judgement", "approval")},
                "citations": values.get("citations", [])}

    # ── 피드백 (LangSmith 연동은 Step 6) ─────────────────────────────────────
    async def feedback(self, run_id: str, score: int, comment: str) -> dict:
        record = {"run_id": run_id, "score": score, "comment": comment,
                  "ts": datetime.now(timezone.utc).isoformat()}
        FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"stored": True, "langsmith": False}
