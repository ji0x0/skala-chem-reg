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

from langgraph.types import Command

from app.agents.baseline import build_baseline_graph
from app.agents.deps import AgentDeps
from app.agents.graph import build_graph
from app.agents.update_graph import UpdateDeps, build_update_graph, initial_state
from app.core.config import Settings
from app.core.tracing import DELETED_KEY, send_feedback
from app.llm.base import AgentLLM
from app.llm.langchain_llm import build_llm
from app.regupdate.sources import WATCHED
from app.repositories.product_db import ProductDB
from app.repositories.reg_db import RegDB
from app.repositories.run_log import RunLog
from app.repositories.thread_db import ThreadDB
from app.repositories.update_db import UpdateDB
from app.repositories.weekly_db import WeeklyDB
from app.streaming.converter import convert
from app.streaming.events import Done, Error, RunStarted
from app.streaming.sse import format_sse
from app.tools.provider import ToolProvider
from scripts.build_reg_db import build as build_reg_db, bulk_overrides

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
        self.runs = RunLog(settings.app_db_path)               # 실행 기록 (관리자 화면: 처리량·비용·갱신 결정)
        self.weekly = WeeklyDB(settings.app_db_path)           # Step 10: 주차별 정기 브리핑
        self.weekly.seed_if_empty(settings.weekly_dir)
        self.deps = AgentDeps(settings, llm, tools)
        builder = build_baseline_graph if pipeline == "baseline" else build_graph
        self.graph = builder(self.deps, checkpointer=checkpointer)
        self.updates = UpdateDB(settings.app_db_path)          # Step 12: 규제 DB 갱신 후보
        self.update_graph = build_update_graph(UpdateDeps(settings, llm, self.products, self.updates),
                                               checkpointer=checkpointer)
        self._update_lock = asyncio.Lock()
        self.instance_id = id(self)
        self._locks: dict[str, asyncio.Lock] = {}

    @classmethod
    async def create(cls, settings: Settings, stack: AsyncExitStack, *, llm: AgentLLM | None = None,
                     tools: ToolProvider | None = None, checkpointer=None,
                     pipeline: str = "v2") -> "AgentService":
        if bulk_overrides(settings.reg_updates_dir):      # 승인해 반영한 갱신을 DB에 (Docker 이미지의 DB는 저장소 원본 기준)
            await asyncio.to_thread(build_reg_db, settings)
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
            if self.threads.is_deleted(thread_id):            # 삭제한 대화에는 이어 질문하지 않는다 (기록은 남아 있음)
                yield format_sse(Error(message="삭제된 대화입니다. 새 대화에서 질문해 주세요."))
                yield format_sse(Done(thread_id=thread_id, run_id=run_id, status="failed"))
                return
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

    async def delete_thread(self, thread_id: str) -> dict:
        """대화 목록에서 삭제 (숨김). 처리 중인 대화는 끝난 뒤에. 실행 기록·체크포인터·LangSmith 트레이스는 그대로.
        LangSmith에는 그 대화의 Run마다 피드백 thread_deleted=1을 남긴다 (실패해도 삭제는 유지)."""
        if self._locks.get(thread_id) and self._locks[thread_id].locked():
            raise ValueError("처리 중인 대화는 삭제할 수 없습니다. 답변이 끝난 뒤 다시 시도하세요.")
        already = self.threads.is_deleted(thread_id)
        record = self.threads.delete(thread_id)
        if not already:
            for run in self.runs.for_thread(thread_id):
                await asyncio.to_thread(send_feedback, run["run_id"], 1, "사용자가 대화를 목록에서 삭제", DELETED_KEY)
        return record

    async def thread_state(self, thread_id: str) -> dict:
        if self.threads.is_deleted(thread_id):                 # 삭제한 대화는 사용자 화면에서 다시 열지 않는다
            return {"thread_id": thread_id, "title": None, "exists": False, "deleted": True, "history": [],
                    "last": {}, "citations": []}
        snap = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        values = snap.values or {}
        title = self.threads.register(thread_id)["title"] if values else None
        return {"thread_id": thread_id, "title": title, "exists": bool(values),
                "history": self._with_runs(thread_id, values.get("history", [])),
                "last": {k: values.get(k) for k in ("route", "plan", "impacts", "gaps", "judgement")},
                "citations": values.get("citations", [])}

    # ── 규제 DB 갱신 제안 (Step 12) ─────────────────────────────────────────
    async def check_updates(self) -> list[dict]:
        """감시 목록마다 갱신 그래프를 돌린다. 새 버전이면 후보를 만들고 담당자 승인 대기에서 멈춘다."""
        results = []
        async with self._update_lock:                       # 확인은 한 번에 하나 (원본 수십 MB를 받는다)
            for w in WATCHED:
                thread_id = f"regupdate-{w.reg_id}-{uuid.uuid4().hex[:8]}"
                config = {"configurable": {"thread_id": thread_id}, "run_name": "chem-reg:regupdate",
                          "tags": ["regupdate"], "metadata": {"reg_id": w.reg_id}}
                started = time.perf_counter()
                try:
                    values = await self.update_graph.ainvoke(initial_state(w.reg_id, thread_id), config)
                except Exception as exc:
                    log.exception("DB 갱신 확인 실패", extra={"thread_id": thread_id})
                    values = {"outcome": "failed", "message": f"확인 실패 ({type(exc).__name__})"}
                outcome = values.get("outcome")
                self.runs.record(run_id=str(uuid.uuid4()), thread_id=thread_id, kind="update", route="regupdate",
                                 question=f"{w.label} 갱신 확인", latency_ms=int((time.perf_counter() - started) * 1000),
                                 status={"failed": "failed", "proposed": "awaiting_approval"}.get(outcome, "completed"),
                                 tokens=sum(u.get("tokens", 0) for u in values.get("usage") or []),
                                 impacted=",".join(p["product_id"] for p in values.get("products") or []) or None)
                results.append({"reg_id": w.reg_id, "label": w.label, "outcome": outcome, "message": values.get("message"),
                                "current": values.get("current"), "latest": values.get("latest"),
                                "update_id": values.get("update_id")})
        return results

    async def decide_update(self, update_id: int, approved: bool, approver: str, comment: str) -> dict:
        """담당자 결정으로 승인 대기 중인 갱신 그래프를 재개한다 (승인 → 반영·재판정 / 반려 → 그대로)."""
        record = self.updates.get(update_id)
        if record is None:
            raise KeyError(update_id)
        if record["status"] != "pending":
            raise ValueError(f"승인 대기 중인 갱신이 아닙니다 (상태: {record['status']})")
        config = {"configurable": {"thread_id": record["thread_id"]}}
        started = time.perf_counter()
        async with self._update_lock:
            values = await self.update_graph.ainvoke(
                Command(resume={"approved": approved, "approver": approver, "comment": comment}), config)
        if values.get("outcome") == "applied":
            await self.refresh_catalog()                    # 이름 매칭용 물질 목록도 새 DB 기준으로
        self.runs.record(run_id=str(uuid.uuid4()), thread_id=record["thread_id"], kind="approval", route="regupdate",
                         question=f"{record['label']} {record['new_version']} 반영",
                         status="failed" if values.get("outcome") == "failed" else "completed",
                         latency_ms=int((time.perf_counter() - started) * 1000), approved=int(approved),
                         approver=approver, comment=comment or None,
                         impacted=",".join(p["product_id"] for p in record.get("products") or []) or None)
        return self.updates.get(update_id)

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

    def _with_runs(self, thread_id: str, history: list[dict]) -> list[dict]:
        """다시 연 대화의 답변마다 Run ID와 남긴 피드백을 붙인다 → 지난 답변에도 담당자가 피드백할 수 있게.
        완료된 질문 실행 1건 = 답변 1개. 실행 기록이 생기기 전(Step 7 이전) 답변이 있을 수 있어 최근 것부터 맞춘다."""
        runs = [r for r in self.runs.for_thread(thread_id) if r["kind"] == "question" and r["status"] == "completed"]
        given = {r["run_id"]: {"score": r["score"], "comment": r.get("comment") or ""}
                 for r in reversed(self._feedback_lines())}            # 같은 답변에 여러 번이면 마지막 것
        answers = [i for i, m in enumerate(history) if m.get("role") == "assistant"]
        history = [dict(m) for m in history]
        for i, run in zip(reversed(answers), reversed(runs)):
            history[i].update(run_id=run["run_id"], feedback=given.get(run["run_id"]))
        return history

    def _feedback_lines(self, limit: int | None = None) -> list[dict]:
        """feedback.jsonl — 최근 것부터."""
        log_path = self.settings.app_db_path.parent / "feedback.jsonl"
        if not log_path.exists():
            return []
        lines = log_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in reversed(lines[-limit:] if limit else lines) if line.strip()]

    def feedback_records(self, limit: int = 100) -> list[dict]:
        """관리자 화면용: 최근 피드백 (실행 기록과 run_id로 이어 질문·경로를 붙인다)."""
        records = self._feedback_lines(limit)
        runs = {r["run_id"]: r for r in self.runs.recent(limit=1000)}
        for r in records:
            run = runs.get(r["run_id"], {})
            r.update(question=run.get("question"), route=run.get("route"), thread_id=run.get("thread_id"))
        return records
