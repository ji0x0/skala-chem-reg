"""규제 목록 API (R55) — 규제 목록, 규제별 등재 물질, 물질 검색, 관보 원문 스냅샷."""
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/v1", tags=["regulations"])


def service(request: Request):
    return request.app.state.service


@router.get("/regulations", summary="규제 목록 (등재 물질 수·검증 상태 포함)")
async def list_regulations(request: Request):
    db = service(request).regdb
    result = []
    for reg in db.regulations():
        listings = db.listings_for_reg(reg["reg_id"])
        result.append({**reg, "listing_count": len(listings),
                       "unverified": sum(1 for x in listings if x["status"] != "official")})
    return result


@router.get("/regulations/{reg_id}", summary="규제 하나와 등재 물질")
async def get_regulation(request: Request, reg_id: str):
    db = service(request).regdb
    reg = db.regulation(reg_id)
    if reg is None:
        raise HTTPException(404, f"등록되지 않은 규제입니다: {reg_id}")
    return {**reg, "listings": db.listings_for_reg(reg_id)}


@router.get("/substances", summary="물질 검색 (CAS·이름) → 등재 규제와 함유 제품")
async def search_substances(request: Request, q: str = Query(min_length=1, max_length=60)):
    svc = service(request)
    substances = svc.regdb.search_substance(q)
    cas = [s["cas"] for s in substances]
    return {"query": q, "substances": substances, "listings": svc.regdb.listings_for_cas(cas),
            "products": svc.products.products_containing(cas)}
