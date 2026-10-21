"""관리자 API (Step 7) — 규제대응 팀장용: 처리량·비용, 담당자 피드백, 품질 평가, 규제 데이터 상태,
규제 DB 갱신 후보의 승인·반려 (Step 12).

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

from .schemas import UpdateDecision


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


@router.get("/overview", summary="운영 요약: 처리량·비용·품질, 규제 데이터·갱신 후보, LangSmith")
async def overview(request: Request):
    svc = service(request)
    regs = svc.regdb.regulations()
    listings = [x for r in regs for x in svc.regdb.listings_for_reg(r["reg_id"])]
    verified = sorted({x["verified_on"] for x in listings if x.get("verified_on")})
    feedback = svc.feedback_records(limit=1000)
    return {
        "runs": svc.runs.summary(),
        "pending_approvals": svc.updates.pending_count(),      # 승인 대기 중인 규제 DB 갱신 후보
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


@router.get("/runs", summary="최근 실행 기록 (질문·정기 브리핑·갱신 확인·갱신 결정)")
async def runs(request: Request, kind: str | None = Query(default=None, pattern="^(question|weekly|update|approval)$"),
               limit: int = Query(default=50, ge=1, le=500)):
    return service(request).runs.recent(limit=limit, kind=kind)


# ── 규제 DB 갱신 후보 (Step 12) ─────────────────────────────────────────────
@router.get("/updates", summary="규제 DB 갱신 후보 목록 (승인 대기·반영·반려·변화 없음)")
async def updates(request: Request):
    return service(request).updates.list()


@router.post("/updates/check", summary="공식 원본의 새 버전을 지금 확인 (보통은 매주 정기 브리핑 뒤 자동)")
async def check_updates(request: Request):
    return await service(request).check_updates()


@router.get("/updates/{update_id}", summary="갱신 후보 상세: 바뀐 행 전체·회사 성분·제품 판정 변화")
async def update_detail(request: Request, update_id: int):
    record = service(request).updates.get(update_id)
    if record is None:
        raise HTTPException(404, "없는 갱신 후보입니다.")
    return record


@router.post("/updates/{update_id}/decision", summary="갱신 후보 승인(DB 반영·재판정) 또는 반려")
async def decide_update(request: Request, update_id: int, body: UpdateDecision):
    try:
        return await service(request).decide_update(update_id, body.approved, body.approver, body.comment)
    except KeyError:
        raise HTTPException(404, "없는 갱신 후보입니다.")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


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
