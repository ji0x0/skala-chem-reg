"""Step 6 — 코드 채점기와 평가 실행 (fake LLM, 네트워크 없음)."""
import json
import os
import subprocess
import sys
from pathlib import Path

from app.core.config import get_settings
from app.eval.metrics import citation_check, flagged_products, invented_facts, keyword_score, prf, score_answer
from app.eval.runner import load_corpus, load_questions

ROOT = Path(__file__).resolve().parents[1]


def test_flagged_products_ignores_negation_and_examples():
    text = ("## 우리 제품 영향\n- P003 금속 탈지 세정제: TCE 94.5% [3]\n- P001은 이번 변경과 무관\n"
            "- P099: 등록되지 않은 제품\n제품 ID(예: P007)나 P010 형식으로 물어보세요")
    assert flagged_products(text) == {"P003"}


def test_prf_counts_false_positives_and_misses():
    assert prf({"P003", "P007"}, {"P003"}) == {"precision": 0.5, "recall": 1.0, "false_positives": ["P007"], "missed": []}
    assert prf(set(), set())["precision"] == 1.0                   # 음성 문항에서 아무것도 지목하지 않으면 만점
    assert prf(set(), {"P003"})["recall"] == 0.0


def test_keyword_alternatives():
    assert keyword_score("TCE 준수 기한 연장", ["트리클로로에틸렌|TCE", "연장", "P003"]) == 0.667


def test_invented_facts_against_sources():
    corpus = "TCE (79-01-6) compliance date December 31, 2027; comments by November 13, 2026"
    out = invented_facts("기한 2027-12-31, 마감 2026-11-13, 대상 79-01-6", corpus)
    assert out == {"cas": [], "dates": []}
    out = invented_facts("PFOA(335-67-1)는 2026-12-14까지 통보", corpus)
    assert out == {"cas": ["335-67-1"], "dates": ["2026-12-14"]}


def test_citation_check_verifies_quotes_and_listings():
    docs = {"2026-20964": "EPA is proposing to extend certain compliance dates until December 31, 2027."}
    cites = [{"id": 1, "kind": "document", "source_id": "2026-20964", "quote": "EPA is proposing to extend certain compliance dates until December 31, 2027."},
             {"id": 2, "kind": "document", "source_id": "2026-20964", "quote": "EPA bans TCE immediately."},
             {"id": 3, "kind": "listing", "source_id": "US_TSCA_S6", "quote": "제6조 · 트리클로로에틸렌 (CAS 79-01-6)"}]
    r = citation_check("근거 [1][3][9]", cites, docs, {("US_TSCA_S6", "79-01-6")})
    assert r["verified"] == 2 and r["unknown_refs"] == ["9"]     # 지어낸 인용 1개, 없는 근거 번호 1개
    assert r["used"] == 2


def test_cite_ok_requires_answer_to_use_citations():
    """외부 검토 ⑥: 근거 목록만 있고 본문에 근거 번호가 하나도 없어도 통과하던 문제."""
    corpus = load_corpus(get_settings())
    b1 = next(q for q in load_questions() if q["id"] == "B1")
    quote = corpus["documents"]["2026-20964"][:200].strip()
    cites = [{"id": 1, "kind": "document", "source_id": "2026-20964", "quote": quote}]
    without = score_answer(b1, "P003 영향. 마감 2026-11-13, 기한 2027-12-31", cites, "briefing", corpus)
    with_ref = score_answer(b1, "P003 영향 [1]. 마감 2026-11-13, 기한 2027-12-31", cites, "briefing", corpus)
    assert without.citations["verified"] == 1 and not without.cite_ok
    assert with_ref.cite_ok


def test_questions_and_corpus_are_consistent():
    items = load_questions()
    assert {q["category"] for q in items} == {"briefing", "briefing_kr", "routing", "lookup", "chat"}   # briefing_kr·routing: v2 회귀만
    corpus = load_corpus(get_settings())
    us = {"2026-20964", "2026-21051", "2026-21052", "2026-20436"}
    assert us <= set(corpus["documents"]) and "2100000275070" in corpus["documents"]   # 미국 관보 + 국내 고시
    for q in items:                                                  # 정답 날짜는 실제 자료에 있어야 한다
        for d in q["expect"].get("required_dates", []):
            assert not invented_facts(d, corpus["text"])["dates"], (q["id"], d)
    b1 = next(q for q in items if q["id"] == "B1")
    s = score_answer(b1, "## 우리 제품 영향\n- P003 (TCE) 의견 마감 2026-11-13, 준수 기한 2027-12-31", [], "briefing", corpus)
    assert s.route_ok and s.products["recall"] == 1.0 and s.dates == 1.0 and not s.cite_ok   # 근거 필수 문항


def test_run_eval_script_fake_mode(tmp_path):
    """실험 스크립트 전체 흐름 (fake LLM, 스냅샷 관보). 별도 프로세스: FEED_MODE 환경 변수가 다른 테스트에 새지 않게."""
    env = {**os.environ, "LLM_BACKEND": "fake", "LANGSMITH_TRACING": "false"}
    proc = subprocess.run([sys.executable, "scripts/run_eval.py", "--ids", "B1", "L4", "--judge", "--out", str(tmp_path)],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    data = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert [r["id"] for r in data["results"]["baseline"]] == ["B1"]          # Before는 briefing만
    assert [r["id"] for r in data["results"]["v2"]] == ["B1", "L4"]
    v2_b1 = data["results"]["v2"][0]
    assert v2_b1["products"]["recall"] == 1.0 and v2_b1["citations"]["verified"] == v2_b1["citations"]["count"] > 0
    assert "Before(LLM 단독) vs After(v2)" in next(tmp_path.glob("*.md")).read_text(encoding="utf-8")


def test_corpus_includes_bulk_official_lists():
    """재측정에서 발견: 공식 전체 목록(bulk)에서 온 근거를 '확인 안 됨'으로 세던 채점 누락."""
    corpus = load_corpus(get_settings())
    assert ("KR_CCA_HAZ", "71-43-2") in corpus["listings"] and ("EU_CLP_ANNEX_VI", "108-88-3") in corpus["listings"]


def test_citation_refs_are_normalized():
    from app.agents.graph import normalize_refs
    assert normalize_refs("기준 초과 [근거 1], 확인 필요 [근거 2, 3]") == "기준 초과 [1], 확인 필요 [2][3]"
