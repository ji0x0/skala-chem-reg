"""LangChain 기반 실제 LLM (Ollama 또는 OpenAI).

- init_chat_model: 공급자가 달라도 같은 코드로 모델 생성
- 모델 분리: fast(분류·계획·질의응답) / quality(요약·작성·검토)
- 구조화 출력: with_structured_output(Pydantic, include_raw=True) → 결과와 토큰 사용량을 함께 얻는다
- 스트리밍: 브리핑·답변은 astream으로 토큰 조각을 바로 흘려보낸다
- 형식이 깨지면 None을 돌려주고, 부르는 쪽(그래프 노드)이 코드 규칙으로 대체한다
"""
from __future__ import annotations

import logging
import time

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.core.config import Settings

from . import prompts
from .base import TokenCallback, Usage
from .schemas import BriefingPlan, DocumentSummary, Judgement, RouteDecision

log = logging.getLogger(__name__)


def build_chat_models(s: Settings) -> tuple[BaseChatModel, BaseChatModel]:
    if s.llm_backend == "ollama":
        common = {"model_provider": "ollama", "base_url": s.ollama_base_url, "temperature": 0,
                  "reasoning": False,          # qwen3의 "생각" 출력 끄기 (속도·형식 안정)
                  "num_ctx": 8192, "client_kwargs": {"timeout": s.llm_timeout_s}}
        # num_predict: 작은 모델이 끝없이 생성하는 경우를 막는 출력 토큰 상한
        return (init_chat_model(s.ollama_fast_model, num_predict=512, **common),
                init_chat_model(s.ollama_quality_model, num_predict=2048, **common))
    if s.llm_backend == "openai":
        common = {"model_provider": "openai", "temperature": 0, "timeout": s.llm_timeout_s,
                  "stream_usage": True, "max_retries": 2}
        return (init_chat_model(s.openai_fast_model, **common),
                init_chat_model(s.openai_quality_model, **common))
    raise ValueError(f"LangChain 백엔드가 아닙니다: {s.llm_backend}")


def _tokens(message) -> int:
    meta = getattr(message, "usage_metadata", None) or {}
    return int(meta.get("total_tokens") or 0)


class LangChainLLM:
    def __init__(self, settings: Settings, fast: BaseChatModel | None = None,
                 quality: BaseChatModel | None = None):
        if fast is None or quality is None:
            fast, quality = build_chat_models(settings)
        self.fast, self.quality = fast, quality
        backend = settings.llm_backend
        self.fast_name = f"{backend}:{getattr(fast, 'model', getattr(fast, 'model_name', 'fast'))}"
        self.quality_name = f"{backend}:{getattr(quality, 'model', getattr(quality, 'model_name', 'quality'))}"
        self._price = {"fast": settings.fast_usd_per_1k, "quality": settings.quality_usd_per_1k}

    def _usage(self, stage: str, tier: str, tokens: int) -> Usage:
        return {"stage": stage, "model": getattr(self, f"{tier}_name"), "tokens": tokens,
                "usd": round(tokens / 1000 * self._price[tier], 6)}

    async def _structured(self, tier: str, prompt, schema, variables: dict, stage: str):
        model = self.fast if tier == "fast" else self.quality
        chain = prompt | model.with_structured_output(schema, include_raw=True)
        started = time.perf_counter()
        out = await chain.ainvoke(variables, config={"run_name": stage})
        log.info("LLM 호출", extra={"node": stage, "latency_ms": int((time.perf_counter() - started) * 1000)})
        usage = self._usage(stage, tier, _tokens(out.get("raw")))
        if out.get("parsing_error") or out.get("parsed") is None:
            log.warning("구조화 출력 형식 오류", extra={"node": stage, "event": "parse_error"})
            return None, usage
        return out["parsed"], usage

    async def _stream(self, tier: str, prompt, variables: dict, stage: str,
                      on_token: TokenCallback) -> tuple[str, Usage]:
        model = self.fast if tier == "fast" else self.quality
        chunks, tokens = [], 0
        async for chunk in (prompt | model).astream(variables, config={"run_name": stage}):
            if chunk.content:
                chunks.append(chunk.content)
                if on_token:
                    on_token(chunk.content)
            tokens = max(tokens, _tokens(chunk))
        return "".join(chunks), self._usage(stage, tier, tokens)

    # ── 인터페이스 구현 ───────────────────────────────────────────────────────
    async def route(self, question):
        return await self._structured("fast", prompts.ROUTE, RouteDecision, {"question": question}, "route")

    async def plan(self, question, today):
        return await self._structured("fast", prompts.PLAN, BriefingPlan,
                                      {"question": question, "today": today}, "plan")

    async def summarize_document(self, meta, quotes, glossary):
        numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(quotes, start=1))
        return await self._structured("quality", prompts.SUMMARIZE_DOC, DocumentSummary,
                                      {"meta": meta, "quotes": numbered, "glossary": glossary}, "summarize")

    async def write_briefing(self, question, summaries, judgements, citations, feedback,
                             on_token: TokenCallback = None):
        return await self._stream("quality", prompts.WRITE_BRIEFING,
                                  {"question": question, "summaries": summaries, "judgements": judgements,
                                   "citations": citations,
                                   "feedback": f"## 이전 초안 반려 사유 (반드시 반영)\n{feedback}" if feedback else ""},
                                  "write_briefing", on_token)

    async def judge(self, question, report, citations, code_checks):
        return await self._structured("quality", prompts.JUDGE, Judgement,
                                      {"question": question, "report": report, "citations": citations,
                                       "code_checks": code_checks}, "judge")

    async def answer(self, question, context, citations, history, on_token: TokenCallback = None):
        return await self._stream("fast", prompts.ANSWER,
                                  {"question": question, "context": context or "(없음)",
                                   "citations": citations or "(없음)", "history": history or "(없음)"},
                                  "answer", on_token)

    async def baseline_briefing(self, question, documents, products, on_token: TokenCallback = None):
        return await self._stream("quality", prompts.BASELINE_BRIEFING,
                                  {"question": question, "documents": documents, "products": products},
                                  "baseline_briefing", on_token)


def build_llm(settings: Settings):
    if settings.llm_backend == "fake":
        from .fake import FakeLLM
        return FakeLLM(settings.fast_usd_per_1k, settings.quality_usd_per_1k)
    return LangChainLLM(settings)
