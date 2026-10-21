"""제품·성분 저장소 (data/app.db) — 화면에서 추가·수정한 제품의 원본.

regulations.db는 CSV로 언제든 다시 만들지만, 이 DB는 다시 만들지 않는다.
비어 있을 때만 products.csv로 한 번 채운다(seed).
"""
from __future__ import annotations

import csv
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from app.domain.products import Product, products_from_rows, validate_product


class ProductValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class ProductDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS products (product_id TEXT PRIMARY KEY, product_name TEXT,
                    product_form TEXT, export_regions TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS ingredients (product_id TEXT REFERENCES products(product_id)
                    ON DELETE CASCADE, cas TEXT, ingredient_name TEXT, role TEXT, wt_pct REAL);
                CREATE INDEX IF NOT EXISTS idx_ingredients_cas ON ingredients(cas);
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with closing(self._connect()) as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # ── 초기 데이터 ─────────────────────────────────────────────────────────
    def seed_if_empty(self, csv_path: Path) -> int:
        if self._query("SELECT 1 FROM products LIMIT 1"):
            return 0
        with open(csv_path, encoding="utf-8", newline="") as f:
            products = products_from_rows(list(csv.DictReader(f)))
        for p in products:
            self.save(p)
        return len(products)

    # ── 조회 ────────────────────────────────────────────────────────────────
    def products(self) -> list[dict]:
        rows = self._query(
            "SELECT p.product_id, p.product_name, p.product_form, p.export_regions, p.updated_at, "
            "COUNT(i.cas) AS ingredient_count FROM products p LEFT JOIN ingredients i USING(product_id) "
            "GROUP BY p.product_id ORDER BY p.product_id")
        return rows

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
        if not cas_list:
            return []
        marks = ",".join("?" * len(cas_list))
        return self._query(
            f"SELECT p.product_id, p.product_name, p.product_form, p.export_regions, "
            f"i.cas, i.ingredient_name, i.role, i.wt_pct FROM ingredients i "
            f"JOIN products p USING(product_id) WHERE i.cas IN ({marks}) ORDER BY p.product_id",
            tuple(cas_list))

    def ingredient_names(self) -> dict[str, str]:
        """제품들에 든 성분 CAS → 성분명 (영문)."""
        return {r["cas"]: r["ingredient_name"] for r in self._query("SELECT DISTINCT cas, ingredient_name FROM ingredients")}

    def next_id(self) -> str:
        nums = [int(m.group(1)) for r in self._query("SELECT product_id FROM products")
                if (m := re.fullmatch(r"P(\d+)", r["product_id"]))]
        return f"P{(max(nums) + 1 if nums else 1):03d}"

    # ── 저장 (추가·수정 공통) ───────────────────────────────────────────────
    def save(self, product: Product, *, must_exist: bool | None = None) -> str:
        """검증 → 저장. must_exist=True면 수정, False면 신규, None이면 둘 다 허용(초기 데이터)."""
        errors = validate_product(product)
        if errors:
            raise ProductValidationError(errors)
        pid = product.product_id or self.next_id()
        exists = self.product(pid) is not None
        if must_exist is True and not exists:
            raise KeyError(pid)
        if must_exist is False and exists:
            raise ProductValidationError([f"이미 있는 제품 ID입니다: {pid}"])
        with closing(self._connect()) as conn, conn:          # 한 트랜잭션: 제품 + 성분 전체 교체
            conn.execute("DELETE FROM products WHERE product_id=?", (pid,))
            conn.execute("INSERT INTO products(product_id, product_name, product_form, export_regions) "
                         "VALUES (?,?,?,?)", (pid, product.product_name, product.product_form,
                                              ";".join(product.export_regions)))
            conn.executemany("INSERT INTO ingredients VALUES (?,?,?,?,?)",
                             [(pid, i.cas, i.ingredient_name, i.role, i.wt_pct) for i in product.ingredients])
        return pid
