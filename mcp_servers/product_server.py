"""MCP 서버 ① product — 회사 제품·배합 조회 (Tool).

    uv run python mcp_servers/product_server.py      # stdio로 실행 (보통은 백엔드가 띄운다)
"""
try:
    from ._common import open_db          # 패키지로 import될 때 (테스트)
except ImportError:
    from _common import open_db           # 파일로 직접 실행될 때 (stdio)

from fastmcp import FastMCP

mcp = FastMCP(name="product")
db = open_db()


@mcp.tool()
def list_products() -> list[dict]:
    """회사 제품 목록(제품 ID, 이름, 형태, 수출 지역)을 조회합니다."""
    return db.products()


@mcp.tool()
def get_product(product_id: str) -> dict:
    """제품 하나의 배합(성분 CAS, 이름, 역할, 함량 wt%)을 조회합니다. product_id 예: P001"""
    product = db.product(product_id)
    if product is None:
        raise ValueError(f"등록되지 않은 제품입니다: {product_id}")
    return product


@mcp.tool()
def find_products_by_cas(cas_numbers: list[str]) -> list[dict]:
    """주어진 CAS 번호 중 하나라도 들어 있는 제품과 해당 성분을 찾습니다.
    규제 문서에 나온 물질이 우리 제품에 들어 있는지 확인할 때 씁니다."""
    return db.products_containing(cas_numbers)


if __name__ == "__main__":
    mcp.run(show_banner=False)
