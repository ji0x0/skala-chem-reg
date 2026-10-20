"""규제 DB(SQLite) 조회.

DB 접근은 이 클래스 한 곳에만 둔다. 판정 코드(domain)·MCP 서버·테스트는 SQL을 직접 쓰지 않고
여기 메서드를 부른다. 저장소를 PostgreSQL로 바꾸더라도 이 파일만 고치면 된다.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


class RegDB:
    def __init__(self, db_path: Path):
        if not Path(db_path).exists():
            raise FileNotFoundError(
                f"{db_path}가 없습니다. 먼저 `uv run python scripts/build_reg_db.py`를 실행하세요.")
        self.db_path = Path(db_path)

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

    def search_substance(self, keyword: str) -> list[dict]:
        """CAS 또는 영문·한글 이름 일부로 등재 물질을 찾는다."""
        like = f"%{keyword}%"
        return self._query(
            "SELECT DISTINCT cas, name_en, name_ko FROM listings "
            "WHERE cas=? OR name_en LIKE ? OR name_ko LIKE ? ORDER BY name_en",
            (keyword, like, like))

    # ── 제품 ────────────────────────────────────────────────────────────────
    def products(self) -> list[dict]:
        return self._query("SELECT * FROM products ORDER BY product_id")

    def product(self, product_id: str) -> dict | None:
        rows = self._query("SELECT * FROM products WHERE product_id=?", (product_id,))
        if not rows:
            return None
        product = rows[0]
        product["export_regions"] = product["export_regions"].split(";")
        product["ingredients"] = self._query(
            "SELECT cas, ingredient_name, role, wt_pct FROM ingredients WHERE product_id=? "
            "ORDER BY wt_pct DESC", (product_id,))
        return product

    def products_containing(self, cas_list: list[str]) -> list[dict]:
        """해당 CAS가 하나라도 들어 있는 제품과 그 성분 행."""
        if not cas_list:
            return []
        marks = ",".join("?" * len(cas_list))
        return self._query(
            f"SELECT p.product_id, p.product_name, p.product_form, p.export_regions, "
            f"i.cas, i.ingredient_name, i.role, i.wt_pct FROM ingredients i "
            f"JOIN products p USING(product_id) WHERE i.cas IN ({marks}) "
            f"ORDER BY p.product_id", tuple(cas_list))

    # ── 용어집 ──────────────────────────────────────────────────────────────
    def glossary(self) -> list[dict]:
        return self._query("SELECT * FROM glossary ORDER BY lang, term")
