"""공식 원본에서 규제 등재 목록 전체를 가져와 data/regulations/bulk/*.csv로 만든다.

    uv run python scripts/import_official_lists.py eu        # EU CLP 부속서 VI · REACH 부속서 XVII (EUR-Lex 통합본)
    uv run --with openpyxl python scripts/import_official_lists.py kr-cca   # 국내 인체등유해성물질(화관법 유해화학물질)

- EUR-Lex 웹사이트는 자동 요청을 막지만, 같은 공식 문서를 EU 출판국 Cellar API가 기계용으로 제공한다
  (https://publications.europa.eu/resource/celex/<CELEX> , Accept: application/xhtml+xml)
- 원본 파일(수십 MB)은 data/regulations/raw/ 에 캐시하고 Git에 올리지 않는다. 결과 CSV만 커밋한다
- 결과 행은 모두 status=official, verified_on=가져온 날, evidence=통합본 버전·위치
- 사람이 조건·기준을 정리한 행(listings.csv)이 같은 (규제, CAS)의 bulk 행보다 우선한다 (build_reg_db.py)

ECHA SVHC 후보 목록 등 웹 화면으로만 제공되는 목록은 브라우저로 확인해 bulk CSV로 저장했다 (docs/regulation-verification.md).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.domain.cas import is_valid_cas  # noqa: E402

REG_DIR = ROOT / "data" / "regulations"
BULK_DIR = REG_DIR / "bulk"
RAW_DIR = REG_DIR / "raw"
HEADER = ["reg_id", "cas", "name_en", "name_ko", "entry_ref", "threshold_wt_pct", "condition_ko", "status",
          "source_url", "verified_on", "evidence"]
CAS_RE = re.compile(r"(?<![\d-])\d{2,7}-\d{2}-\d(?![\d-])")

# 현재(2026-10-20) 시행 중인 최신 통합본
CLP_CELEX = "02008R1272-20260701"
REACH_CELEX = "02006R1907-20260622"
EURLEX = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{}"


def fetch_cellar(celex: str) -> str:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{celex}.xhtml"
    if not cache.exists():
        req = urllib.request.Request(f"https://publications.europa.eu/resource/celex/{celex}",
                                     headers={"Accept": "application/xhtml+xml", "Accept-Language": "eng"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            cache.write_bytes(resp.read())
    return cache.read_text(encoding="utf-8")


def text(fragment: str) -> str:
    t = re.sub(r"<[^>]+>", " ", fragment)
    t = t.replace("►", " ").replace("◄", " ").replace("▼", " ")
    t = re.sub(r"\b[MBAC]\d{1,3}\b", " ", t)               # 개정 표시(►M18 ◄)의 잔여 기호
    return re.sub(r"\s+", " ", t).strip()


def cells(row: str) -> list[str]:
    return [text(c) for c in re.findall(r"<td\b.*?</td>", row, flags=re.S)]


def cas_numbers(value: str) -> list[str]:
    return [c for c in dict.fromkeys(CAS_RE.findall(value)) if is_valid_cas(c)]


HAZARD_START = re.compile(r"\s(?=(?:Unst\. |Expl\.|Flam\.|Aerosol|Ox\.|Press\.|Self-|Pyr\.|Met\.|Water-|Org\.|Acute Tox|Skin|Eye|"
                          r"Resp\.|Carc\.|Muta\.|Repr\.|Lact\.|STOT|Asp\.|Aquatic (?:Acute|Chronic)|Ozone|ED HH|ED ENV|PBT|vPvB|PMT|vPvM|Desen))")


def classification(raw: str) -> str:
    """'Flam. Liq. 2 Carc. 1 a Muta. 1B' → 'Flam. Liq. 2, Carc. 1A, Muta. 1B'"""
    raw = re.sub(r"(\d) ([AB])\b", r"\1\2", raw.replace(" a ", "A ").replace(" b ", "B "))
    raw = re.sub(r"(\d) a$", r"\1A", raw)
    return ", ".join(p.strip() for p in HAZARD_START.split(raw) if p.strip())


def write(name: str, rows: list[dict]) -> Path:
    BULK_DIR.mkdir(parents=True, exist_ok=True)
    path = BULK_DIR / f"{name}.csv"
    seen, unique = set(), []
    for r in rows:                                      # 같은 규제·CAS·항목은 한 행 (한 물질이 여러 항목에 걸릴 수 있음)
        key = (r["reg_id"], r["cas"], r["entry_ref"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(unique)
    return path


# ── EU CLP 부속서 VI 표 3 ────────────────────────────────────────────────────
def import_clp(today: str) -> list[dict]:
    t = fetch_cellar(CLP_CELEX)
    tables = re.findall(r"<table\b.*?</table>", t, flags=re.S)
    table3 = max(tables, key=lambda x: len(re.findall(r">\s*\d{3}-\d{3}-\d{2}-[\dX]\s*<", x)))
    rows = []
    for tr in re.findall(r"<tr\b.*?</tr>", table3, flags=re.S):
        c = cells(tr)
        if len(c) < 8 or not re.fullmatch(r"\d{3}-\d{3}-\d{2}-[\dX]", c[0]):
            continue
        index_no, name, cas_field, hazard = c[0], c[1], c[3], c[4]
        scl = c[9] if len(c) > 9 else ""
        cond = classification(hazard)
        if scl:
            cond += f" (특정 농도 한계 등: {scl[:120]})"
        for cas in cas_numbers(cas_field):
            rows.append({"reg_id": "EU_CLP_ANNEX_VI", "cas": cas, "name_en": name[:200], "name_ko": "",
                         "entry_ref": index_no, "threshold_wt_pct": "", "condition_ko": cond[:400],
                         "status": "official", "source_url": EURLEX.format(CLP_CELEX), "verified_on": today,
                         "evidence": f"CLP 통합본 {CLP_CELEX} 부속서 VI 표 3, 색인번호 {index_no}"})
    return rows


# ── EU REACH 부속서 XVII (항목 + 부록 1~6·8·9·12·13) ──────────────────────────
APPENDIX_ENTRY = {"1": ("Entry 28", "발암성 1A"), "2": ("Entry 28", "발암성 1B"), "3": ("Entry 29", "생식세포 변이원성 1A"),
                  "4": ("Entry 29", "생식세포 변이원성 1B"), "5": ("Entry 30", "생식독성 1A"),
                  "6": ("Entry 30", "생식독성 1B"), "8": ("Entry 43", "아조 염료 유래 방향족 아민"),
                  "9": ("Entry 43", "아조 염료"), "12": ("Entry 72", "의류·섬유 제품 내 CMR 물질"),
                  "13": ("Entry 75", "문신·영구 화장용 잉크")}
APPENDIX_NOTE = {"Entry 28": "일반 소비자 대상 물질·혼합물에 분류 기준 농도 이상 공급 금지 (산업·전문가용 등 예외 — 원문 확인)",
                 "Entry 29": "일반 소비자 대상 물질·혼합물에 분류 기준 농도 이상 공급 금지 (산업·전문가용 등 예외 — 원문 확인)",
                 "Entry 30": "일반 소비자 대상 물질·혼합물에 분류 기준 농도 이상 공급 금지 (산업·전문가용 등 예외 — 원문 확인)",
                 "Entry 43": "피부·구강에 장시간 닿는 섬유·가죽 제품 등에서 제한 (아민 30 mg/kg 기준 — 원문 확인)",
                 "Entry 72": "의류·섬유·신발 등에서 부록 12의 물질별 최대 농도 초과 금지 — 원문 확인",
                 "Entry 75": "문신·영구 화장용 혼합물에서 물질별 농도 제한 — 원문 확인"}


def import_xvii(today: str) -> list[dict]:
    t = fetch_cellar(REACH_CELEX)
    start = [m.start() for m in re.finditer(r"ANNEX XVII", t)][-1]
    app1 = start + re.search(r"Appendix 1\s*</p>", t[start:]).start()   # 본문의 "listed in Appendix 1"이 아니라 부록 제목
    rows = []
    # 항목 표: 1열 "번호. 물질명 CAS …", 2열 제한 조건
    for tr in re.findall(r"<tr\b.*?</tr>", t[start:app1], flags=re.S):
        c = cells(tr)
        if len(c) != 2:
            continue
        m = re.match(r"^(\d{1,3})\.\s", c[0])
        if not m:
            continue
        entry = f"Entry {m.group(1)}"
        name = re.sub(r"\s*CAS No.*$", "", c[0][len(m.group(0)):])[:200]
        for cas in cas_numbers(c[0]):
            rows.append(_xvii_row(cas, name, entry, f"부속서 XVII {entry} 제한 대상 — 제한 조건(용도·농도)은 원문 확인",
                                  today, f"REACH 통합본 {REACH_CELEX} 부속서 XVII {entry}"))
    # 부록: 각 부록 제목 뒤의 표에서 CAS 열
    marks = [(m.group(1), m.start()) for m in re.finditer(r"Appendix (\d{1,2})\s*</p>", t[app1 - 50:])]
    marks = [(n, app1 - 50 + p) for n, p in marks]
    for i, (num, pos) in enumerate(marks):
        if num not in APPENDIX_ENTRY:
            continue
        end = marks[i + 1][1] if i + 1 < len(marks) else len(t)
        entry, label = APPENDIX_ENTRY[num]
        for tr in re.findall(r"<tr\b.*?</tr>", t[pos:end], flags=re.S):
            c = cells(tr)
            found = [cas for cell in c[1:] for cas in cas_numbers(cell)]
            if not c or not found:
                continue
            for cas in found:
                rows.append(_xvii_row(cas, c[0][:200], entry, f"{label} — {APPENDIX_NOTE[entry]}", today,
                                      f"REACH 통합본 {REACH_CELEX} 부속서 XVII 부록 {num} ({entry})"))
    return rows


def _xvii_row(cas, name, entry, cond, today, evidence) -> dict:
    return {"reg_id": "EU_REACH_XVII", "cas": cas, "name_en": name, "name_ko": "", "entry_ref": entry,
            "threshold_wt_pct": "", "condition_ko": cond, "status": "official",
            "source_url": EURLEX.format(REACH_CELEX), "verified_on": today, "evidence": evidence}


# ── 국내 인체급성·인체만성·생태유해성물질 (화관법 유해화학물질) ─────────────────
KR_CCA_NOTICE = "화학물질안전원고시 제2026-5호 (2026-03-27, 시행 2026-07-01)"
KR_CCA_URL = "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000276378"
KR_CCA_XLSX = "https://www.law.go.kr/LSW/flDownload.do?flSeq=162837753"     # 첨부 '(별표) 인체등유해성물질 목록(전체).xlsx'


def _pct(value) -> float | None:
    """'25', '0.1', '1\n(as HCHO)' → 숫자. '-'·빈칸 → None"""
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(value)) if value is not None else None
    return float(m.group(1)) if m else None


def import_kr_cca(today: str) -> list[dict]:
    import openpyxl                                  # 이 명령에서만 필요: uv run --with openpyxl …
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / "kr_cca_hazardous_2026-5.xlsx"
    if not path.exists():
        req = urllib.request.Request(KR_CCA_XLSX, headers={"User-Agent": "Mozilla/5.0", "Referer": KR_CCA_URL})
        with urllib.request.urlopen(req, timeout=120) as resp:
            path.write_bytes(resp.read())
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    rows = []
    last_no, last_sub, last_limits = None, None, ({}, "")
    for row in ws.iter_rows(min_row=5, values_only=True):
        no, sub, ko, en, cas_field, acute, chronic, eco, kinds = (list(row) + [None] * 10)[:9]
        if not (ko or en):
            continue
        # 그룹 물질: 하위 행은 고유번호·함량 칸이 비어 있고 CAS가 영문명 괄호에 있다 → 위 행에서 이어받는다
        no = no or last_no
        sub = sub if no == last_no and sub else (sub or (last_sub if no == last_no else None))
        cas_found = cas_numbers(str(cas_field or "")) or cas_numbers(str(en or ""))
        if not no or not cas_found:
            last_no, last_sub = no, sub
            continue
        limits = {"인체급성": _pct(acute), "인체만성": _pct(chronic), "생태": _pct(eco)}
        if not any(v is not None for v in limits.values()) and not kinds:
            limits, kinds = last_limits
        else:
            last_limits = (limits, kinds)
        last_no, last_sub = no, sub
        given = {k: v for k, v in limits.items() if v is not None}
        detail = " · ".join(f"{k} {v:g}%" for k, v in given.items()) or "함량 기준 원문 확인"
        ref = f"{no}-{sub}" if sub else f"{no}"
        for cas in cas_found:
            rows.append({"reg_id": "KR_CCA_HAZ", "cas": cas, "name_en": (en or "")[:200], "name_ko": (ko or "")[:120],
                         "entry_ref": ref, "threshold_wt_pct": f"{min(given.values()):g}" if given else "",
                         "condition_ko": f"인체등유해성물질({kinds or ''}) — 혼합물 중 함량 {detail} 이상이면 유해화학물질: "
                                         f"영업허가·취급시설 기준·표시·장외영향평가 등",
                         "status": "official", "source_url": KR_CCA_URL, "verified_on": today,
                         "evidence": f"{KR_CCA_NOTICE} 별표 첨부 '인체등유해성물질 목록(전체)' 고유번호 {ref}"})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", choices=["eu", "kr-cca"])
    args = parser.parse_args()
    today = date.today().isoformat()
    if args.source == "kr-cca":
        path = write("kr_cca_hazardous", import_kr_cca(today))
        print(f"{path.relative_to(ROOT)}: {sum(1 for _ in open(path)) - 1}행")
    if args.source == "eu":
        for name, rows in (("eu_clp_annex_vi", import_clp(today)), ("eu_reach_xvii", import_xvii(today))):
            path = write(name, rows)
            print(f"{path.relative_to(ROOT)}: {sum(1 for _ in open(path)) - 1}행")


if __name__ == "__main__":
    main()
