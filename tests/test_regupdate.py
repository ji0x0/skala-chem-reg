"""Step 12 — 규제 DB 갱신 제안: 행 비교, 갱신 파일로 DB 빌드, 감지 → 후보 → 승인/반려 → 반영·재판정, 재시작.

네트워크 없이: 최신 버전 조회와 새 버전 행 읽기를 바꿔 끼운다. 새 CLP 버전 = 지금 목록에서
이산화티타늄(회사 성분, P002·P004·P010) 삭제 + 1행 내용 변경 + 1행 추가 (실제 2027-01-01 통합본의 변화가 이산화티타늄 삭제).
"""
import shutil

import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import Settings, get_settings
from app.llm.fake import FakeLLM
from app.main import create_app
from app.regupdate import compare, sources
from app.repositories.product_db import ProductDB
from app.repositories.reg_db import RegDB
from app.tools.provider import InMemoryToolProvider
from mcp_servers import product_server, reg_db_server, reg_feed_server
from scripts.build_reg_db import build, load_listings
from tests.test_admin import AUTH, TOKEN

CLP, REACH = sources.BY_REG["EU_CLP_ANNEX_VI"], sources.BY_REG["EU_REACH_XVII"]
OLD, NEW = "02008R1272-20260701", "02008R1272-20270101"
TIO2 = "13463-67-7"


def new_clp_rows() -> list[dict]:
    rows = sources.read_rows(get_settings().regulations_dir / "bulk" / CLP.bulk_file)
    rows = [{**r, "evidence": r["evidence"].replace(OLD, NEW), "verified_on": "2026-10-21"}   # 버전·확인일만 바뀐 행은 같은 행
            for r in rows if r["cas"] != TIO2]
    rows[0] = {**rows[0], "condition_ko": rows[0]["condition_ko"] + ", Skin Sens. 1"}
    rows.append({**rows[1], "cas": "64-17-5", "entry_ref": "999-999-99-9", "name_en": "test substance"})
    return rows


@pytest.fixture
def offline_cellar(monkeypatch):
    latest = {CLP.reg_id: NEW, REACH.reg_id: "02006R1907-20260622"}
    monkeypatch.setattr(sources, "latest_version", lambda w, timeout=60: latest[w.reg_id])
    monkeypatch.setattr(sources, "fetch_rows", lambda w, celex, verified_on=None: new_clp_rows())


def make_client(monkeypatch, tmp_path, db_name="regulations.db"):
    """규제 DB·갱신 폴더를 모두 임시 폴더에 — 승인하면 이 DB가 바뀐다 (저장소의 DB는 그대로)."""
    reg_db = tmp_path / db_name
    if not reg_db.exists():
        shutil.copyfile(get_settings().reg_db_path, reg_db)
    settings = Settings(_env_file=None, llm_backend="fake", app_db_path=tmp_path / "app.db", admin_token=TOKEN,
                        reg_db_path=reg_db, reg_updates_dir=tmp_path / "updates")
    products = ProductDB(settings.app_db_path)
    products.seed_if_empty(settings.products_path)
    regdb = RegDB(reg_db, products)
    for module in (product_server, reg_db_server, reg_feed_server):
        monkeypatch.setattr(module, "db", regdb)
    monkeypatch.setattr(reg_feed_server.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    app = create_app(settings, llm=FakeLLM(), tools=InMemoryToolProvider(), checkpointer=InMemorySaver())
    return TestClient(app), regdb


def clp_listing(regdb: RegDB, cas: str) -> list[dict]:
    return [x for x in regdb.listings_for_cas([cas]) if x["reg_id"] == CLP.reg_id]


def test_diff_ignores_version_fields():
    old = sources.read_rows(get_settings().regulations_dir / "bulk" / CLP.bulk_file)
    diff = compare.diff_rows(old, new_clp_rows())
    assert compare.counts(diff) == {"added": 1, "removed": 1, "changed": 1}     # 확인일·근거 버전만 바뀐 4,000여 행은 변화 아님
    assert diff["removed"][0]["cas"] == TIO2 and list(diff["changed"][0]["fields"]) == ["condition_ko"]
    company = compare.company_rows(diff, {TIO2: "이산화티타늄"})
    assert company == [{"change": "removed", **diff["removed"][0], "ingredient": "이산화티타늄"}]


def test_build_uses_update_files_and_replaces_atomically(tmp_path):
    updates = tmp_path / "updates"
    sources.write_rows(updates / "bulk" / CLP.bulk_file, new_clp_rows())
    regs = get_settings().regulations_dir
    assert not [r for r in load_listings(regs, {CLP.bulk_file: updates / "bulk" / CLP.bulk_file})
                if r["reg_id"] == CLP.reg_id and r["cas"] == TIO2]
    settings = Settings(_env_file=None, reg_db_path=tmp_path / "regulations.db", reg_updates_dir=updates)
    counts = build(settings)
    assert counts["updates"] == [CLP.bulk_file] and counts["listings"] == 9351          # -1 +1
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []            # 임시 파일 남지 않음
    assert sources.current_version(settings, CLP) == NEW


def test_detect_propose_approve_apply(monkeypatch, tmp_path, offline_cellar):
    client, regdb = make_client(monkeypatch, tmp_path)
    with client:
        assert clp_listing(regdb, TIO2)
        results = {r["reg_id"]: r for r in client.post("/api/v1/admin/updates/check", headers=AUTH).json()}
        assert results[CLP.reg_id]["outcome"] == "proposed" and results[REACH.reg_id]["outcome"] == "no_new_version"
        assert clp_listing(regdb, TIO2)                                          # 승인 전에는 DB가 그대로

        [item] = client.get("/api/v1/admin/updates", headers=AUTH).json()
        assert item["status"] == "pending" and item["effective_date"] == "2027-01-01"
        assert item["counts"] == {"added": 1, "removed": 1, "changed": 1}
        assert [c["cas"] for c in item["company"]] == [TIO2]
        assert [p["product_id"] for p in item["products"]] == ["P002", "P004", "P010"]   # 후보 DB로 미리 판정
        assert all(p["removed"][0]["outcome"] == "listed" for p in item["products"])
        assert "적용 예정 판" in item["facts"] and item["summary"]
        assert client.get("/api/v1/admin/overview", headers=AUTH).json()["pending_approvals"] == 1
        again = client.post("/api/v1/admin/updates/check", headers=AUTH).json()
        assert {r["reg_id"]: r["outcome"] for r in again}[CLP.reg_id] == "already_proposed"   # 같은 버전은 한 번만

        done = client.post(f"/api/v1/admin/updates/{item['id']}/decision", headers=AUTH,
                           json={"approved": True, "approver": "팀장", "comment": "적용일 확인"}).json()
        assert done["status"] == "applied" and done["decided_by"] == "팀장" and done["applied_counts"]["listings"] == 9351
        assert not clp_listing(regdb, TIO2) and clp_listing(regdb, "64-17-5")      # 반영: 같은 경로의 DB가 바뀜
        assert (tmp_path / "updates" / "bulk" / CLP.bulk_file).exists()
        judged = client.get("/api/v1/products/P010", headers=AUTH).json()
        assert not [f for f in judged["judgement"]["findings"] if f["reg_id"] == CLP.reg_id and f["cas"] == TIO2]

        decided_again = client.post(f"/api/v1/admin/updates/{item['id']}/decision", headers=AUTH, json={"approved": True})
        assert decided_again.status_code == 409
        assert client.post("/api/v1/admin/updates/999/decision", headers=AUTH, json={"approved": True}).status_code == 404
        kinds = [r["kind"] for r in client.get("/api/v1/admin/runs", headers=AUTH).json()]
        assert kinds.count("update") == 4 and kinds.count("approval") == 1          # 확인 2회 × 목록 2개 + 결정 1

    # 서버를 다시 시작하면 (Docker: 이미지의 DB는 저장소 원본 기준) 승인한 갱신으로 DB를 다시 만든다
    shutil.copyfile(get_settings().reg_db_path, tmp_path / "fresh.db")
    client2, regdb2 = make_client(monkeypatch, tmp_path, db_name="fresh.db")
    with client2:
        assert not clp_listing(regdb2, TIO2)


def test_reject_keeps_db(monkeypatch, tmp_path, offline_cellar):
    client, regdb = make_client(monkeypatch, tmp_path)
    with client:
        client.post("/api/v1/admin/updates/check", headers=AUTH)
        [item] = client.get("/api/v1/admin/updates", headers=AUTH).json()
        done = client.post(f"/api/v1/admin/updates/{item['id']}/decision", headers=AUTH,
                           json={"approved": False, "comment": "적용일 전이라 보류"}).json()
        assert done["status"] == "rejected" and clp_listing(regdb, TIO2)
        assert not (tmp_path / "updates" / "bulk" / CLP.bulk_file).exists()


def test_invented_numbers_in_explanation_fall_back_to_facts(monkeypatch, tmp_path, offline_cellar):
    async def inventing(self, question, context, citations, history, on_token=None):
        return "이산화티타늄 분류가 2028-03-01부터 삭제되어 제품 7개에 영향이 있습니다.", self._usage("answer", "fast", question)
    monkeypatch.setattr(FakeLLM, "answer", inventing)
    client, _ = make_client(monkeypatch, tmp_path)
    with client:
        client.post("/api/v1/admin/updates/check", headers=AUTH)
        [item] = client.get("/api/v1/admin/updates", headers=AUTH).json()
        assert item["summary"] == "" and "P010" in item["facts"]                   # 지어낸 날짜·숫자 → 설명 버림
