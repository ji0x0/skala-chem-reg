"""규제 해당 여부 판정 — LLM이 아니라 코드가 정한다.

판정 순서 (제품 × 성분 × 등재 규제마다)
1. 적용 지역: 규제 지역이 제품 수출 지역에 있어야 한다. 국내(KR) 규제는 국내 생산 사업장이므로 항상 적용
2. 적용 형태: SVHC 정보 제공 의무(제33조)·XVII Entry 51은 성형품(article) 기준
3. 함량 기준: 등재 행의 기준 → 없으면 규제의 기본 기준과 비교. 합산 규칙(Entry 51)은 그룹 합계로 비교
4. 함량으로 판정할 수 없는 경우는 "확인 필요": 방출량 기준, 세부 기준이 데이터에 없음, 불순물에 대한 규칙 적용 여부

결과 5종
- exceeds   기준 초과 → 의무 발생
- listed    등재(함량 기준 없음) → 존재 자체로 해당
- review    확인 필요 → 담당자 판단이 필요한 이유를 함께 준다
- below     등재돼 있지만 기준 이하 → 의무 없음 (모니터링)
- (skipped) 지역·형태가 맞지 않아 적용 제외 → 왜 제외했는지 기록
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from app.repositories.reg_db import RegDB

Outcome = Literal["exceeds", "listed", "review", "below"]

DOMESTIC_REGION = "KR"

# 성형품에만 적용되는 규제·항목
ARTICLE_ONLY = {("EU_REACH_SVHC", ""), ("EU_REACH_XVII", "Entry 51")}

# 같은 항목 안의 여러 물질을 합산해 기준과 비교하는 규칙
GROUP_SUM = {("EU_REACH_XVII", "Entry 51")}

# 함량이 아닌 기준이라 함량으로 판정할 수 없는 항목
NON_CONTENT_BASIS = {("EU_REACH_XVII", "Entry 77"): "방출량 기준이라 함량으로 판정할 수 없음 — 방출 시험 필요"}

# 세부 함량 기준이 아직 데이터에 없어 판정을 보류하는 규제
THRESHOLD_PENDING = {"KR_CCA_HAZ": "세부 분류별 함량 기준이 데이터에 없음 — 고시 원문 확인 필요"}

SEVERITY = {"restriction": "high", "notification": "medium", "listing": "medium",
            "classification": "low"}


@dataclass
class Finding:
    reg_id: str
    region: str
    list_name: str
    entry_ref: str
    cas: str
    substance: str
    role: str
    wt_pct: float
    threshold_wt_pct: float | None
    outcome: Outcome
    severity: str
    reason: str
    obligation: str
    source_url: str
    data_status: str


@dataclass
class ProductJudgement:
    product_id: str
    product_name: str
    product_form: str
    export_regions: list[str]
    findings: list[Finding] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        counts = {o: 0 for o in ("exceeds", "listed", "review", "below")}
        for f in self.findings:
            counts[f.outcome] += 1
        return counts

    def to_dict(self) -> dict:
        return {**asdict(self), "summary": self.summary(),
                "unverified_data": any(f.data_status != "official" for f in self.findings)}


def _threshold(listing: dict) -> float | None:
    t = listing.get("threshold_wt_pct")
    return t if t is not None else listing.get("default_threshold_wt_pct")


def judge_product(db: RegDB, product_id: str) -> ProductJudgement:
    product = db.product(product_id)
    if product is None:
        raise ValueError(f"등록되지 않은 제품입니다: {product_id}")
    result = ProductJudgement(product["product_id"], product["product_name"],
                              product["product_form"], product["export_regions"])
    ingredients = {i["cas"]: i for i in product["ingredients"]}
    listings = db.listings_for_cas(list(ingredients))

    # 합산 규칙: (규제, 항목)별로 제품 안 해당 물질 함량 합계
    group_totals: dict[tuple[str, str], float] = {}
    for lst in listings:
        key = (lst["reg_id"], lst["entry_ref"] or "")
        if key in GROUP_SUM:
            group_totals[key] = group_totals.get(key, 0.0) + ingredients[lst["cas"]]["wt_pct"]

    for lst in listings:
        ing = ingredients[lst["cas"]]
        key = (lst["reg_id"], lst["entry_ref"] or "")
        base = dict(reg_id=lst["reg_id"], region=lst["region"], list_name=lst["list_name"],
                    entry_ref=lst["entry_ref"] or "", cas=lst["cas"],
                    substance=lst["name_ko"] or lst["name_en"], role=ing["role"],
                    wt_pct=ing["wt_pct"], source_url=lst["source_url"],
                    data_status=lst["status"])

        # 1. 적용 지역
        if lst["region"] != DOMESTIC_REGION and lst["region"] not in product["export_regions"]:
            result.skipped.append({**base, "reason": f"{lst['region']} 미수출 — 적용 제외"})
            continue
        # 2. 적용 형태
        if key in ARTICLE_ONLY and product["product_form"] != "article":
            if lst["reg_id"] == "EU_REACH_SVHC" and ing["wt_pct"] > 0.1:
                result.findings.append(Finding(
                    **base, threshold_wt_pct=0.1, outcome="review", severity="medium",
                    reason="혼합물이라 성형품 정보 제공 의무(제33조) 대상은 아님. "
                           "0.1 wt% 초과 SVHC 함유 혼합물의 SDS 제공 의무(제31조) 확인 필요",
                    obligation=""))
            else:
                result.skipped.append({**base, "reason": "성형품 기준 규제 — 혼합물이라 적용 제외"})
            continue

        threshold = _threshold(lst)
        severity = SEVERITY.get(lst["rule_type"], "medium")
        obligation = lst["condition_ko"] or lst["obligation_ko"]

        # 3. 함량으로 판정할 수 없는 경우
        if key in NON_CONTENT_BASIS:
            result.findings.append(Finding(**base, threshold_wt_pct=None, outcome="review",
                                           severity=severity, reason=NON_CONTENT_BASIS[key],
                                           obligation=obligation))
            continue
        if lst["reg_id"] in THRESHOLD_PENDING and threshold is None:
            result.findings.append(Finding(**base, threshold_wt_pct=None, outcome="review",
                                           severity=severity,
                                           reason=THRESHOLD_PENDING[lst["reg_id"]],
                                           obligation=lst["obligation_ko"]))
            continue

        # 4. 함량 기준 비교 (합산 규칙이면 그룹 합계로)
        if threshold is not None:
            amount = group_totals.get(key, ing["wt_pct"])
            label = f"{lst['entry_ref']} 대상 물질 합계 {amount:g} wt%" if key in GROUP_SUM \
                else f"함량 {amount:g} wt%"
            if amount > threshold:
                result.findings.append(Finding(**base, threshold_wt_pct=threshold, outcome="exceeds",
                                               severity=severity,
                                               reason=f"{label} > 기준 {threshold:g} wt%",
                                               obligation=lst["obligation_ko"]))
            else:
                result.findings.append(Finding(**base, threshold_wt_pct=threshold, outcome="below",
                                               severity="info",
                                               reason=f"{label} ≤ 기준 {threshold:g} wt%",
                                               obligation=""))
            continue

        # 5. 함량 기준이 없는 등재: 존재로 해당. 단 불순물이면 규칙 적용 여부 확인
        if "불순물" in ing["role"] and lst["rule_type"] in ("restriction", "notification"):
            result.findings.append(Finding(
                **base, threshold_wt_pct=None, outcome="review", severity=severity,
                reason=f"{ing['role']}로 {ing['wt_pct']:g} wt% 함유 — 불순물에도 규칙이 적용되는지 "
                       f"(면제·허용 한도) 원문 확인 필요", obligation=obligation))
            continue
        result.findings.append(Finding(**base, threshold_wt_pct=None, outcome="listed",
                                       severity=severity,
                                       reason="함량 기준 없이 등재 — 함유 자체로 해당",
                                       obligation=obligation))
    return result


def judge_portfolio(db: RegDB) -> list[ProductJudgement]:
    return [judge_product(db, p["product_id"]) for p in db.products()]
