#!/usr/bin/env bash
# 프론트엔드(Vue + Vite :5173) 실행. 백엔드(:8000)는 scripts/run_backend.sh로 먼저 띄운다.
#   bash scripts/run_frontend.sh
set -euo pipefail
cd "$(dirname "$0")/../frontend"
[ -d node_modules ] || npm install
curl -s --max-time 2 http://127.0.0.1:8000/api/v1/health >/dev/null \
  || echo "⚠ 백엔드(:8000)가 응답하지 않습니다. 화면은 열리지만 '백엔드 연결 안 됨'으로 표시됩니다."
lsof -ti:5173 | xargs kill 2>/dev/null || true
exec npm run dev
