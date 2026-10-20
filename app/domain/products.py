"""제품·성분 모델과 검증 규칙 — 화면에서 제품을 추가·수정할 때와 초기 데이터(CSV)를 넣을 때 같은 규칙을 쓴다.

형식 검증(타입·범위·허용 값)은 Pydantic이, 업무 규칙은 validate_product()가 맡는다.
업무 규칙 (어기면 저장하지 않고 어느 성분이 왜 틀렸는지 돌려준다)
1. 성분이 1개 이상, 같은 CAS가 두 번 나오지 않는다
2. CAS 번호는 형식과 체크 디지트가 맞아야 한다
3. 함량 합계는 100 ± 0.5 wt% (반올림 오차만 허용)
4. 수출 지역이 1개 이상
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .cas import is_valid_cas

Region = Literal["KR", "US", "EU", "CN", "JP"]
SUM_TOLERANCE = 0.5


class Ingredient(BaseModel):
    cas: str = Field(min_length=5, max_length=12, examples=["79-01-6"])
    ingredient_name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=40, description="주원료·첨가제·잔류 단량체·불순물 등")
    wt_pct: float = Field(gt=0, le=100, description="함량 (wt%)")


class Product(BaseModel):
    product_id: str | None = Field(default=None, pattern=r"^P\d{3,}$", description="비우면 자동 발급")
    product_name: str = Field(min_length=1, max_length=120)
    product_form: Literal["article", "mixture"] = Field(description="article(성형품) / mixture(혼합물)")
    export_regions: list[Region] = Field(min_length=1)
    ingredients: list[Ingredient] = Field(min_length=1)


def validate_product(product: Product) -> list[str]:
    errors = []
    seen: set[str] = set()
    for i, ing in enumerate(product.ingredients, start=1):
        if not is_valid_cas(ing.cas):
            errors.append(f"{i}번 성분 '{ing.ingredient_name}': CAS 번호 오류 '{ing.cas}' (형식 또는 체크 디지트)")
        if ing.cas in seen:
            errors.append(f"{i}번 성분 '{ing.ingredient_name}': CAS {ing.cas}가 중복됨")
        seen.add(ing.cas)
    total = sum(i.wt_pct for i in product.ingredients)
    if abs(total - 100) > SUM_TOLERANCE:
        errors.append(f"함량 합계 {total:.4g} wt% — 100 ± {SUM_TOLERANCE} wt%여야 함")
    if len(set(product.export_regions)) != len(product.export_regions):
        errors.append("수출 지역이 중복됨")
    return errors


def products_from_rows(rows: list[dict]) -> list[Product]:
    """CSV 행(제품 정보가 성분마다 반복) → Product 목록."""
    grouped: dict[str, dict] = {}
    for r in rows:
        p = grouped.setdefault(r["product_id"], {
            "product_id": r["product_id"], "product_name": r["product_name"],
            "product_form": r["product_form"], "export_regions": r["export_regions"].split(";"),
            "ingredients": []})
        p["ingredients"].append({"cas": r["cas"], "ingredient_name": r["ingredient_name"],
                                 "role": r["role"], "wt_pct": float(r["wt_pct"])})
    return [Product(**p) for p in grouped.values()]
