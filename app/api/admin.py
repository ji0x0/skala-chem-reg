"""관리자 API (Step 7) — 규제대응 팀장용: 처리량·비용, 승인 이력, 담당자 피드백, 품질 평가, 규제 데이터 상태.

사용자 화면과 분리된 관리자 페이지(/admin/)가 쓴다. 모든 경로가 ADMIN_TOKEN을 요구한다.
- 토큰 설정이 비어 있으면 503 (관리자 API 꺼짐 — 기본 잠금)
- 요청의 Bearer 토큰이 틀리면 401
상세 추적(노드·도구 호출·프롬프트)은 LangSmith가 맡고, 여기서는 앱이 가진 기록만 모아 보여 준다.
"""
from __future__ import annotations

import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.core.tracing import langsmith_enabled, project_name


def service(request: Request):
    return request.app.state.service


def require_admin(request: Request, authorization: str | None = Header(default=None)) -> None:
    expected = service(request).settings.admin_token
    if not expected:
        raise HTTPException(503, "관리자 API가 꺼져 있습니다. .env에 ADMIN_TOKEN을 설정하세요.")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token.encode(), expected.encode()):      # 길이·내용 비교 시간을 일정하게
        raise HTTPException(401, "관리자 토큰이 올바르지 않습니다.")


router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/overview", summary="운영 요약: 처리량·비용·승인·품질, 규제 데이터, LangSmith")
async def overview(request: Request):
    svc = service(request)
    regs = svc.regdb.regulations()
    listings = [x for r in regs for x in svc.regdb.listings_for_reg(r["reg_id"])]
    verified = sorted({x["verified_on"] for x in listings if x.get("verified_on")})
    feedback = svc.feedback_records(limit=1000)
    return {
        "runs": svc.runs.summary(),
        "pending_approvals": len(_pending(svc)),
        "feedback": {"total": len(feedback), "up": sum(f["score"] > 0 for f in feedback),
                     "down": sum(f["score"] <= 0 for f in feedback)},
        "regulations": {"count": len(regs), "listings": len(listings),
                        "unverified": sum(x["status"] != "official" for x in listings),
                        "verified_on": verified[-1] if verified else None},
        "products": len(svc.products.products()),
        "pipeline": svc.pipeline, "llm_backend": svc.settings.llm_backend,
        "langsmith": {"enabled": langsmith_enabled(), "project": project_name(),
                      "url": "https://smith.langchain.com/"},
    }


@router.get("/runs", summary="최근 실행 기록 (질문·승인)")
async def runs(request: Request, kind: str | None = Query(default=None, pattern="^(question|approval)$"),
               limit: int = Query(default=50, ge=1, le=500)):
    return service(request).runs.recent(limit=limit, kind=kind)


def _pending(svc) -> list[dict]:
    """승인 요청 후 아직 승인·반려가 없는 대화 (같은 대화의 더 최근 승인 기록이 없으면 대기)."""
    pending, decided = {}, set()
    for r in svc.runs.recent(limit=1000):              # 최근 순
        if r["kind"] == "approval":
            decided.add(r["thread_id"])
        elif r["status"] == "awaiting_approval" and r["thread_id"] not in decided:
            pending.setdefault(r["thread_id"], r)
    return list(pending.values())


@router.get("/approvals", summary="승인 대기와 승인·반려 이력")
async def approvals(request: Request, limit: int = Query(default=100, ge=1, le=500)):
    svc = service(request)
    titles = {t["thread_id"]: t["title"] for t in svc.threads.list(limit=1000)}
    history = svc.runs.recent(limit=limit, kind="approval")
    requests = {r["thread_id"]: r for r in reversed(svc.runs.recent(limit=1000))
                if r["status"] == "awaiting_approval"}         # 대화별 마지막 승인 요청 (승인 대상 제품·질문)
    for r in history:
        req = requests.get(r["thread_id"], {})
        r.update(title=titles.get(r["thread_id"]), impacted=req.get("impacted"), question=req.get("question"))
    pending = [{**r, "title": titles.get(r["thread_id"])} for r in _pending(svc)]
    return {"pending": pending, "history": history}


@router.get("/feedback", summary="담당자 피드백 (👍/👎·코멘트, 질문과 연결)")
async def feedback(request: Request, limit: int = Query(default=100, ge=1, le=1000)):
    return service(request).feedback_records(limit=limit)


@router.get("/evaluations", summary="Before/After 평가 결과 (scripts/run_eval.py)")
async def evaluations(request: Request):
    folder = service(request).settings.experiments_dir
    files = sorted(folder.glob("*.json"), reverse=True) if folder.exists() else []
    items = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        items.append({"name": path.stem, "meta": data.get("meta", {}), "summary": data.get("summary", {})})
    return items
