"""MCP 서버 공통.

MCP 서버는 나중에 FastAPI가 stdio 자식 프로세스로 띄운다. 이때 작업 폴더가 달라도 `app` 패키지를
찾을 수 있도록 프로젝트 루트를 import 경로에 넣는다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.repositories.product_db import ProductDB  # noqa: E402
from app.repositories.reg_db import RegDB  # noqa: E402


def open_db() -> RegDB:
    """규제 DB + 제품 DB. 제품 DB가 비어 있으면 products.csv로 한 번 채운다."""
    s = get_settings()
    products = ProductDB(s.app_db_path)
    products.seed_if_empty(s.products_path)
    return RegDB(s.reg_db_path, products)
