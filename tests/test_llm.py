"""Step 3a — LLM 계층 (Fake로 인터페이스 확인. 실모델 확인은 scripts/llm_smoke.py)."""
import pytest

from app.core.config import Settings
from app.llm.fake import FakeLLM
from app.llm.langchain_llm import build_llm


@pytest.fixture
def llm():
    return FakeLLM()


async def test_route_and_plan(llm):
    assert (await llm.route("이번 주 미국 EPA 규제 바뀐 거 브리핑해줘"))[0].route == "briefing"
    assert (await llm.route("79-01-6 미국에서 규제 대상이야?"))[0].route == "lookup"
    assert (await llm.route("안녕?"))[0].route == "chat"
    plan, usage = await llm.plan("최근 14일 미국이랑 EU, P003", "2026-10-20")
    assert plan.days == 14 and plan.regions == ["US", "EU"] and plan.product_ids == ["P003"]
    assert usage["tokens"] > 0 and usage["usd"] >= 0


async def test_streaming_callback(llm):
    pieces = []
    text, _ = await llm.write_briefing("q", "요약", "판정", "근거", None, on_token=pieces.append)
    assert "".join(pieces) == text and "## 할 일과 기한" in text


def test_backend_switch():
    assert isinstance(build_llm(Settings(_env_file=None, llm_backend="fake")), FakeLLM)
    real = build_llm(Settings(_env_file=None, llm_backend="ollama"))
    assert real.fast_name.startswith("ollama:") and real.quality_name.startswith("ollama:")
