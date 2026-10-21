"""도구 제공자 — 에이전트는 이 인터페이스로만 MCP 도구를 부른다.

- MCPToolProvider (실서비스): MCP 서버 3개를 stdio 자식 프로세스로 띄우고, 서버 수명 동안 세션을
  유지한다 (FastAPI lifespan에서 한 번 시작). MultiServerMCPClient로 여러 서버를 묶는다.
- InMemoryToolProvider (테스트): 같은 서버 객체에 메모리 안에서 MCP 프로토콜로 연결한다 (프로세스 없음)

두 제공자 모두 오류를 ToolError로 바꾼다. 에이전트는 어느 쪽인지 모른다 (의존성 주입).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from contextlib import AsyncExitStack
from typing import Any, Protocol

from app.core.config import ROOT_DIR, Settings

log = logging.getLogger(__name__)

SERVERS = ("product", "reg_db", "reg_feed")


class ToolError(Exception):
    """도구 호출 실패. transient=True면 잠시 뒤 재시도할 가치가 있는 오류(시간 초과 등)."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class ToolProvider(Protocol):
    async def call(self, name: str, args: dict[str, Any]) -> Any: ...
    async def get_prompt(self, name: str, args: dict[str, str]) -> str: ...
    async def read_resource(self, uri: str) -> str: ...
    def tool_names(self) -> list[str]: ...


async def call_with_retry(provider: ToolProvider, name: str, args: dict, *, retries: int = 3,
                          base_delay: float = 0.5, timeout: float = 30.0) -> tuple[Any, int]:
    """일시적 오류(시간 초과)만 지수 백오프로 재시도한다: 0.5초 → 1.5초.
    잘못된 인자 같은 영구 오류는 바로 올린다. (결과, 재시도 횟수)를 돌려준다."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return await asyncio.wait_for(provider.call(name, args), timeout), attempt - 1
        except (asyncio.TimeoutError, TimeoutError) as exc:
            if attempt >= retries:
                raise ToolError(f"{name} 시간 초과 ({retries}회 시도)", transient=True) from exc
        except ToolError as exc:
            if not exc.transient or attempt >= retries:
                raise
        await asyncio.sleep(base_delay * (3 ** (attempt - 1)))


def _as_value(content: Any) -> Any:
    """MCP 도구 결과(content block 목록 또는 문자열)를 파이썬 값으로."""
    if isinstance(content, list):
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    return content


class MCPToolProvider:
    """MCP 서버 3개에 지속 세션으로 연결한다 (MultiServerMCPClient + load_mcp_tools)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._stack: AsyncExitStack | None = None
        self._sessions: dict[str, Any] = {}
        self._tools: dict[str, Any] = {}

    def _connections(self) -> dict[str, dict]:
        # 자식 프로세스는 부모의 환경변수를 다 받지 않는다 (MCP 기본값: HOME·PATH 등만). 로컬에선 서버가 .env를
        # 직접 읽어 드러나지 않았지만, Docker엔 .env 파일이 없어 키·DB 경로가 빠졌다 → 백엔드 설정을 명시적으로 넘긴다
        s = self.settings
        env = {"FASTMCP_LOG_LEVEL": "ERROR", "PYTHONPATH": str(ROOT_DIR),
               "APP_DB_PATH": str(s.app_db_path), "REG_DB_PATH": str(s.reg_db_path), "FEEDS_DIR": str(s.feeds_dir),
               "FEED_MODE": s.feed_mode, "HTTP_TIMEOUT_S": str(s.http_timeout_s),
               "LAW_API_OC": s.law_api_oc or ""}          # 빈 값도 넘긴다 (서버가 .env의 키를 대신 읽지 않게)
        return {name: {"transport": "stdio", "command": sys.executable,
                       "args": [str(ROOT_DIR / "mcp_servers" / f"{name}_server.py")], "env": env}
                for name in SERVERS}

    async def start(self) -> None:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools

        started = time.perf_counter()
        client = MultiServerMCPClient(self._connections())
        self._stack = AsyncExitStack()
        # client.session()으로 연 세션을 계속 쓴다. get_tools()를 세션 없이 쓰면 호출마다
        # 서버 프로세스를 새로 띄운다 (1차 초안에서 확인한 문제)
        for name in SERVERS:
            session = await self._stack.enter_async_context(client.session(name))
            self._sessions[name] = session
            for tool in await load_mcp_tools(session):
                self._tools[tool.name] = tool
        log.info("MCP 연결", extra={"event": "mcp_ready",
                                   "latency_ms": int((time.perf_counter() - started) * 1000)})

    async def stop(self) -> None:
        if self._stack:
            await self._stack.aclose()
        self._stack, self._sessions, self._tools = None, {}, {}

    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"알 수 없는 도구: {name}")
        result = await tool.ainvoke(args)
        value = _as_value(result)
        # 어댑터는 도구 오류를 예외 대신 "Error calling tool ..." 문자열로 돌려준다 (1차 초안에서 확인)
        if isinstance(value, str) and value.startswith(("Error calling tool", "Error executing tool")):
            raise ToolError(value)
        return value

    async def get_prompt(self, name: str, args: dict[str, str]) -> str:
        result = await self._sessions["reg_db"].get_prompt(name, args)
        return result.messages[0].content.text

    async def read_resource(self, uri: str) -> str:
        result = await self._sessions["reg_db"].read_resource(uri)
        return result.contents[0].text


class InMemoryToolProvider:
    """테스트용: fastmcp.Client로 서버 객체에 메모리 안에서 연결한다 (MCP 프로토콜은 그대로)."""

    def __init__(self, fail_tools: set[str] | None = None):
        self.fail_tools = fail_tools or set()        # 장애 주입 테스트용
        self._stack: AsyncExitStack | None = None
        self._clients: dict[str, Any] = {}
        self._tool_server: dict[str, str] = {}

    async def start(self) -> None:
        from fastmcp import Client

        from mcp_servers import product_server, reg_db_server, reg_feed_server
        servers = {"product": product_server.mcp, "reg_db": reg_db_server.mcp,
                   "reg_feed": reg_feed_server.mcp}
        self._stack = AsyncExitStack()
        for name, server in servers.items():
            client = await self._stack.enter_async_context(Client(server))
            self._clients[name] = client
            for tool in await client.list_tools():
                self._tool_server[tool.name] = name

    async def stop(self) -> None:
        if self._stack:
            await self._stack.aclose()

    def tool_names(self) -> list[str]:
        return sorted(self._tool_server)

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        if name in self.fail_tools:
            raise ToolError(f"{name} 장애 주입")
        server = self._tool_server.get(name)
        if server is None:
            raise ToolError(f"알 수 없는 도구: {name}")
        try:
            result = await self._clients[server].call_tool(name, args)
        except Exception as exc:          # fastmcp는 도구 오류를 ToolError(예외)로 올린다
            raise ToolError(str(exc)) from exc
        return result.data if result.data is not None else _as_value(
            [c.model_dump() for c in result.content])

    async def get_prompt(self, name: str, args: dict[str, str]) -> str:
        result = await self._clients["reg_db"].get_prompt(name, args)
        return result.messages[0].content.text

    async def read_resource(self, uri: str) -> str:
        result = await self._clients["reg_db"].read_resource(uri)
        return result[0].text
