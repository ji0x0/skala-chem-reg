"""그래프 공유 상태(State).

노드들은 이 상태를 읽고, 바뀐 부분만 돌려준다. LangGraph가 리듀서로 합친다.
- 기본: 새 값으로 덮어쓴다
- 리스트에 계속 더할 값(대화 이력, 근거, 사용량 등)은 Annotated[..., 리듀서]로 지정한다

체크포인터가 thread_id별로 상태를 저장하므로 같은 대화의 다음 질문에도 이전 값이 남는다.
그래서 질문마다 새로 시작해야 하는 값은 RESET 신호로 비운다.
(1차 초안에서 두 번째 질문의 토큰 사용량이 앞 질문과 합쳐진 문제를 겪었다 → [RESET, 새 값] 형식 지원)
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

RESET = "__reset__"


def add_or_reset(left: list | None, right: list | str | None) -> list:
    """RESET이면 비우고, [RESET, *items]이면 비운 뒤 items로 시작하고, 그 밖에는 이어 붙인다."""
    if right == RESET:
        return []
    if isinstance(right, list) and right and right[0] == RESET:
        return list(right[1:])
    return (left or []) + (right or [])


def merge_or_reset(left: dict | None, right: dict | str | None) -> dict:
    if right == RESET:
        return {}
    return {**(left or {}), **(right or {})}


class AgentState(TypedDict, total=False):
    # 대화 (질문이 바뀌어도 유지)
    question: str
    history: Annotated[list[dict], operator.add]

    # 질문마다 새로 채우는 값
    route: str
    route_reasoning: str
    plan: dict
    corrections: list[str]                                  # 코드가 LLM 계획을 바로잡은 기록
    tasks: list[dict]                                       # 병렬 조사 에이전트에 줄 일
    research_round: int
    documents: Annotated[list[dict], add_or_reset]          # 수집한 규제 문서 (근거 문장·언급 물질 포함)
    judgements: Annotated[dict[str, Any], merge_or_reset]   # 제품 ID → 판정 결과
    summaries: list[dict]                                   # 문서별 한국어 요약 (+ 무결성 검사 결과)
    impacts: list[dict]                                     # 문서 × 영향 제품 × 판정
    citations: Annotated[list[dict], add_or_reset]          # 근거 (원문·번역·출처·기준일)
    errors: Annotated[list[dict], add_or_reset]             # 실패한 조사 (격리된 오류)
    gaps: list[str]                                         # 확인하지 못한 항목
    draft: str
    writing_attempts: int
    validation_attempts: int
    validation_feedback: str | None
    guard: dict
    judgement: dict
    approval: dict
    final: str
    usage: Annotated[list[dict], add_or_reset]


def per_turn_reset(question: str) -> dict:
    """새 질문을 받을 때 비울 값들."""
    return {"question": question, "route": "", "route_reasoning": "", "plan": {}, "corrections": [],
            "tasks": [], "research_round": 0, "documents": RESET, "judgements": RESET,
            "summaries": [], "impacts": [], "citations": RESET, "errors": RESET, "gaps": [],
            "draft": "", "writing_attempts": 0, "validation_attempts": 0, "validation_feedback": None,
            "guard": {}, "judgement": {}, "approval": {}, "final": ""}
