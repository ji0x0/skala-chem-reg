"""AgentService — API와 그래프 사이의 서비스 계층.

FastAPI lifespan에서 한 번 만들어 app.state에 두고 모든 요청이 공유한다 (싱글턴, 캡스톤 FastAPI 실습).
LLM·MCP 연결·체크포인터·컴파일된 그래프를 요청마다 다시 만들지 않는다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from typing import AsyncIterator

from app.agents.baseline import build_baseline_graph
from app.agents.deps import AgentDeps
from app.agents.graph import build_graph
from app.core.config import Settings
from app.core.tracing import send_feedback
from app.llm.base import AgentLLM
from app.llm.langchain_llm import build_llm
from app.repositories.product_db import ProductDB
from app.repositories.reg_db import RegDB
from app.repositories.run_log import RunLog
from app.repositories.thread_db import ThreadDB
from app.streaming.converter import convert
from app.streaming.events import Done, Error, RunStarted
from app.streaming.sse import format_sse
from app.tools.provider import ToolProvider

log = logging.getLogger(__name__)


class AgentService:
    def __init__(self, settings: Settings, llm: AgentLLM, tools: ToolProvider, checkpointer,
                 pipeline: str = "v2"):
        self.settings = settings
        self.tools = tools
        self.pipeline = pipeline
        self.products = ProductDB(settings.app_db_path)
        self.products.seed_if_empty(settings.products_path)
        self.regdb = RegDB(settings.reg_db_path, self.products)
        self.threads = ThreadDB(settings.app_db_path)          # 대화 목록 (이름·번호). 내용은 체크포인터
        self.runs = RunLog(settings.app_db_path)               # 실행 기록 (관리자 화면: 처리량·비용·승인 이력)
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

    async def _run(self, graph_input, thread_id: str, record: dict) -> AsyncIterator[str]:
        run_id = str(uuid.uuid4())
        lock = self._locks.setdefault(thread_id, asyncio.Lock())
        if lock.locked():                                   # 같은 대화에서 동시에 두 요청 방지
            yield format_sse(Error(message="이 대화에서 이미 처리 중인 요청이 있습니다."))
            yield format_sse(Done(thread_id=thread_id, run_id=run_id, status="failed"))
            return
        async with lock:
            title = self.threads.ensure(thread_id)["title"]
            yield format_sse(RunStarted(thread_id=thread_id, run_id=run_id, title=title))
            status, usage, started = "completed", {}, time.perf_counter()
            config = self._config(thread_id, run_id)
            try:
                async for mode, payload in self.graph.astream(graph_input, config, stream_mode=["custom", "updates"]):
                    for event in convert(mode, payload, thread_id):
                        if event.event == "final":
                            usage = event.usage           # 한 턴의 사용량은 final에 한 번만 실린다
                        yield format_sse(event)
            except Exception as exc:                        # 스트림 중간 실패도 이벤트로 알리고 정상 종료
                log.exception("그래프 실행 실패", extra={"thread_id": thread_id, "run_id": run_id})
                status = "failed"
                yield format_sse(Error(message=f"처리 중 오류가 발생했습니다 ({type(exc).__name__})"))
            await self._record(run_id, thread_id, config, status, usage,
                               int((time.perf_counter() - started) * 1000), record)
            yield format_sse(Done(thread_id=thread_id, run_id=run_id, status=status))

    async def _record(self, run_id, thread_id, config, status, usage, latency_ms, record) -> None:
        """실행 기록 한 줄. 기록 실패가 사용자 응답을 막지 않게 한다."""
        try:
            values = (await self.graph.aget_state(config)).values or {}
            judgement = values.get("judgement") or {}
            impacted = list(dict.fromkeys(i["product_id"] for i in values.get("impacts") or []))   # 브리핑의 영향 제품
            self.runs.record(run_id=run_id, thread_id=thread_id, route=values.get("route"),
                             question=(values.get("question") or "")[:300], status=status, latency_ms=latency_ms,
                             tokens=usage.get("tokens", 0), usd=usage.get("usd", 0.0),
                             quality_passed=(int(judgement["passed"]) if "passed" in judgement   # 브리핑 질문에만
                                             and record["kind"] == "question" else None),
                             impacted=",".join(impacted) or None, **record)
        except Exception:
            log.exception("실행 기록 저장 실패", extra={"run_id": run_id})

    def stream_chat(self, message: str, thread_id: str) -> AsyncIterator[str]:
        return self._run({"question": message}, thread_id, {"kind": "question"})

    async def thread_state(self, thread_id: str) -> dict:
        snap = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        values = snap.values or {}
        title = self.threads.register(thread_id)["title"] if values else None
        return {"thread_id": thread_id, "title": title, "exists": bool(values), "history": values.get("history", []),
                "last": {k: values.get(k) for k in ("route", "plan", "impacts", "gaps", "judgement")},
                "citations": values.get("citations", [])}

    # ── 피드백: 로컬 기록 + LangSmith Run feedback (R41) ──────────────────────
    async def feedback(self, run_id: str, score: int, comment: str) -> dict:
        record = {"run_id": run_id, "score": score, "comment": comment,
                  "ts": datetime.now(timezone.utc).isoformat()}
        log_path = self.settings.app_db_path.parent / "feedback.jsonl"   # 앱 DB와 같은 곳 (배포 시 영구 볼륨)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        sent, reason = await asyncio.to_thread(send_feedback, run_id, score, comment)   # HTTP는 이벤트 루프 밖에서
        return {"stored": True, "langsmith": sent, **({"langsmith_reason": reason} if reason else {})}

    def feedback_records(self, limit: int = 100) -> list[dict]:
        """관리자 화면용: 최근 피드백 (실행 기록과 run_id로 이어 질문·경로를 붙인다)."""
        log_path = self.settings.app_db_path.parent / "feedback.jsonl"
        if not log_path.exists():
            return []
        lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
        records = [json.loads(line) for line in reversed(lines) if line.strip()]
        runs = {r["run_id"]: r for r in self.runs.recent(limit=1000)}
        for r in records:
            run = runs.get(r["run_id"], {})
            r.update(question=run.get("question"), route=run.get("route"), thread_id=run.get("thread_id"))
        return records
