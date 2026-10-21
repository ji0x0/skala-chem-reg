"""Step 4 — 제품 저장소: 검증 규칙, 추가·수정, 초기 데이터, 자동 ID."""
import pytest

from app.core.config import get_settings
from app.domain.products import Product
from app.repositories.product_db import ProductDB, ProductValidationError

GOOD = {"product_name": "시험용 세정제", "product_form": "mixture", "export_regions": ["US", "KR"],
        "ingredients": [{"cas": "79-01-6", "ingredient_name": "TCE", "role": "주용제", "wt_pct": 90},
                        {"cas": "67-56-1", "ingredient_name": "Methanol", "role": "용제", "wt_pct": 10}]}


@pytest.fixture
def db(tmp_path):
    return ProductDB(tmp_path / "app.db")


def test_seed_only_once(db):
    assert db.seed_if_empty(get_settings().products_path) == 20
    assert db.seed_if_empty(get_settings().products_path) == 0          # 이미 있으면 다시 채우지 않음


def test_create_assigns_next_id_and_update(db):
    db.seed_if_empty(get_settings().products_path)
    pid = db.save(Product(**GOOD), must_exist=False)
    assert pid == "P021" and db.product(pid)["ingredients"][0]["cas"] == "79-01-6"
    changed = {**GOOD, "product_id": pid, "product_name": "시험용 세정제 v2"}
    db.save(Product(**changed), must_exist=True)
    assert db.product(pid)["product_name"] == "시험용 세정제 v2"
    assert [h["product_id"] for h in db.products_containing(["67-56-1"])] == ["P012", pid]


def test_business_rules_reject_bad_product(db):
    bad = {**GOOD, "ingredients": [{"cas": "79-01-7", "ingredient_name": "오타", "role": "주용제", "wt_pct": 90},
                                   {"cas": "79-01-6", "ingredient_name": "TCE", "role": "용제", "wt_pct": 5}]}
    with pytest.raises(ProductValidationError) as exc:
        db.save(Product(**bad))
    messages = " ".join(exc.value.errors)
    assert "CAS 번호 오류 '79-01-7'" in messages and "함량 합계 95" in messages
    assert db.products() == []                                          # 아무것도 저장되지 않음


def test_update_missing_product(db):
    with pytest.raises(KeyError):
        db.save(Product(**{**GOOD, "product_id": "P999"}), must_exist=True)
