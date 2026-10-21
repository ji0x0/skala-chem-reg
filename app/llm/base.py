"""에이전트가 쓰는 LLM 기능 인터페이스.

그래프 노드는 이 인터페이스만 안다. 구현은 두 가지다.
- LangChainLLM: init_chat_model(Ollama / OpenAI) + 프롬프트 + 구조화 출력 + 스트리밍
- FakeLLM: 결정론 규칙. 테스트와 API 키 없는 시연용

모든 메서드는 (결과, usage)를 돌려준다. usage = {"stage", "model", "tokens", "usd"} → 비용 집계
"""
from __future__ import annotations

from typing import Any, Callable, Protocol

from .schemas import BriefingPlan, DocumentSummary, Judgement, RouteDecision

TokenCallback = Callable[[str], None] | None
Usage = dict


class AgentLLM(Protocol):
    fast_name: str
    quality_name: str
    # 도구를 직접 부르는 ReAct 에이전트용 LangChain 모델 (Step 8 국내 수집). 없으면(None) 코드 안전장치로 대신
    agent_model: Any

    def usage_for(self, stage: str, tokens: int) -> Usage: ...

    async def route(self, question: str) -> tuple[RouteDecision, Usage]: ...

    async def plan(self, question: str, today: str) -> tuple[BriefingPlan, Usage]: ...

    async def summarize_document(self, meta: str, quotes: list[str],
                                 glossary: str) -> tuple[DocumentSummary, Usage]: ...

    async def write_briefing(self, question: str, summaries: str, judgements: str, citations: str,
                             feedback: str | None, on_token: TokenCallback = None) -> tuple[str, Usage]: ...

    async def judge(self, question: str, report: str, citations: str,
                    code_checks: str) -> tuple[Judgement, Usage]: ...

    async def answer(self, question: str, context: str, citations: str, history: str,
                     on_token: TokenCallback = None) -> tuple[str, Usage]: ...

    async def baseline_briefing(self, question: str, documents: str, products: str,
                                on_token: TokenCallback = None) -> tuple[str, Usage]:
        """Before 비교용: 원문과 제품 배합을 통째로 주고 판단까지 LLM에 맡긴다."""
        ...
