"""규제 DB(SQLite) 조회.

DB 접근은 이 클래스 한 곳에만 둔다. 판정 코드(domain)·MCP 서버·테스트는 SQL을 직접 쓰지 않고
여기 메서드를 부른다. 저장소를 PostgreSQL로 바꾸더라도 이 파일만 고치면 된다.

Step 4부터 제품·성분은 app.db(ProductDB)가 원본이다. 규제 판정 코드가 쓰는 제품 조회 메서드는
그대로 두고 ProductDB에 위임한다 → judge.py는 바꾸지 않아도 된다.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .product_db import ProductDB


class RegDB:
    def __init__(self, db_path: Path, products: ProductDB):
        if not Path(db_path).exists():
            raise FileNotFoundError(
                f"{db_path}가 없습니다. 먼저 `uv run python scripts/build_reg_db.py`를 실행하세요.")
        self.db_path = Path(db_path)
        self._products = products

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # ── 규제 ────────────────────────────────────────────────────────────────
    def regulations(self) -> list[dict]:
        return self._query("SELECT * FROM regulations ORDER BY priority, region, reg_id")

    def regulation(self, reg_id: str) -> dict | None:
        rows = self._query("SELECT * FROM regulations WHERE reg_id=?", (reg_id,))
        return rows[0] if rows else None

    def listings_for_cas(self, cas_list: list[str]) -> list[dict]:
        """여러 CAS의 등재 정보를 규제 정보와 합쳐 돌려준다."""
        if not cas_list:
            return []
        marks = ",".join("?" * len(cas_list))
        return self._query(
            f"SELECT l.*, r.region, r.law, r.list_name, r.rule_type, r.applies_when, "
            f"r.default_threshold_wt_pct, r.obligation_ko, r.priority "
            f"FROM listings l JOIN regulations r USING(reg_id) WHERE l.cas IN ({marks}) "
            f"ORDER BY r.priority, r.region", tuple(cas_list))

    def listings_for_reg(self, reg_id: str) -> list[dict]:
        return self._query("SELECT * FROM listings WHERE reg_id=? ORDER BY name_en", (reg_id,))

    def search_substance(self, keyword: str, limit: int | None = None) -> list[dict]:
        """CAS 또는 영문·한글 이름 일부로 등재 물질을 찾는다 (CAS마다 한 행 — 목록마다 영문 표기가 달라도)."""
        like = f"%{keyword}%"
        # 영문 이름은 정리한 행(listings.csv)의 표기를 우선 — "(DEHP)" 같은 약어가 들어 있어 질문 속 약어 매칭에 쓰인다
        sql = ("SELECT cas, COALESCE(MAX(CASE WHEN origin='listings.csv' AND name_en != '' THEN name_en END), "
               "MIN(NULLIF(name_en, '')), '') AS name_en, MAX(name_ko) AS name_ko FROM listings "
               "WHERE cas=? OR name_en LIKE ? OR name_ko LIKE ? GROUP BY cas "
               "ORDER BY MAX(name_ko) = '', MIN(name_en)")
        return self._query(sql + (f" LIMIT {int(limit)}" if limit else ""), (keyword, like, like))

    def company_substances(self) -> list[dict]:
        """회사 제품에 든 성분 중 규제 DB에 있는 물질 (+ 제품 배합의 성분명). 관보 본문의 물질명 매칭용 —
        수천 개 전체 목록으로 찾으면 회사와 무관한 물질이 잡힌다."""
        ingredients = self._products.ingredient_names()
        if not ingredients:
            return []
        marks = ",".join("?" * len(ingredients))
        rows = self._query(f"SELECT cas, name_en, MAX(name_ko) AS name_ko FROM listings WHERE cas IN ({marks}) "
                           f"GROUP BY cas, name_en", tuple(ingredients))
        listed = {r["cas"] for r in rows}
        rows += [{"cas": cas, "name_en": name, "name_ko": ""} for cas, name in ingredients.items() if cas in listed]
        return rows

    # ── 제품 (app.db의 ProductDB에 위임) ─────────────────────────────────────
    def products(self) -> list[dict]:
        return self._products.products()

    def product(self, product_id: str) -> dict | None:
        return self._products.product(product_id)

    def products_containing(self, cas_list: list[str]) -> list[dict]:
        return self._products.products_containing(cas_list)

    # ── 용어집 ──────────────────────────────────────────────────────────────
    def glossary(self) -> list[dict]:
        return self._query("SELECT * FROM glossary ORDER BY lang, term")
