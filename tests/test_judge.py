"""Step 2 — 판정 규칙이 Step 1에서 심어 둔 정답대로 동작하는가 (docs/lab/step01-data.md 표)."""
import pytest

from app.core.config import get_settings
from app.domain.judge import judge_product
from app.repositories.product_db import ProductDB
from app.repositories.reg_db import RegDB


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> RegDB:
    s = get_settings()
    products = ProductDB(tmp_path_factory.mktemp("app") / "app.db")
    products.seed_if_empty(s.products_path)          # 초기 데이터(CSV) 그대로 → Step 1 정답표
    return RegDB(s.reg_db_path, products)


def outcomes(db, product_id) -> dict[tuple[str, str], str]:
    """(규제 ID, CAS) → 결과"""
    j = judge_product(db, product_id)
    return {(f.reg_id, f.cas, f.entry_ref): f.outcome for f in j.findings}


def test_p001_svhc_and_restriction_exceeded(db):
    o = outcomes(db, "P001")
    assert o[("EU_REACH_SVHC", "117-81-7", "")] == "exceeds"      # DEHP 28%
    assert o[("EU_REACH_SVHC", "7439-92-1", "")] == "exceeds"     # 납 0.15%
    assert o[("EU_REACH_XVII", "7439-92-1", "Entry 63")] == "exceeds"     # Entry 63 (제품 전체 대비로도 0.15 ≥ 0.1)


def test_p002_group_sum_exceeds_although_each_is_below(db):
    o = outcomes(db, "P002")
    assert o[("EU_REACH_SVHC", "117-81-7", "")] == "below"        # DEHP 0.08% 단독
    assert o[("EU_REACH_SVHC", "84-74-2", "")] == "below"         # DBP 0.03% 단독
    assert o[("EU_REACH_XVII", "117-81-7", "Entry 51")] == "exceeds"      # Entry 51 합계 0.11% ≥ 0.1%
    j = judge_product(db, "P002")
    assert "합계 0.11" in next(f.reason for f in j.findings if f.entry_ref == "Entry 51")


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
    assert o[("EU_REACH_SVHC", "25637-99-4", "")] == "below"      # HBCDD 0.08% < 0.1%
    assert o[("JP_CSCL_C1", "25637-99-4", "政令番号 30")] == "review"        # 일본 1종: 함량 기준 없음 + 불순물


def test_p009_non_content_basis_needs_review(db):
    j = judge_product(db, "P009")
    f77 = next(f for f in j.findings if f.entry_ref == "Entry 77")
    assert f77.outcome == "review" and "방출" in f77.reason


def test_p010_classification_and_domestic_managed_substance(db):
    """수성 아크릴 도료: 금지·제한은 없고, EU 조화된 분류 대상 성분 + 국내 관리대상 유해물질(이산화티타늄 1% 이상)."""
    j = judge_product(db, "P010")
    regs = {f.reg_id for f in j.findings if f.outcome != "below"}
    assert regs == {"EU_CLP_ANNEX_VI", "KR_OSHA_MANAGED"}          # 암모니아·MIT는 화관법 기준 함량 미만
    assert all("조화된 분류 대상" in f.reason for f in j.findings if f.reg_id == "EU_CLP_ANNEX_VI")
    tio2 = next(f for f in j.findings if f.reg_id == "KR_OSHA_MANAGED")
    assert tio2.cas == "13463-67-7" and tio2.outcome == "exceeds" and "≥ 기준 1 wt%" in tio2.reason


def test_threshold_equal_counts_for_xvii_but_not_svhc(db, tmp_path):
    """원문 표현: 부속서 XVII는 '0.1% 이상', SVHC 제33조는 '0.1% 초과'."""
    from app.domain.products import Product
    db._products.save(Product(product_name="경계값 시험 바닥재", product_form="article", export_regions=["EU"], ingredients=[
        {"cas": "9002-86-2", "ingredient_name": "PVC", "role": "주원료", "wt_pct": 99.9},
        {"cas": "117-81-7", "ingredient_name": "DEHP", "role": "가소제", "wt_pct": 0.1}]))
    pid = db._products.products()[-1]["product_id"]
    o = outcomes(db, pid)
    assert o[("EU_REACH_XVII", "117-81-7", "Entry 51")] == "exceeds"       # 0.1 ≥ 0.1
    assert o[("EU_REACH_SVHC", "117-81-7", "")] == "below"                 # 0.1 > 0.1 아님


def test_p012_domestic_rules_apply_regardless_of_export(db):
    j = judge_product(db, "P012")
    # 산안법 관리대상 1% 이상 5종(톨루엔·크실렌·메탄올·n-헥산·에틸벤젠) + 특별관리물질 벤젠 0.2% ≥ 0.1% (별표 12)
    # + 화관법 유해화학물질 벤젠(인체만성 0.1% 이상). 메탄올 9%는 화관법 인체급성 기준 10% 미만
    assert sum(f.outcome == "exceeds" and f.region == "KR" for f in j.findings) == 7
    methanol = next(f for f in j.findings if f.reg_id == "KR_CCA_HAZ" and f.cas == "67-56-1")
    assert methanol.outcome == "below" and "< 기준 10 wt%" in methanol.reason
    assert {s["region"] for s in j.skipped} == {"EU", "CN"}   # 미수출 지역(EU·중국) → 제외, 국내(KR)는 항상 적용


def test_all_regulation_data_is_officially_verified(db):
    """2026-10-20 공식 원본 대조 완료 — 모든 판정 근거에 확인일·근거가 있다 (docs/regulation-verification.md)."""
    for pid in ("P001", "P003", "P012"):
        j = judge_product(db, pid)
        assert j.to_dict()["unverified_data"] is False
        assert all(f.verified_on and f.evidence for f in j.findings)


def test_unknown_product(db):
    with pytest.raises(ValueError):
        judge_product(db, "P999")


def test_tsca_pcb_threshold_inclusive_and_cooling_tower_chromium_conditional(db):
    """40 CFR 761: PCB '50 ppm or greater' → 0.005%와 같아도 해당 / 749.68: 냉각탑 수처리제 용도만 → 확인 필요."""
    from app.domain.products import Product
    db._products.save(Product(product_name="시험용 수처리제", product_form="mixture", export_regions=["US"], ingredients=[
        {"cas": "7732-18-5", "ingredient_name": "Water", "role": "용매", "wt_pct": 94.995},
        {"cas": "10588-01-9", "ingredient_name": "Sodium dichromate", "role": "부식 억제제", "wt_pct": 5},
        {"cas": "1336-36-3", "ingredient_name": "PCBs", "role": "불순물(원료 유래)", "wt_pct": 0.005}]))
    pid = db._products.products()[-1]["product_id"]
    o = outcomes(db, pid)
    assert o[("US_TSCA_S6", "1336-36-3", "40 CFR 761")] == "exceeds"
    assert o[("US_TSCA_S6", "10588-01-9", "40 CFR 749.68")] == "review"
