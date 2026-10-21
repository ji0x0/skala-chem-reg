"""감시하는 규제 목록과 버전.

지금 자동으로 감지·추출할 수 있는 것은 EU 통합본(Cellar)으로 만든 두 목록이다 (설계 8절).
통합본 CELEX "02008R1272-20270101" = CLP의 2027-01-01 기준 통합본. 날짜가 오늘보다 뒤면 "적용 예정" 판이다.
SVHC 후보 목록·일본 1종(웹 화면만 제공)과 국내 목록(별표·첨부 파일)은 아직 감지만 할 수 없어 대상이 아니다.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from app.core.config import Settings
from scripts import import_official_lists as importer

CELLAR_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
CONSOLIDATED = re.compile(r"\b0\d{4}R\d{4}-(\d{8})\b")


@dataclass(frozen=True)
class Watched:
    reg_id: str
    label: str
    base_celex: str          # 통합본 CELEX 앞부분 (0 + 연도 + R + 번호)
    bulk_file: str           # data/regulations/bulk/ 안의 파일 이름
    importer: str            # scripts/import_official_lists.py 의 함수 이름


WATCHED = [
    Watched("EU_CLP_ANNEX_VI", "EU CLP 부속서 VI 조화된 분류", "02008R1272", "eu_clp_annex_vi.csv", "import_clp"),
    Watched("EU_REACH_XVII", "EU REACH 부속서 XVII 제한", "02006R1907", "eu_reach_xvii.csv", "import_xvii"),
]
BY_REG = {w.reg_id: w for w in WATCHED}


def version_date(celex: str) -> str:
    """'02008R1272-20270101' → '2027-01-01'"""
    d = celex.rsplit("-", 1)[-1]
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def effective_file(settings: Settings, w: Watched) -> Path:
    """지금 DB가 쓰는 파일: 승인해 반영한 갱신이 있으면 그것, 없으면 저장소의 bulk 파일."""
    applied = settings.reg_updates_dir / "bulk" / w.bulk_file
    return applied if applied.exists() else settings.regulations_dir / "bulk" / w.bulk_file


def read_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def current_version(settings: Settings, w: Watched) -> str | None:
    """지금 DB의 통합본 버전 — 행의 근거(evidence)에 적힌 CELEX."""
    for row in read_rows(effective_file(settings, w)):
        m = CONSOLIDATED.search(row.get("evidence", ""))
        if m:
            return m.group(0)
    return None


def latest_version(w: Watched, timeout: float = 60) -> str:
    """EU 출판국 Cellar에 올라온 통합본 중 가장 최근 버전 (적용 예정 판 포함)."""
    query = f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex WHERE {{
  ?w cdm:resource_legal_id_celex ?celex . FILTER(STRSTARTS(STR(?celex), "{w.base_celex}-"))
}} ORDER BY DESC(?celex) LIMIT 1"""
    resp = httpx.get(CELLAR_SPARQL, params={"query": query}, timeout=timeout,
                     headers={"Accept": "application/sparql-results+json"})
    resp.raise_for_status()
    rows = resp.json()["results"]["bindings"]
    if not rows:
        raise ValueError(f"통합본을 찾지 못했습니다: {w.base_celex}")
    return rows[0]["celex"]["value"]


def fetch_rows(w: Watched, celex: str, verified_on: str | None = None) -> list[dict]:
    """새 버전 원본을 받아 지금 목록과 같은 방법(같은 파서)으로 행을 만든다. 원본은 data/regulations/raw/에 캐시."""
    rows = getattr(importer, w.importer)(verified_on or date.today().isoformat(), celex)
    return importer.unique_rows(rows)


def write_rows(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=importer.HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return path
