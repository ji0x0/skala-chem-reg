"""질문 하나를 그래프로 실행하고 진행 이벤트를 출력한다 (API·화면 없이 확인용).

    uv run python scripts/run_graph.py "안녕, 뭘 할 수 있어?"
    LLM_BACKEND=ollama uv run python scripts/run_graph.py "79-01-6 미국 규제 대상이야?"
    LLM_BACKEND=ollama uv run python scripts/run_graph.py --approve "이번 주 미국 EPA 규제 브리핑해줘"

MCP 서버 3개는 실제 프로세스(stdio)로 띄운다. 상태 저장은 메모리(InMemorySaver)를 쓴다.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.agents.deps import AgentDeps  # noqa: E402
from app.agents.baseline import build_baseline_graph  # noqa: E402
from app.agents.graph import build_graph  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.llm.langchain_llm import build_llm  # noqa: E402
from app.tools.provider import MCPToolProvider  # noqa: E402

SHOW = {"node_start", "route", "plan", "agent_start", "agent_end", "tool_call_end", "review",
        "summary", "impact", "guard", "validation"}


def show(event: dict, started: float) -> None:
    kind = event["type"]
    if kind == "token":
        print(event["delta"], end="", flush=True)
    elif kind in SHOW:
        body = {k: v for k, v in event.items() if k != "type"}
        print(f"\n  {time.perf_counter() - started:6.1f}s [{kind}] {json.dumps(body, ensure_ascii=False)[:220]}")


async def run(graph, graph_input, config, started) -> None:
    async for mode, payload in graph.astream(graph_input, config, stream_mode=["custom", "updates"]):
        if mode == "custom":
            show(payload, started)
        elif "__interrupt__" in payload:
            value = payload["__interrupt__"][0].value
            print(f"\n  ⏸ 승인 대기: {json.dumps(value, ensure_ascii=False)[:300]}")


async def main(question: str, approve: bool, baseline: bool) -> None:
    settings = get_settings()
    tools = MCPToolProvider(settings)
    await tools.start()
    try:
        deps = AgentDeps(settings, build_llm(settings), tools)
        await deps.load_catalog()
        graph = (build_baseline_graph if baseline else build_graph)(deps, InMemorySaver())
        config = {"configurable": {"thread_id": "cli"}}
        started = time.perf_counter()
        print(f"[질문] {question}  (LLM: {deps.llm.quality_name}, {'Before: LLM 단독' if baseline else 'v2'})")
        await run(graph, {"question": question}, config, started)
        if (await graph.aget_state(config)).next and approve:
            print("\n  ▶ 승인으로 재개")
            await run(graph, Command(resume={"approved": True, "comment": "CLI 승인"}), config, started)
        values = (await graph.aget_state(config)).values
        usage = values.get("usage", [])
        print(f"\n\n[완료] {time.perf_counter() - started:.1f}s · 토큰 {sum(u['tokens'] for u in usage):,} "
              f"· 근거 {len(values.get('citations', []))}개")
    finally:
        await tools.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--approve", action="store_true", help="승인 대기에서 자동 승인")
    parser.add_argument("--baseline", action="store_true", help="Before(LLM 단독) 그래프로 실행")
    args = parser.parse_args()
    asyncio.run(main(args.question, args.approve, args.baseline))
