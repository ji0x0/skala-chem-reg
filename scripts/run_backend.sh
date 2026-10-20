#!/usr/bin/env bash
# 백엔드(FastAPI :8000) 실행. MCP 서버 3개는 백엔드가 stdio 자식 프로세스로 띄운다.
#   bash scripts/run_backend.sh                    # .env 설정 사용
#   LLM_BACKEND=ollama bash scripts/run_backend.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f data/regulations.db ] || uv run python scripts/build_reg_db.py
lsof -ti:8000 | xargs kill 2>/dev/null || true
exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
