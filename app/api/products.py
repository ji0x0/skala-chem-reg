"""제품 관리 API (R54) — 제품 목록·상세, 추가·수정. 저장하면 바로 규제 판정 결과를 함께 돌려준다."""
from fastapi import APIRouter, HTTPException, Request

from app.domain.judge import judge_product
from app.domain.products import Product
from app.repositories.product_db import ProductValidationError

router = APIRouter(prefix="/api/v1/products", tags=["products"])


def service(request: Request):
    return request.app.state.service


def _with_judgement(svc, product_id: str) -> dict:
    return {"product": svc.products.product(product_id),
            "judgement": judge_product(svc.regdb, product_id).to_dict()}


@router.get("", summary="제품 목록 (판정 요약 포함)")
async def list_products(request: Request):
    svc = service(request)
    return [{**p, "export_regions": p["export_regions"].split(";"),
             "summary": judge_product(svc.regdb, p["product_id"]).summary()} for p in svc.products.products()]


@router.get("/{product_id}", summary="제품 상세 + 판정")
async def get_product(request: Request, product_id: str):
    svc = service(request)
    if svc.products.product(product_id) is None:
        raise HTTPException(404, f"등록되지 않은 제품입니다: {product_id}")
    return _with_judgement(svc, product_id)


async def _save(request: Request, product: Product, must_exist: bool) -> dict:
    svc = service(request)
    try:
        pid = svc.products.save(product, must_exist=must_exist)
    except ProductValidationError as exc:
        raise HTTPException(422, {"message": "제품 정보가 규칙에 맞지 않습니다.", "errors": exc.errors})
    except KeyError:
        raise HTTPException(404, f"등록되지 않은 제품입니다: {product.product_id}")
    await svc.refresh_catalog()                      # 에이전트도 새 제품 ID를 알게 한다
    return _with_judgement(svc, pid)


@router.post("", status_code=201, summary="제품 추가 (CAS·함량 합계 검증 → 저장 → 판정)")
async def create_product(request: Request, body: Product):
    return await _save(request, body, must_exist=False)


@router.put("/{product_id}", summary="제품 수정 (성분 전체 교체)")
async def update_product(request: Request, product_id: str, body: Product):
    return await _save(request, body.model_copy(update={"product_id": product_id}), must_exist=True)
