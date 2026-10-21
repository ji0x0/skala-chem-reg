"""지금 목록과 새 버전 비교 — 모두 코드가 한다 (LLM은 결과를 설명만).

1. 행 비교: (CAS, 항목)마다 추가·삭제·내용 변경 (확인일·근거·출처 링크는 버전마다 바뀌므로 비교하지 않음)
2. 회사 성분: 바뀐 행 중 회사 제품 성분인 것
3. 제품 판정 변화: 후보 DB를 따로 만들어 전체 제품을 다시 판정하고 지금 판정과 비교 — 승인 전에 결과를 보여 준다
   (사람이 정리한 행(listings.csv)이 같은 물질을 덮고 있으면 행이 바뀌어도 판정은 그대로일 수 있다 → 판정으로 확인)
"""
from __future__ import annotations

from app.domain.judge import judge_portfolio
from app.repositories.reg_db import RegDB

COMPARED = ("name_en", "threshold_wt_pct", "condition_ko")
OUTCOME_KO = {"exceeds": "기준 초과", "listed": "등재 해당", "review": "확인 필요", "below": "기준 이하"}


def _key(row: dict) -> tuple[str, str]:
    return row["cas"], row["entry_ref"]


def _view(row: dict) -> dict:
    return {"cas": row["cas"], "entry_ref": row["entry_ref"], "name": (row.get("name_en") or "")[:120],
            "condition": (row.get("condition_ko") or "")[:240]}


def diff_rows(old: list[dict], new: list[dict]) -> dict:
    before, after = {_key(r): r for r in old}, {_key(r): r for r in new}
    changed = []
    for k in sorted(before.keys() & after.keys()):
        fields = {f: [before[k].get(f, ""), after[k].get(f, "")] for f in COMPARED
                  if (before[k].get(f) or "") != (after[k].get(f) or "")}
        if fields:
            changed.append({**_view(after[k]), "fields": fields})
    return {"added": [_view(after[k]) for k in sorted(after.keys() - before.keys())],
            "removed": [_view(before[k]) for k in sorted(before.keys() - after.keys())],
            "changed": changed}


def counts(diff: dict) -> dict:
    return {k: len(diff[k]) for k in ("added", "removed", "changed")}


def company_rows(diff: dict, ingredients: dict[str, str]) -> list[dict]:
    """바뀐 행 중 회사 제품 성분 (ingredients = {CAS: 성분명})."""
    return [{"change": change, **row, "ingredient": ingredients[row["cas"]]}
            for change in ("added", "removed", "changed") for row in diff[change] if row["cas"] in ingredients]


def _findings(db: RegDB, reg_ids: set[str]) -> dict[str, dict]:
    result = {}
    for j in judge_portfolio(db):
        result[j.product_id] = {"name": j.product_name, "findings": {
            (f.reg_id, f.entry_ref, f.cas): {"substance": f.substance, "outcome": f.outcome, "list_name": f.list_name}
            for f in j.findings if f.reg_id in reg_ids}}
    return result


def judge_changes(current: RegDB, candidate: RegDB, reg_ids: set[str], names: dict[str, str] | None = None) -> list[dict]:
    """감시 목록(reg_ids)에 대한 제품별 판정 변화: 사라진 판정 · 새 판정 · 결과가 바뀐 판정.
    names = {CAS: 제품 배합의 성분명} — 등재명(긴 영문 화학명) 대신 담당자가 아는 이름으로 보인다."""
    before, after = _findings(current, reg_ids), _findings(candidate, reg_ids)
    for side in (before, after):
        for product in side.values():
            for (_, _, cas), f in product["findings"].items():
                f["substance"] = (names or {}).get(cas) or f["substance"]
    changes = []
    for pid in sorted(before.keys() | after.keys()):
        old, new = before.get(pid, {}).get("findings", {}), after.get(pid, {}).get("findings", {})
        item = {"product_id": pid, "product_name": (after.get(pid) or before[pid])["name"],
                "removed": [{**old[k], "cas": k[2], "entry_ref": k[1]} for k in sorted(old.keys() - new.keys())],
                "added": [{**new[k], "cas": k[2], "entry_ref": k[1]} for k in sorted(new.keys() - old.keys())],
                "changed": [{**new[k], "cas": k[2], "entry_ref": k[1], "before": old[k]["outcome"]}
                            for k in sorted(old.keys() & new.keys()) if old[k]["outcome"] != new[k]["outcome"]]}
        if item["removed"] or item["added"] or item["changed"]:
            changes.append(item)
    return changes


def facts_text(label: str, current: str, latest: str, effective: str, today: str, diff: dict,
               company: list[dict], products: list[dict]) -> str:
    """승인 담당자에게 보여 줄 사실 (LLM 설명의 유일한 입력이자 코드 요약)."""
    c = counts(diff)
    timing = "적용 예정 판 (아직 적용 전)" if effective > today else "이미 적용 중인 판"
    lines = [f"목록: {label}", f"지금 DB 버전: {current} → 새 버전: {latest} (기준일 {effective}, {timing})",
             f"바뀐 행: 추가 {c['added']} · 삭제 {c['removed']} · 내용 변경 {c['changed']}"]
    names = {"added": "추가", "removed": "삭제", "changed": "변경"}
    lines += [f"회사 성분 해당: {names[r['change']]} — {r['ingredient']} ({r['cas']}, 항목 {r['entry_ref']})" for r in company]
    if not company:
        lines.append("회사 성분 해당: 없음")
    for p in products:
        parts = [f"{f['substance']} {OUTCOME_KO.get(f['outcome'], f['outcome'])} 판정 사라짐" for f in p["removed"]]
        parts += [f"{f['substance']} {OUTCOME_KO.get(f['outcome'], f['outcome'])} 판정 추가" for f in p["added"]]
        parts += [f"{f['substance']} {OUTCOME_KO.get(f['before'], f['before'])} → {OUTCOME_KO.get(f['outcome'], f['outcome'])}"
                  for f in p["changed"]]
        lines.append(f"제품 판정 변화: {p['product_id']} {p['product_name']} — {', '.join(parts)}")
    if not products:
        lines.append("제품 판정 변화: 없음")
    return "\n".join(lines)
