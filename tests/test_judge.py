"""Step 2 — 판정 규칙이 Step 1에서 심어 둔 정답대로 동작하는가 (docs/lab/step01-data.md 표)."""
import pytest

from app.core.config import get_settings
from app.domain.judge import judge_product
from app.repositories.reg_db import RegDB


@pytest.fixture(scope="module")
def db() -> RegDB:
    return RegDB(get_settings().reg_db_path)


def outcomes(db, product_id) -> dict[tuple[str, str], str]:
    """(규제 ID, CAS) → 결과"""
    j = judge_product(db, product_id)
    return {(f.reg_id, f.cas): f.outcome for f in j.findings}


def test_p001_svhc_and_restriction_exceeded(db):
    o = outcomes(db, "P001")
    assert o[("EU_REACH_SVHC", "117-81-7")] == "exceeds"      # DEHP 28%
    assert o[("EU_REACH_SVHC", "7439-92-1")] == "exceeds"     # 납 0.15%
    assert o[("EU_REACH_XVII", "7439-92-1")] == "exceeds"     # Entry 63


def test_p002_group_sum_exceeds_although_each_is_below(db):
    o = outcomes(db, "P002")
    assert o[("EU_REACH_SVHC", "117-81-7")] == "below"        # DEHP 0.08% 단독
    assert o[("EU_REACH_SVHC", "84-74-2")] == "below"         # DBP 0.03% 단독
    assert o[("EU_REACH_XVII", "117-81-7")] == "exceeds"      # Entry 51 합계 0.11%
    j = judge_product(db, "P002")
    assert "합계 0.11" in next(f.reason for f in j.findings if f.reg_id == "EU_REACH_XVII")


def test_p003_region_filter_and_impurity_review(db):
    j = judge_product(db, "P003")
    o = {(f.reg_id, f.cas): f.outcome for f in j.findings}
    assert o[("US_TSCA_S6", "79-01-6")] == "listed"           # TCE 주용제
    assert o[("US_TSCA_S6", "56-23-5")] == "review"           # 사염화탄소 공정 불순물
    assert not any(f.region == "EU" for f in j.findings)      # EU 미수출
    assert any("EU 미수출" in s["reason"] for s in j.skipped)


def test_p004_svhc_in_mixture_is_not_article_duty(db):
    j = judge_product(db, "P004")
    bpa = next(f for f in j.findings if f.reg_id == "EU_REACH_SVHC")
    assert bpa.outcome == "review" and "(제33조) 대상은 아님" in bpa.reason


def test_p006_same_substance_differs_by_regulation(db):
    o = outcomes(db, "P006")
    assert o[("EU_REACH_SVHC", "25637-99-4")] == "below"      # HBCDD 0.08% < 0.1%
    assert o[("JP_CSCL_C1", "25637-99-4")] == "review"        # 일본 1종: 함량 기준 없음 + 불순물


def test_p009_non_content_basis_needs_review(db):
    j = judge_product(db, "P009")
    f77 = next(f for f in j.findings if f.entry_ref == "Entry 77")
    assert f77.outcome == "review" and "방출" in f77.reason


def test_p010_no_regulated_substances(db):
    j = judge_product(db, "P010")
    assert j.findings == [] and j.skipped == []


def test_p012_domestic_rules_apply_regardless_of_export(db):
    j = judge_product(db, "P012")
    assert sum(f.outcome == "exceeds" and f.region == "KR" for f in j.findings) == 5
    assert all(s["region"] == "EU" for s in j.skipped)        # EU 미수출 → 제외


def test_unverified_data_is_flagged(db):
    assert judge_product(db, "P001").to_dict()["unverified_data"] is True


def test_unknown_product(db):
    with pytest.raises(ValueError):
        judge_product(db, "P999")
