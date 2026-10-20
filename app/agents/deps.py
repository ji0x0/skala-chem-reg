"""의존성 주입 — 노드 함수는 필요한 것을 전부 AgentDeps로 받는다.

노드는 모듈 전역 변수나 closure에 기대지 않는다. 그래서 노드 파일을 옮기거나, 테스트에서
FakeLLM·InMemoryToolProvider로 바꿔 끼워도 같은 코드가 돈다 (캡스톤 모듈화 실습).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import Settings
from app.llm.base import AgentLLM
from app.tools.provider import ToolProvider


@dataclass
class AgentDeps:
    settings: Settings
    llm: AgentLLM
    tools: ToolProvider
    substances: list[dict] = field(default_factory=list)   # 규제 DB 전체 물질 (이름 매칭용, 시작 시 1회 조회)
    product_ids: list[str] = field(default_factory=list)

    async def load_catalog(self) -> None:
        """서버 시작 시 한 번: 이름 매칭에 쓸 물질 목록과 제품 ID를 받아 둔다."""
        found = await self.tools.call("lookup_substance", {"keyword": ""})
        self.substances = found["substances"]
        self.product_ids = [p["product_id"] for p in await self.tools.call("list_products", {})]
