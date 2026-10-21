"""평가 실행기 — 질문 하나를 그래프에 넣고(승인은 자동) 답변·근거·토큰·시간을 모은다.

채점 입력(corpus)도 여기서 만든다: 관보 스냅샷 본문 + 규제 DB + 제품 배합.
"이 자료 어디에도 없는 CAS·날짜"를 지어낸 사실로 센다.
"""
from __future__ import annotations

import csv
import json
import time
import uuid
from datetime import date
from pathlib import Path


from app.core.config import DATA_DIR, Settings

QUESTIONS_PATH = DATA_DIR / "eval" / "questions.json"


def load_questions(ids: list[str] | None = None) -> list[dict]:
    items = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]
    return [q for q in items if not ids or q["id"] in ids]


def _csv_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load_corpus(settings: Settings) -> dict:
    """채점 기준 자료. documents: 문서 번호 → 본문, listings: {(규제 ID, CAS)}."""
    fulltext_dir = settings.feeds_dir / "fulltext"
    documents = {p.stem: p.read_text(encoding="utf-8") for p in sorted(fulltext_dir.glob("*.txt"))}
    for p in sorted((settings.feeds_dir / "kr_fulltext").glob("*.json")):        # 국내 고시 (Step 8)
        doc = json.loads(p.read_text(encoding="utf-8"))
        documents[p.stem] = "\n\n".join(doc["amendment"] + doc["addenda"] + doc.get("changes", [])
                                         + doc["articles"] + doc["annexes"])
    snapshot = (_csv_text(settings.feeds_dir / "federal_register_tsca.json")    # 제목·요약·게시일·마감일
                + "\n" + _csv_text(settings.feeds_dir / "kr_admin_rules.json"))  # 국내: 제목·발령일·시행일
    regs = settings.regulations_dir
    sources = [regs / "listings.csv", *sorted((regs / "bulk").glob("*.csv"))]   # 정리한 행 + 공식 전체 목록
    listings = set()
    for path in sources:
        with path.open(encoding="utf-8") as f:
            listings |= {(r["reg_id"], r["cas"]) for r in csv.DictReader(f)}
    text = "\n".join([*documents.values(), snapshot, _csv_text(regs / "sources.csv"), *map(_csv_text, sources),
                      _csv_text(settings.products_path), _csv_text(settings.glossary_path)])
    return {"documents": documents, "listings": listings, "text": text,
            "reference": date.today().isoformat()}        # 답변에 오늘 날짜(기준일)를 쓰는 것은 허용


async def run_question(graph, question: str, *, pipeline: str, qid: str) -> dict:
    """그래프 실행 → 최종 상태 (대화 답변에는 승인이 없다)."""
    thread = f"eval-{pipeline}-{qid}-{uuid.uuid4().hex[:6]}"
    config = {"configurable": {"thread_id": thread}, "run_name": f"eval:{pipeline}:{qid}",
              "tags": ["eval", pipeline], "metadata": {"question_id": qid}}
    started = time.perf_counter()
    error = None
    try:
        await graph.ainvoke({"question": question}, config)
    except Exception as exc:                                # 한 문항 실패가 실험 전체를 멈추지 않게
        error = f"{type(exc).__name__}: {exc}"[:300]
    values = (await graph.aget_state(config)).values or {}
    usage = values.get("usage", [])
    return {
        "answer": values.get("final") or values.get("draft") or "",
        "citations": values.get("citations", []),
        "route": values.get("route"),
        "tokens": sum(u.get("tokens", 0) for u in usage),
        "usd": round(sum(u.get("usd", 0.0) for u in usage), 6),
        "latency_s": round(time.perf_counter() - started, 1),
        "error": error,
    }
