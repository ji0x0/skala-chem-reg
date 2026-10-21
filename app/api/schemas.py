"""REST API 요청·응답 스키마 (제품 스키마는 app.domain.products를 그대로 쓴다)."""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000,
                         examples=["이번 주 미국 EPA랑 국내 규제 변경 브리핑해줘"])
    thread_id: str | None = Field(default=None, max_length=64, description="비우면 새 대화")


class WeeklyReview(BaseModel):
    reviewer: str = Field(default="규제 담당자", min_length=1, max_length=50)
    comment: str = Field(default="", max_length=500, examples=["P003 고객사 공지 준비"])


class WeeklyRun(BaseModel):
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="월요일 (비우면 지난주)")


class ThreadRename(BaseModel):
    title: str = Field(min_length=1, max_length=60, examples=["P003 TCE 규제 대응"])


class FeedbackRequest(BaseModel):
    run_id: str
    score: int = Field(ge=0, le=1, description="1=도움됨, 0=도움 안 됨")
    comment: str = Field(default="", max_length=500)


class HealthResponse(BaseModel):
    status: str
    instance_id: int
    pipeline: str
    llm_backend: str
    fast_model: str
    quality_model: str
    tools: list[str]
    products: int
    substances: int
