# 백엔드 (FastAPI + LangGraph + MCP 서버 3개)
# MCP 서버는 백엔드가 같은 Python으로 stdio 자식 프로세스로 띄우므로 이미지 하나로 충분하다.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.0 /uv /usr/local/bin/uv

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# 의존성 먼저 (소스가 바뀌어도 이 층은 캐시)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY mcp_servers ./mcp_servers
COPY scripts ./scripts
COPY data ./data
# 관리자 페이지의 품질 평가 탭 (Before/After 결과)
COPY docs/experiments ./docs/experiments

# 규제 DB는 CSV(공식 원본에서 가져온 목록)로 이미지 빌드 시 생성 — 데이터 검증에 실패하면 빌드가 멈춘다
RUN python scripts/build_reg_db.py

# 계속 남아야 하는 데이터(제품·대화·피드백·실행 기록·정기 브리핑)는 볼륨에
ENV APP_DB_PATH=/app/state/app.db \
    CHECKPOINT_DB_PATH=/app/state/checkpoints.db
VOLUME /app/state

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
