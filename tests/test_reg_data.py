"""Step 1 — CAS 검증과 규제·제품 데이터 무결성."""
import sqlite3

import pytest

from app.core.config import Settings, get_settings
from app.domain.cas import find_cas_numbers, is_valid_cas
from app.repositories.product_db import ProductDB
from scripts.build_reg_db import build, read_csv, validate


@pytest.mark.parametrize("cas, ok", [
    ("71-43-2", True),        # 벤젠
    ("79-01-6", True),        # 트리클로로에틸렌
    ("7439-92-1", True),      # 납
    ("71-43-3", False),       # 체크 디지트 오류
    ("7143-2", False),        # 형식 오류
    ("abc", False),
])
def test_cas_check_digit(cas, ok):
    assert is_valid_cas(cas) is ok


def test_find_cas_in_text_skips_typos():
    text = "EPA proposes rules for TCE (CAS 79-01-6) and PCE 127-18-4; typo 79-01-7"
    assert find_cas_numbers(text) == ["79-01-6", "127-18-4"]


def test_source_data_is_valid():
    s = get_settings()
    errors = validate(read_csv(s.regulations_dir / "sources.csv"),
                      read_csv(s.regulations_dir / "listings.csv"),
                      read_csv(s.products_path))
    assert errors == []


def test_validation_catches_bad_rows():
    sources = [{"reg_id": "EU_REACH_SVHC", "region": "EU"}]
    listings = [{"reg_id": "NOPE", "cas": "71-43-3", "name_en": "x", "threshold_wt_pct": "0.1"}]
    products = [{"product_id": "P1", "cas": "71-43-2", "ingredient_name": "x", "role": "",
                 "export_regions": "EU;XX", "wt_pct": "90"}]
    errors = validate(sources, listings, products)
    assert any("CAS 오류" in e for e in errors)
    assert any("없는 규제 ID" in e for e in errors)
    assert any("수출 지역" in e for e in errors)
    assert any("함량 합계" in e for e in errors)
    assert any("역할(role) 누락" in e for e in errors)


def test_build_creates_db(tmp_path):
    settings = Settings(_env_file=None, reg_db_path=tmp_path / "reg.db")
    counts = build(settings)
    assert counts["regulations"] == 13 and counts["products"] == 12
    with sqlite3.connect(settings.reg_db_path) as conn:
        regions = {r[0] for r in conn.execute(
            "SELECT r.region FROM listings l JOIN regulations r USING(reg_id) WHERE l.cas='79-01-6'")}
    assert regions == {"KR", "US", "EU"}     # TCE는 국내·미국·EU 규제에 동시에 등재


def test_minor_components_are_modelled(tmp_path):
    """주성분만이 아니라 1 wt% 미만의 첨가제·잔류 단량체·불순물까지 들어 있어야 한다."""
    settings = Settings(_env_file=None, reg_db_path=tmp_path / "reg.db")
    build(settings)
    products = ProductDB(tmp_path / "app.db")
    products.seed_if_empty(settings.products_path)
    with sqlite3.connect(settings.reg_db_path) as conn:
        listed = {r[0] for r in conn.execute("SELECT DISTINCT cas FROM listings")}
    per_product = {p["product_id"]: p["ingredient_count"] for p in products.products()}
    minor_hits = {pid for pid in per_product
                  for i in products.product(pid)["ingredients"] if i["wt_pct"] < 1 and i["cas"] in listed}
    assert min(per_product.values()) >= 5
    assert len(minor_hits) >= 8        # 미량 성분이 규제 목록에 걸리는 제품이 여러 개
