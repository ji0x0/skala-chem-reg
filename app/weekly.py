"""정기 브리핑 (Step 10) — 지난주(월~일) 국내외 규제 변경을 같은 브리핑 그래프로 정리해 주차별로 저장한다.

- 실행: 질문 + 고정 기간(period)을 그래프에 넣는다 → 미국 관보·국내 법제처를 그 기간으로만 검색, 넓히지 않음
- 스케줄러: 매주 월요일 지정 시각(한국 시간) 이후 지난주 브리핑이 없으면 만든다 (WEEKLY_SCHEDULE=true일 때만)
- 검토: 담당자가 읽고 "검토 완료" — 승인이 아니라 검토 기록 (설계 9절)
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def week_of(day: date) -> tuple[str, date, date]:
    """(ISO 주차 ID, 월요일, 일요일). 예: 2026-10-14 → ('2026-W42', 10-12, 10-18)"""
    year, week, _ = day.isocalendar()
    monday = day - timedelta(days=day.weekday())
    return f"{year}-W{week:02d}", monday, monday + timedelta(days=6)


def last_complete_weeks(today: date, n: int) -> list[tuple[str, date, date]]:
    """오늘 기준 끝난 주 n개 (최근 주부터)."""
    this_monday = today - timedelta(days=today.weekday())
    return [week_of(this_monday - timedelta(days=7 * (i + 1))) for i in range(n)]


def question_for(start: date, end: date) -> str:
    return f"{start.isoformat()}~{end.isoformat()} 국내외 화학물질 규제 변경 브리핑해줘"


async def run_weekly(service, start: date, end: date) -> dict:
    """한 주의 정기 브리핑을 만들어 저장한다. 실패해도 기록은 남긴다 (status=failed)."""
    week_id, _, _ = week_of(start)
    question = question_for(start, end)
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": f"weekly-{week_id}-{run_id[:8]}"}, "run_id": run_id,
              "run_name": "chem-reg:weekly", "tags": ["weekly", service.settings.llm_backend],
              "metadata": {"week_id": week_id}}
    started = time.perf_counter()
    record = {"week_id": week_id, "period_start": start.isoformat(), "period_end": end.isoformat(),
              "question": question, "run_id": run_id,
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        values = await service.graph.ainvoke(
            {"question": question, "period": {"start": start.isoformat(), "end": end.isoformat()}}, config)
        docs = {d["document_number"]: d for d in values.get("documents", [])}.values()
        usage = values.get("usage", [])
        record.update(status="pending_review", content=values.get("final", ""), citations=values.get("citations", []),
                      impacted=",".join(dict.fromkeys(i["product_id"] for i in values.get("impacts", []))) or None,
                      documents=sum(1 for d in docs if d.get("in_scope", True)),
                      references_count=sum(1 for d in docs if not d.get("in_scope", True)),
                      gaps=values.get("gaps", []), tokens=sum(u.get("tokens", 0) for u in usage))
    except Exception as exc:                                  # 한 주 실패가 스케줄러를 멈추지 않게
        log.exception("정기 브리핑 실패", extra={"week_id": week_id})
        record.update(status="failed", content=f"정기 브리핑 생성 실패 ({type(exc).__name__})", citations=[], gaps=[])
    record["latency_ms"] = int((time.perf_counter() - started) * 1000)
    service.runs.record(run_id=run_id, thread_id=config["configurable"]["thread_id"], kind="weekly", route="briefing",
                        question=question, status="failed" if record["status"] == "failed" else "completed",
                        latency_ms=record["latency_ms"], tokens=record.get("tokens", 0), impacted=record.get("impacted"))
    return service.weekly.save(record)


class WeeklyScheduler:
    """매주 월요일 hour시(한국 시간) 이후, 지난주 브리핑이 없으면 만든다. 30분마다 확인."""

    def __init__(self, service, hour: int = 9, interval_s: int = 1800):
        self.service, self.hour, self.interval_s = service, hour, interval_s
        self._task: asyncio.Task | None = None

    def due(self, now: datetime) -> tuple[str, date, date] | None:
        local = now.astimezone(KST)
        if local.weekday() != 0 or local.hour < self.hour:
            return None
        week = last_complete_weeks(local.date(), 1)[0]
        return None if self.service.weekly.get(week[0]) else week

    async def _loop(self) -> None:
        while True:
            week = self.due(datetime.now(timezone.utc))
            if week:
                log.info("정기 브리핑 생성", extra={"week_id": week[0]})
                await run_weekly(self.service, week[1], week[2])
            await asyncio.sleep(self.interval_s)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
