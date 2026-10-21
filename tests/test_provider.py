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
    assert len(tools.tool_names()) == 12
    judged = await tools.call("judge_product_compliance", {"product_id": "P003"})
    # 미국 불순물 2건 + 국내 제한물질(TCE·PCE: 가정용 세정제·에어러졸 용도만 금지) 2건 — 용도 확인 필요
    assert judged["summary"]["review"] == 4
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


def test_mcp_servers_get_backend_settings(tmp_path):
    """Docker엔 .env 파일이 없다 → 자식 프로세스(MCP 서버)에 DB 경로·수집 방식·법제처 키를 명시적으로 넘긴다."""
    from app.core.config import Settings
    from app.tools.provider import MCPToolProvider
    s = Settings(_env_file=None, app_db_path=tmp_path / "app.db", feed_mode="snapshot", law_api_oc=None)
    env = MCPToolProvider(s)._connections()["reg_feed"]["env"]
    assert env["APP_DB_PATH"] == str(tmp_path / "app.db") and env["FEED_MODE"] == "snapshot"
    assert env["LAW_API_OC"] == ""                     # 키가 없으면 빈 값 — 서버가 .env의 키를 대신 읽지 않게
