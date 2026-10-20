"""LLM 구조화 출력 스키마 (with_structured_output 대상).

LLM이 자유 문장 대신 이 형식으로만 답하게 하면, 코드가 결과를 안전하게 이어받을 수 있다.
"""
from typing import Literal

from pydantic import BaseModel, Field

Region = Literal["KR", "US", "EU", "CN", "JP"]


class RouteDecision(BaseModel):
    route: Literal["chat", "lookup", "briefing"] = Field(
        description="chat: 인사·사용법 / lookup: 특정 물질·규제·제품 조회 / "
                    "briefing: 기간 내 규제 변경 브리핑과 제품 영향 분석")
    reasoning: str = Field(description="판단 이유 한 문장")


class BriefingPlan(BaseModel):
    days: int = Field(default=7, ge=1, le=90, description="최근 며칠의 변경을 볼지")
    regions: list[Region] = Field(default_factory=lambda: ["KR", "US"],
                                  description="볼 지역. 언급이 없으면 KR, US")
    substances: list[str] = Field(default_factory=list,
                                  description="사용자가 언급한 물질 이름 또는 CAS")
    product_ids: list[str] = Field(default_factory=list, description="사용자가 언급한 제품 ID (예: P003)")


class KeyDate(BaseModel):
    label: str = Field(description="날짜의 의미 (예: 의견 제출 마감, 준수 기한)")
    date: str = Field(description="YYYY-MM-DD 형식")


class DocumentSummary(BaseModel):
    title_ko: str = Field(description="문서 제목의 한국어 번역")
    summary_ko: str = Field(description="핵심 내용 2~4문장. 근거 문장에 있는 사실만 사용")
    key_dates: list[KeyDate] = Field(default_factory=list, description="근거 문장에 나온 날짜만")
    substances: list[str] = Field(default_factory=list, description="문서가 다루는 물질 이름 (영문)")
    action_ko: str = Field(description="규제 담당자가 할 일 한 문장. 근거에 없으면 '확인 필요'")


class Judgement(BaseModel):
    relevance: int = Field(ge=1, le=5, description="질문에 답했는가")
    completeness: int = Field(ge=1, le=5, description="영향 제품·할 일·기한·근거를 담았는가")
    faithfulness: int = Field(ge=1, le=5, description="근거에 없는 사실·의무를 만들지 않았는가")
    clarity: int = Field(ge=1, le=5, description="담당자가 바로 이해하고 행동할 수 있는가")
    is_acceptable: bool
    feedback: str = Field(description="불합격이면 고칠 점, 합격이면 빈 문자열")
