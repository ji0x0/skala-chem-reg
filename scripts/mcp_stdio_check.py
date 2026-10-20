"""MCP 서버 3개를 실제 프로세스(stdio)로 띄워 한 클라이언트로 동시에 연결해 본다.

    uv run python scripts/mcp_stdio_check.py

멀티 서버 설정에서는 도구 이름 앞에 서버 이름이 붙는다 (예: product_find_products_by_cas).
"""
import asyncio
import json
import sys
from pathlib import Path

from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
SERVERS = {name: {"command": sys.executable, "args": [str(ROOT / "mcp_servers" / f"{name}_server.py")],
                  "env": {"FASTMCP_LOG_LEVEL": "ERROR"}}
           for name in ("product", "reg_db", "reg_feed")}


async def main() -> None:
    async with Client({"mcpServers": SERVERS}) as client:
        tools = sorted(t.name for t in await client.list_tools())
        print(f"연결된 도구 {len(tools)}개:")
        for name in tools:
            print(f"  - {name}")

        # 시나리오: 관보 문서 → 언급 물질 → 우리 제품 → 판정
        doc = (await client.call_tool("reg_feed_get_federal_register_document",
                                      {"document_number": "2026-20964"})).data
        cas = [m["cas"] for m in doc["substance_mentions"]]
        print(f"\n[관보 {doc['document_number']} / {doc['source']}] {doc['title'][:70]}")
        print(f"  언급 물질: {[(m['name_ko'], m['mentions']) for m in doc['substance_mentions']]}")
        hits = (await client.call_tool("product_find_products_by_cas", {"cas_numbers": cas})).data
        print(f"  영향 후보 제품: {sorted({h['product_id'] for h in hits})}")
        for pid in sorted({h["product_id"] for h in hits}):
            judged = (await client.call_tool("reg_db_judge_product_compliance", {"product_id": pid})).data
            us = [f for f in judged["findings"] if f["region"] == "US"]
            print(f"  {pid} {judged['product_name']}: 미국 판정 " +
                  json.dumps([(f["substance"], f["outcome"]) for f in us], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
