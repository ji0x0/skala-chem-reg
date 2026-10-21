# Step 7 — 관리자 페이지

## 목표
규제대응 팀장(관리자 페르소나)이 **"얼마나 처리했고, 무엇을 승인·반려했고, 담당자 평가와 품질은 어떤가"**를 한 화면에서 본다.
사용자 화면과 분리된 페이지(`/admin/`)로 두고 관리자 토큰으로 잠근다. 노드·도구 호출 단위의 상세 추적은 LangSmith가 맡는다.

```
사용자 화면 (index.html)                     관리자 페이지 (admin.html, /admin/)
  질문·승인 ──▶ AgentService._run ──▶ 실행 기록 runs (app.db)  ◀── GET /api/v1/admin/*  (Bearer ADMIN_TOKEN)
  👍/👎   ──▶ feedback.jsonl + LangSmith                 ◀──┤
                                       docs/experiments/*.json ◀──┤  (Before/After)
                                       regulations.db         ◀──┘  (규제 데이터 상태)
```

## 만드는 파일

| 파일 | 역할 |
| --- | --- |
| `app/repositories/run_log.py` | 실행 기록 표 `runs`: 경로·상태·시간·토큰·비용·품질 검토·승인 대상·승인 결정. 경로별·날짜별 집계 |
| `app/service.py` (수정) | 요청이 끝날 때마다 기록 (기록 실패가 응답을 막지 않음), 피드백을 실행 기록과 연결 |
| `app/api/admin.py` | `/api/v1/admin/overview·runs·approvals·feedback·evaluations` + 토큰 검사 |
| `app/core/config.py`, `app/main.py` (수정) | `ADMIN_TOKEN`, 평가 결과 폴더, 라우터 등록, CORS `Authorization` 허용 |
| `frontend/admin.html`, `src/admin/` | 관리자 전용 페이지 (잠금 화면 + 탭 5개), 관리자 API 모듈 |
| `frontend/vite.config.js`, `nginx.conf` (수정) | 진입점 2개로 빌드, `/admin/` 경로 |
| `Dockerfile`, `.dockerignore`, `docker-compose.yml` (수정) | 평가 결과를 이미지에 포함, `ADMIN_TOKEN` 전달 |
| `tests/test_admin.py`, `src/admin/admin.test.js` | 토큰 잠금, 질문·승인·피드백 기록, 평가 결과 |

## 설계 포인트
- **사용자 화면과 분리**: 같은 빌드의 다른 HTML. 사용자 화면 메뉴에 없고, 데이터는 API가 토큰을 확인한 뒤에만 준다 (화면을 숨기는 것만으로는 보안이 아니다)
- **기본 잠금**: `ADMIN_TOKEN`이 비어 있으면 관리자 API 전체가 503. 토큰 비교는 `hmac.compare_digest`
- **토큰 보관**: `sessionStorage` — 탭을 닫으면 지워진다. 저장소가 막힌 브라우저에서는 메모리에만
- **사용량은 한 턴에 한 번**: 브리핑은 승인 대기에서 멈췄다가 승인 후 끝난다. 사용량은 `final` 이벤트에만 실어 기록하므로 승인 대기 실행은 0, 승인 실행에 한 턴 전체가 잡힌다 (이중 계산 방지)
- **품질 검토 통과율은 브리핑 질문에만**: 승인 실행에도 같은 검토 결과가 상태에 남아 있어 그대로 쓰면 두 번 센다
- **비용은 비교용 가정 단가**: 로컬 모델은 요금이 없다. 화면에 "실제 요금이 아님"을 적는다
- **LangSmith와 역할 분리**: 앱은 업무 기록(처리량·승인·피드백), LangSmith는 실행 추적(노드·도구·프롬프트). 관리자 페이지에서 LangSmith로 바로 이동

## 따라 하기

`.env`에 관리자 토큰을 넣는다 (값은 아무 긴 문자열):

```bash
python -c "import secrets;print(secrets.token_urlsafe(24))"
```

```
ADMIN_TOKEN=<위에서 만든 값>
```

```bash
uv run pytest -q tests/test_admin.py
```

```bash
bash scripts/run_backend.sh
```

```bash
bash scripts/run_frontend.sh
```

http://127.0.0.1:5173/admin.html → 토큰 입력. 사용자 화면(http://127.0.0.1:5173)에서 질문·브리핑 승인·👍를 해 본 뒤 관리자 페이지의 **새로고침**.

Docker:

```bash
docker compose up --build
```

http://localhost:8080/admin/

## 결과 (Docker, Ollama qwen3:8b)
- 조회 1건(12.4초) + 브리핑 1건(80.7초) → 승인 → 👍 1건: 처리 요청 3 · 대화 2 · 승인 1 · 품질 검토 통과율 100% · 토큰 7,498
- 토큰 없이 `/api/v1/admin/overview` → 401, 토큰 설정이 비어 있으면 503
- 품질 평가 탭: `docs/experiments/` 3회 측정 중 선택해 Before/After 비교 (After가 나은 지표는 초록)

![관리자 페이지](../images/admin.jpg)

## 실제로 겪은 문제
- **Dockerfile 줄 끝 주석** — `COPY docs/experiments ./docs/experiments   # 설명`을 Docker가 복사할 파일 이름으로 읽어 `"/관리자": not found`. Dockerfile 주석은 줄 맨 앞 `#`만 → 주석을 윗줄로
- **빌드가 `DeadlineExceeded`로 실패** — BuildKit이 ghcr.io 이미지 정보를 받다가 시간 초과. `docker pull`로 기반 이미지를 먼저 받은 뒤 다시 빌드
- **기록이 없을 때 품질 통과율 "0%"** — SQL `AVG`가 NULL인 것을 0으로 바꿨음 → "기록 없음(—)"으로 구분
- 자세한 내용: [troubleshooting.md](../../troubleshooting.md)
