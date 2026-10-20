"""Step 3a 부품을 한 줄로 이어 본다 (그래프 없음).

    LLM_BACKEND=ollama uv run python scripts/llm_smoke.py              # 기본 문서: 2026-20964 (TCE)
    LLM_BACKEND=ollama uv run python scripts/llm_smoke.py 2026-21051

관보 문서(MCP) → 언급 물질 → 근거 문장 추출(코드) → 용어집(MCP) → LLM 요약(구조화 출력)
→ 무결성 검사(코드: 요약의 날짜·CAS·숫자가 근거 문장에 있는가)
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.domain import integrity  # noqa: E402
from app.domain.citations import extract_quotes, official_dates, quote_in_source  # noqa: E402
from app.domain.mentions import name_variants, ABBREVIATIONS  # noqa: E402
from app.llm.langchain_llm import build_llm  # noqa: E402
from app.tools.provider import MCPToolProvider  # noqa: E402


async def main(document_number: str) -> None:
    settings = get_settings()
    tools = MCPToolProvider(settings)
    await tools.start()
    try:
        doc = await tools.call("get_federal_register_document",
                               {"document_number": document_number, "max_chars": 100000})
        mentions = doc["substance_mentions"]
        print(f"[문서] {doc['document_number']} ({doc['source']}, {doc['text_source']}) {doc['title'][:80]}")
        print(f"[언급 물질] {[(m['name_ko'], m['mentions']) for m in mentions]}")

        terms = [t for m in mentions for t in name_variants(m["name_en"]) + ABBREVIATIONS.get(m["cas"], [])]
        quotes = extract_quotes(doc["text"], terms or [doc["title"]])
        assert all(quote_in_source(q, doc["text"]) for q in quotes)
        print(f"[근거 문장] 본문 {len(doc['text']):,}자 → {len(quotes)}개 {sum(map(len, quotes)):,}자 (원문 포함 확인)")

        glossary = await tools.call("glossary_lookup", {"text": doc["text"][:20000]})
        glossary_text = "\n".join(f"- {g['term']} → {g['ko']}" for g in glossary)
        print(f"[용어집] {[g['term'] for g in glossary]}")

        llm = build_llm(settings)
        meta = f"{doc['title']}\n종류: {doc['type']} / 게시일: {doc['publication_date']} / " \
               f"의견 마감: {doc.get('comments_close_on')}"
        started = time.perf_counter()
        summary, usage = await llm.summarize_document(meta, quotes, glossary_text)
        print(f"\n[LLM 요약] {llm.quality_name} {time.perf_counter() - started:.1f}s, 토큰 {usage['tokens']}")
        if summary is None:
            print("  형식 오류 — 구조화 출력 실패")
            return
        print(f"  제목: {summary.title_ko}\n  요약: {summary.summary_ko}")
        print(f"  본문 속 날짜(LLM): {[(d.label, d.date) for d in summary.key_dates]}")
        print(f"  공식 날짜(코드): {[(d['label'], d['date']) for d in official_dates(doc)]}")
        print(f"  할 일: {summary.action_ko}")

        # 무결성: LLM이 만든 문장의 사실이 근거 문장에 있는가 (공식 날짜는 코드가 넣으므로 대상 아님)
        produced = " ".join([summary.summary_ko, summary.action_ko] + [d.date for d in summary.key_dates])
        report = integrity.check(" ".join(quotes), produced, reference=meta)
        print(f"\n[무결성 검사] {'통과' if report.ok else '실패'} {report.to_dict()}")
    finally:
        await tools.stop()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "2026-20964"))
