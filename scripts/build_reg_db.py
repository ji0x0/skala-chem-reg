"""규제 CSV를 검증하고 SQLite DB(data/regulations.db)로 만든다. 제품 CSV는 검증만 한다.

Step 4부터 제품·성분은 data/app.db가 원본이다 (MCP 서버·API가 시작할 때 비어 있으면 products.csv로 채움).
그래서 이 스크립트는 규제 DB만 다시 만들고, 화면에서 추가한 제품은 건드리지 않는다.

    uv run python scripts/build_reg_db.py

CSV는 사람이 고치기 쉽고 Git에서 변경 이력을 보기 좋다. 서비스는 조회가 빠르고 조건 검색이
쉬운 SQLite를 쓴다. 이 스크립트가 둘 사이를 잇고, 그 과정에서 데이터 오류를 막는다.

검증 규칙 (하나라도 어기면 DB를 만들지 않고 종료)
1. 모든 CAS 번호는 형식과 체크 디지트가 맞아야 한다
2. listings의 reg_id는 sources에 있어야 한다
3. 기준 함량은 비었거나 0~100 사이 숫자여야 한다
4. 제품의 원료 함량 합계는 100 ± 0.5 wt%여야 한다
5. 수출 지역은 KR·US·EU·CN·JP 중 하나여야 한다
6. 모든 성분에 역할(role: 주원료·첨가제·잔류 단량체·불순물 등)이 있어야 한다
7. 등재 행의 상태는 official 또는 to_verify. official이면 확인일(verified_on)과 근거(evidence)가 있어야 한다

등재 데이터는 두 곳에서 온다.
- listings.csv: 사람이 조건·기준 함량·한글 설명을 정리한 행 (판정에 직접 쓰는 핵심 행)
- bulk/*.csv: 공식 원본의 전체 목록 (scripts/import_official_lists.py 또는 브라우저 확인으로 만든 행)
같은 (규제, CAS, 항목)이면 listings.csv 행이 우선한다. 한글 이름은 names_ko.csv로 CAS마다 채운다.

Step 12: 담당자가 승인한 DB 갱신은 저장소의 bulk 파일을 고치지 않고 갱신 폴더(REG_UPDATES_DIR/bulk/)에
같은 이름으로 둔다 → 그 파일이 bulk 파일을 대신한다. DB는 임시 파일로 만든 뒤 한 번에 바꿔 끼운다
(만드는 도중에 조회하는 서버·MCP 서버가 반쯤 만든 DB를 보지 않게).
"""
import csv
import os
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import Settings, get_settings  # noqa: E402
from app.domain.cas import is_valid_cas  # noqa: E402

REGIONS = {"KR", "US", "EU", "CN", "JP"}


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def to_float(value: str) -> float | None:
    return float(value) if value.strip() else None


def bulk_overrides(updates_dir: Path | None) -> dict[str, Path]:
    """승인해 반영한 갱신 파일 {bulk 파일 이름: 경로}."""
    folder = Path(updates_dir) / "bulk" if updates_dir else None
    return {p.name: p for p in sorted(folder.glob("*.csv"))} if folder and folder.is_dir() else {}


def load_listings(regs_dir: Path, overrides: dict[str, Path] | None = None) -> list[dict]:
    """listings.csv(정리한 행) + bulk/*.csv(공식 전체 목록)를 합친다. 정리한 행이 같은 규제·CAS·항목의 bulk 행보다 우선.
    overrides에 같은 이름의 파일이 있으면 그 파일을 bulk 대신 쓴다 (승인한 갱신 · 갱신 후보 미리보기)."""
    overrides = overrides or {}
    curated = [{**r, "origin": "listings.csv"} for r in read_csv(regs_dir / "listings.csv")]
    keys = {(r["reg_id"], r["cas"], r["entry_ref"]) for r in curated}
    keys_any_entry = {(r["reg_id"], r["cas"]) for r in curated if not r["entry_ref"]}
    bulk = []
    for path in sorted((regs_dir / "bulk").glob("*.csv")):
        source, origin = (overrides[path.name], f"갱신/{path.name}") if path.name in overrides else (path, f"bulk/{path.name}")
        for r in read_csv(source):
            if (r["reg_id"], r["cas"], r["entry_ref"]) in keys or (r["reg_id"], r["cas"]) in keys_any_entry:
                continue
            bulk.append({**r, "origin": origin})
    names = {r["cas"]: r["name_ko"] for r in read_csv(regs_dir / "names_ko.csv")}
    for r in curated + bulk:
        r["name_ko"] = r["name_ko"] or names.get(r["cas"], "")
    return curated + bulk


def validate(sources: list[dict], listings: list[dict], products: list[dict]) -> list[str]:
    errors = []
    reg_ids = {s["reg_id"] for s in sources}
    for s in sources:
        if s["region"] not in REGIONS:
            errors.append(f"sources: {s['reg_id']} 지역 코드 오류 '{s['region']}'")
    for i, row in enumerate(listings, start=2):
        where = f"{row.get('origin', 'listings.csv')} ({row['reg_id']} {row['cas']})"
        if not is_valid_cas(row["cas"]):
            errors.append(f"{where}: CAS 오류 '{row['cas']}' ({row['name_en']})")
        if row["reg_id"] not in reg_ids:
            errors.append(f"{where}: 없는 규제 ID '{row['reg_id']}'")
        t = to_float(row["threshold_wt_pct"])
        if t is not None and not 0 < t <= 100:
            errors.append(f"{where}: 기준 함량 범위 오류 {t}")
        if row["status"] not in ("official", "to_verify"):
            errors.append(f"{where}: 상태 값 오류 '{row['status']}'")
        if row["status"] == "official" and not (row.get("verified_on") and row.get("evidence")):
            errors.append(f"{where}: official인데 확인일·근거 없음")
        name = (row.get("name_en") or "").strip()
        if name and not re.search(r"[A-Za-z]", name):                # 규칙 8: "1", "2." 같은 잘린 이름 (번호 칸·쉼표 잘림)
            errors.append(f"{where}: 영문명 '{name}'에 글자가 없음 (원본 파싱 오류)")
    totals: dict[str, float] = defaultdict(float)
    for i, row in enumerate(products, start=2):
        if not row.get("role", "").strip():
            errors.append(f"products {i}행: 성분 역할(role) 누락 ({row['ingredient_name']})")
        if not is_valid_cas(row["cas"]):
            errors.append(f"products {i}행: CAS 오류 '{row['cas']}' ({row['ingredient_name']})")
        bad = set(row["export_regions"].split(";")) - REGIONS
        if bad:
            errors.append(f"products {i}행: 수출 지역 코드 오류 {bad}")
        totals[row["product_id"]] += float(row["wt_pct"])
    for pid, total in totals.items():
        if abs(total - 100) > 0.5:      # 반올림 오차만 허용
            errors.append(f"products: {pid} 함량 합계 {total:.2f} wt% (100 ± 0.5 아님)")
    return errors


def build(settings: Settings, out_path: Path | None = None, extra: dict[str, Path] | None = None) -> dict:
    """검증 → DB 생성. out_path를 주면 그 경로에(갱신 후보 미리보기), 아니면 settings.reg_db_path를 바꿔 끼운다.
    extra: 반영한 갱신 위에 더 얹을 bulk 파일 (갱신 후보)."""
    sources = read_csv(settings.regulations_dir / "sources.csv")
    listings = load_listings(settings.regulations_dir, bulk_overrides(settings.reg_updates_dir) | (extra or {}))
    products = read_csv(settings.products_path)
    glossary = read_csv(settings.glossary_path)

    errors = validate(sources, listings, products)
    if errors:
        raise ValueError("데이터 검증 실패:\n  " + "\n  ".join(errors))

    db = Path(out_path or settings.reg_db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_name(f".{db.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript("""
        CREATE TABLE regulations (reg_id TEXT PRIMARY KEY, region TEXT, law TEXT, list_name TEXT,
            authority TEXT, rule_type TEXT, applies_when TEXT, default_threshold_wt_pct REAL,
            obligation_ko TEXT, source_url TEXT, priority INTEGER, listing_note TEXT);
        CREATE TABLE listings (reg_id TEXT REFERENCES regulations(reg_id), cas TEXT, name_en TEXT,
            name_ko TEXT, entry_ref TEXT, threshold_wt_pct REAL, condition_ko TEXT, status TEXT,
            source_url TEXT, verified_on TEXT, evidence TEXT, origin TEXT);
        CREATE INDEX idx_listings_reg ON listings(reg_id);
        CREATE INDEX idx_listings_cas ON listings(cas);
        CREATE TABLE glossary (term TEXT, lang TEXT, ko TEXT, definition_ko TEXT);
    """)
    conn.executemany("INSERT INTO regulations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (s["reg_id"], s["region"], s["law"], s["list_name"], s["authority"], s["rule_type"],
         s["applies_when"], to_float(s["default_threshold_wt_pct"]), s["obligation_ko"],
         s["source_url"], int(s["priority"]), s.get("listing_note", "")) for s in sources])
    conn.executemany("INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (r["reg_id"], r["cas"], r["name_en"], r["name_ko"], r["entry_ref"],
         to_float(r["threshold_wt_pct"]), r["condition_ko"], r["status"], r["source_url"],
         r.get("verified_on", ""), r.get("evidence", ""), r["origin"])
        for r in listings])
    conn.executemany("INSERT INTO glossary VALUES (?,?,?,?)", [
        (g["term"], g["lang"], g["ko"], g["definition_ko"]) for g in glossary])
    conn.commit()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("regulations", "listings", "glossary")}
    counts["products"] = len({r["product_id"] for r in products})       # 검증한 초기 데이터 (app.db에 들어감)
    counts["ingredients"] = len(products)
    counts["substances"] = conn.execute("SELECT COUNT(DISTINCT cas) FROM listings").fetchone()[0]
    counts["to_verify"] = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE status='to_verify'").fetchone()[0]
    conn.close()
    os.replace(tmp, db)                                 # 한 번에 바꿔 끼움 (조회는 쿼리마다 파일을 새로 연다)
    counts["updates"] = sorted(bulk_overrides(settings.reg_updates_dir))
    return counts


def main() -> None:
    settings = get_settings()
    try:
        counts = build(settings)
    except ValueError as exc:
        print(exc)
        sys.exit(1)
    print(f"생성: {settings.reg_db_path.name}")
    print(f"  규제 {counts['regulations']}개 · 등재 {counts['listings']}행(물질 {counts['substances']}종) · "
          f"용어 {counts['glossary']}개")
    print(f"  제품 초기 데이터 검증 통과: {counts['products']}개(성분 {counts['ingredients']}행) "
          f"→ app.db가 비어 있으면 서버 시작 시 채워짐")
    print(f"  공식 원본 확인(official): {counts['listings'] - counts['to_verify']}행 · 확인 전(to_verify): {counts['to_verify']}행")
    if counts["updates"]:
        print(f"  승인해 반영한 갱신: {', '.join(counts['updates'])} ({settings.reg_updates_dir})")


if __name__ == "__main__":
    main()
