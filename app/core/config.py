"""애플리케이션 설정.

모든 설정은 환경변수(.env)에서 읽어 Settings 하나에 모은다.
- 코드 곳곳에 상수를 흩어 두지 않는다 → 바꿀 곳이 한 군데
- 값의 형식을 시작할 때 검증한다 → 오타가 있으면 서버가 바로 멈춘다
- 테스트에서는 Settings(...)를 직접 만들어 넘긴다 → 의존성 주입의 출발점

단계가 진행되면서 필요한 설정을 아래에 추가한다.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]   # app/core/config.py → 프로젝트 루트
DATA_DIR = ROOT_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    # ── Step 0: 공통 ──
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── Step 1: 데이터 ──
    regulations_dir: Path = DATA_DIR / "regulations"     # 규제 목록 원본 CSV
    products_path: Path = DATA_DIR / "products" / "products.csv"
    glossary_path: Path = DATA_DIR / "glossary.csv"
    feeds_dir: Path = DATA_DIR / "feeds"                  # 해외·국내 변경 원문 스냅샷
    reg_db_path: Path = DATA_DIR / "regulations.db"       # CSV를 검증해 만든 SQLite (생성물, 재생성 가능)
    app_db_path: Path = DATA_DIR / "app.db"               # Step 4: 제품·성분 원본 (화면에서 추가·수정)

    # ── Step 2: 외부 규제 원문 API ──
    federal_register_api: str = "https://www.federalregister.gov/api/v1"
    law_api_oc: str | None = None      # 법제처 Open API 사용자 ID(OC). 없으면 국내 실시간 조회 비활성
    http_timeout_s: float = 20.0

    # ── Step 3a: LLM ──
    llm_backend: Literal["fake", "ollama", "openai"] = "fake"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_fast_model: str = "qwen3:8b"         # 분류·계획 (짧고 정형적인 작업)
    ollama_quality_model: str = "qwen3:8b"      # 요약·번역·작성·검토
    openai_fast_model: str = "gpt-4o-mini"
    openai_quality_model: str = "gpt-4o"
    llm_timeout_s: float = 180.0
    # 비용 비교용 가정 단가 (USD / 1K tokens). 실제 요금표가 아니다.
    fast_usd_per_1k: float = 0.00015
    quality_usd_per_1k: float = 0.005
    tool_timeout_s: float = 30.0

    # ── Step 4: API ──
    pipeline_version: Literal["v2", "baseline"] = "v2"      # baseline = Before(LLM 단독)
    checkpoint_db_path: Path = DATA_DIR / "checkpoints.db"  # 대화·승인 대기 상태 (재시작해도 유지)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """설정을 한 번만 읽고 재사용한다."""
    return Settings()
