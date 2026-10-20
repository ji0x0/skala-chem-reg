"""Step 3a — 도구 제공자: MCP 프로토콜 호출, 오류 변환, 재시도, 장애 주입."""
import asyncio

import pytest

from app.tools.provider import InMemoryToolProvider, ToolError, call_with_retry


@pytest.fixture
async def tools():
    provider = InMemoryToolProvider()
    await provider.start()
    yield provider
    await provider.stop()


async def test_calls_tools_prompt_resource(tools):
    assert len(tools.tool_names()) == 11
    judged = await tools.call("judge_product_compliance", {"product_id": "P003"})
    assert judged["summary"]["review"] == 2
    assert "숫자·CAS·날짜" in await tools.get_prompt("briefing_procedure", {"period": "최근 7일"})
    assert "TSCA" in await tools.read_resource("regulation://US_TSCA_S6")


async def test_tool_error_is_permanent_and_not_retried(tools):
    with pytest.raises(ToolError, match="등록되지 않은 제품"):
        await call_with_retry(tools, "get_product", {"product_id": "P999"}, base_delay=0)


async def test_timeout_is_retried_then_fails():
    class Slow:
        calls = 0

        async def call(self, name, args):
            Slow.calls += 1
            await asyncio.sleep(1)

    with pytest.raises(ToolError, match="시간 초과") as exc:
        await call_with_retry(Slow(), "x", {}, retries=3, base_delay=0, timeout=0.01)
    assert exc.value.transient and Slow.calls == 3


async def test_fault_injection():
    provider = InMemoryToolProvider(fail_tools={"get_product"})
    await provider.start()
    with pytest.raises(ToolError, match="장애 주입"):
        await provider.call("get_product", {"product_id": "P001"})
    await provider.stop()
