"""정기 브리핑 API (Step 10) — 주차 목록·상세·검토 완료, 생성 실행(관리자).

생성은 LLM을 여러 번 부르는 무거운 작업이라 관리자 토큰을 요구한다 (스케줄러·스크립트가 주로 만든다).
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from app.weekly import last_complete_weeks, run_weekly, week_of

from .admin import require_admin
from .schemas import WeeklyReview, WeeklyRun

router = APIRouter(prefix="/api/v1/weekly", tags=["weekly"])


def service(request: Request):
    return request.app.state.service


@router.get("", summary="정기 브리핑 주차 목록 (최근 주차 먼저)")
async def list_weekly(request: Request):
    return service(request).weekly.list()


@router.get("/{week_id}", summary="정기 브리핑 하나 (본문·근거·검토 상태)")
async def get_weekly(request: Request, week_id: str):
    record = service(request).weekly.get(week_id)
    if record is None:
        raise HTTPException(404, f"정기 브리핑이 없습니다: {week_id}")
    return record


@router.post("/{week_id}/review", summary="검토 완료 표시 (검토자·의견)")
async def review_weekly(request: Request, week_id: str, body: WeeklyReview):
    svc = service(request)
    record = svc.weekly.get(week_id)
    if record is None:
        raise HTTPException(404, f"정기 브리핑이 없습니다: {week_id}")
    if record["status"] == "failed":
        raise HTTPException(409, "생성에 실패한 브리핑은 검토할 수 없습니다")
    return svc.weekly.review(week_id, body.reviewer, body.comment)


@router.post("/run", summary="정기 브리핑 생성 (관리자) — 비우면 지난주", dependencies=[Depends(require_admin)])
async def run(request: Request, body: WeeklyRun):
    if body.start:
        start = date.fromisoformat(body.start)
        if start.weekday() != 0:
            raise HTTPException(422, "start는 월요일이어야 합니다")
        _, start, end = week_of(start)
    else:
        _, start, end = last_complete_weeks(date.today(), 1)[0]
    if start + timedelta(days=6) >= date.today():
        raise HTTPException(422, "끝나지 않은 주는 만들 수 없습니다")
    return await run_weekly(service(request), start, end)
