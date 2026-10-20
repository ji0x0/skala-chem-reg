"""결정론 Fake LLM — 실제 모델 없이 파이프라인 전체를 재현한다 (테스트·키 없는 시연용).

실제 판단 대신 단순 규칙으로 답한다. 화면 데모에는 쓰지 않는다 (1차 초안에서 "깡통 답변" 문제).
"""
from __future__ import annotations

import re
from datetime import date

from app.domain.integrity import extract_facts

from .base import TokenCallback, Usage
from .schemas import BriefingPlan, DocumentSummary, Judgement, KeyDate, RouteDecision

BRIEFING_WORDS = r"브리핑|이번 주|최근|지난주|변경|바뀐|새로 나온|동향|업데이트"
LOOKUP_WORDS = r"\d{2,7}-\d{2}-\d|P\d{3}|해당|규제 대상|등재|SVHC|TSCA|REACH|CLP|화관법|산안법|들어 있|포함"
REGION_WORDS = {"KR": r"국내|한국", "US": r"미국|EPA|TSCA", "EU": r"EU|유럽|REACH|ECHA|CLP",
                "CN": r"중국", "JP": r"일본"}


class FakeLLM:
    def __init__(self, fast_usd_per_1k: float = 0.00015, quality_usd_per_1k: float = 0.005):
        self.fast_name, self.quality_name = "fake-fast", "fake-quality"
        self._price = {"fast": fast_usd_per_1k, "quality": quality_usd_per_1k}

    def _usage(self, stage: str, tier: str, *texts: str) -> Usage:
        tokens = sum(len(t) for t in texts) // 3 + 1
        return {"stage": stage, "model": getattr(self, f"{tier}_name"), "tokens": tokens,
                "usd": round(tokens / 1000 * self._price[tier], 6)}

    async def route(self, question):
        if re.search(BRIEFING_WORDS, question):
            route, why = "briefing", "기간 내 변경 정리 요청"
        elif re.search(LOOKUP_WORDS, question):
            route, why = "lookup", "물질·규제·제품 조회"
        else:
            route, why = "chat", "인사·사용법"
        return RouteDecision(route=route, reasoning=why), self._usage("route", "fast", question)

    async def plan(self, question, today):
        days = int(m.group(1)) if (m := re.search(r"(\d+)\s*일", question)) else 7
        regions = [r for r, pat in REGION_WORDS.items() if re.search(pat, question)] or ["KR", "US"]
        plan = BriefingPlan(days=min(days, 90), regions=regions,
                            substances=re.findall(r"\d{2,7}-\d{2}-\d", question),
                            product_ids=re.findall(r"P\d{3}", question))
        return plan, self._usage("plan", "fast", question)

    async def summarize_document(self, meta, quotes, glossary):
        text = " ".join(quotes)
        dates = sorted(extract_facts(text)["dates"])
        summary = DocumentSummary(
            title_ko=meta.splitlines()[0][:120] if meta else "(제목 없음)",
            summary_ko=f"근거 문장 {len(quotes)}개를 요약했습니다 (Fake). " + (quotes[0][:200] if quotes else ""),
            key_dates=[KeyDate(label="원문 날짜", date=d) for d in dates],
            substances=[], action_ko="확인 필요")
        return summary, self._usage("summarize", "quality", meta, text)

    async def write_briefing(self, question, summaries, judgements, citations, feedback,
                             on_token: TokenCallback = None):
        report = ("## 요약\n(Fake) 수집한 문서와 판정 결과를 정리했습니다.\n\n## 규제 변경 (지역별)\n"
                  f"{summaries}\n\n## 우리 제품 영향\n{judgements}\n\n## 할 일과 기한\n- 근거 문서 확인 [1]\n\n"
                  "## 확인이 필요한 항목\n- Fake LLM 결과이므로 실제 모델로 다시 확인")
        if on_token:
            for line in report.splitlines(keepends=True):
                on_token(line)
        return report, self._usage("write", "quality", summaries, judgements, report)

    async def judge(self, question, report, citations, code_checks):
        ok = "문제 없음" in code_checks or code_checks.strip() in ("", "{}")
        j = Judgement(relevance=4, completeness=4, faithfulness=5 if ok else 2, clarity=4,
                      is_acceptable=ok, feedback="" if ok else "코드 검사에서 문제가 발견됨")
        return j, self._usage("judge", "quality", report)

    async def answer(self, question, context, citations, history, on_token: TokenCallback = None):
        if context:
            text = f"조회 결과입니다 (Fake).\n\n{context}\n\n근거: {citations[:300]}"
        else:
            text = ("국내외 화학물질 규제 브리핑 도우미입니다. 물질(CAS)·제품의 규제 해당 여부를 묻거나 "
                    "\"이번 주 미국 EPA 규제 변경 브리핑해줘\"처럼 요청해 주세요.")
        if on_token:
            on_token(text)
        return text, self._usage("answer", "fast", question, text)


def today() -> str:
    return date.today().isoformat()
