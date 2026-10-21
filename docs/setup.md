# 설정·배포·운영 안내

README의 [빠른 시작](../README.md#빠른-시작) 다음 단계입니다. 실시간 수집, 관리자 페이지, Docker 배포, 정기 브리핑, 규제 DB 갱신, 평가를 다룹니다.

## 1. 환경 변수 (`.env`)

`cp .env.example .env`로 만든 뒤 필요한 줄만 바꿉니다. `.env`는 Git에 올라가지 않습니다.

| 항목 | 기본값 | 쓰임 |
| --- | --- | --- |
| `LLM_BACKEND` | `fake` | `fake`(규칙 기반, 키·모델 불필요) / `ollama`(로컬 모델) / `openai`(과금) |
| `FEED_MODE` | `live` | `live`: 미국 관보·법제처·EU Cellar를 실시간 조회 / `snapshot`: 저장본 `data/feeds/`만 사용 (네트워크 없음, 평가와 같은 입력) |
| `LAW_API_OC` | (비어 있음) | 법제처 Open API 인증키(신청할 때 정한 값). 비우면 국내 실시간 수집은 "확인하지 못한 항목"으로 안내 |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | **로컬 실행**용 Ollama 주소 (Docker는 아래 `DOCKER_OLLAMA_BASE_URL`) |
| `OLLAMA_FAST_MODEL` · `OLLAMA_QUALITY_MODEL` | `qwen3:8b` | 질문 이해·계획 / 요약·작성·검토에 쓰는 모델 |
| `OPENAI_API_KEY` · `OPENAI_FAST_MODEL` · `OPENAI_QUALITY_MODEL` | — · `gpt-4o-mini` · `gpt-4o` | `LLM_BACKEND=openai`일 때 |
| `ADMIN_TOKEN` | (비어 있음) | 관리자 페이지·API 토큰. 비우면 관리자 API가 닫힘 |
| `WEEKLY_SCHEDULE` · `WEEKLY_HOUR` | `false` · `9` | `true`면 매주 월요일 지정 시각(한국 시간) 이후 지난주 정기 브리핑 생성 (Docker 기본 `true`) |
| `LANGSMITH_TRACING` · `LANGSMITH_API_KEY` · `LANGSMITH_PROJECT` | `false` | 트레이스·👍/👎 피드백을 LangSmith에 기록 |
| `REG_UPDATES_DIR` | `data/regulations_updates` | 승인한 규제 DB 갱신을 두는 폴더 (Docker는 영구 볼륨) |

### 실시간 수집 켜기
`FEED_MODE=live`로 두면 미국 관보와 EU Cellar는 키 없이 조회됩니다. 국내 고시까지 받으려면 [법제처 Open API](https://open.law.go.kr)에서 인증키를 신청해 `LAW_API_OC`에 넣습니다.

## 2. 관리자 페이지

`.env`에 `ADMIN_TOKEN`을 넣고 백엔드를 다시 띄운 뒤, 같은 값을 입력하면 열립니다.

| 실행 방식 | 주소 |
| --- | --- |
| 로컬 (`run_frontend.sh`) | http://127.0.0.1:5173/admin.html |
| Docker | http://localhost:8080/admin/ |

탭: 운영 요약(처리량·비용·품질) · DB 갱신(승인·반려) · 피드백 · 품질 평가(Before/After) · 실행 기록. 사용자 화면에는 관리자 메뉴가 없고, 토큰 없이는 API가 열리지 않습니다.

## 3. Docker 배포

```bash
docker compose up -d --build
```

| 주소 | 내용 |
| --- | --- |
| http://localhost:8080 | 사용자 화면 (관리자 `/admin/`) |
| http://localhost:8000/docs | API 문서 |

| 구성 | 내용 |
| --- | --- |
| `backend` | FastAPI + LangGraph + MCP 서버 3개(같은 이미지에서 자식 프로세스). 규제 DB는 이미지 빌드 때 공식 목록 CSV로 생성 |
| `frontend` | Vite 빌드 결과를 nginx가 제공하고 `/api`를 백엔드로 넘김 (같은 출처라 CORS 불필요, SSE 버퍼링 끔) |
| 볼륨 `state` | 제품 DB·대화·피드백·실행 기록·정기 브리핑·승인한 DB 갱신 — 컨테이너를 다시 만들어도 유지 |

`.env`가 백엔드에 그대로 전달됩니다. `.env`만 바꿨다면 다시 빌드하지 않고 `docker compose up -d`로 컨테이너만 새로 만들면 됩니다. Docker에서는 `LLM_BACKEND`를 비우면 `ollama`, 정기 브리핑 스케줄러는 기본으로 켜집니다.

### Ollama 주소

컨테이너 안에서 `127.0.0.1`은 컨테이너 자신입니다. 그래서 Docker는 로컬용 `OLLAMA_BASE_URL`을 쓰지 않고 `DOCKER_OLLAMA_BASE_URL`을 씁니다.

| 실행 방식 | 설정 |
| --- | --- |
| 백엔드·Ollama 모두 로컬 | `OLLAMA_BASE_URL=http://127.0.0.1:11434` (기본값) |
| 백엔드는 Docker, Ollama는 호스트 | 설정 없음 — 기본값 `http://host.docker.internal:11434` |
| Ollama도 Compose 서비스로 | `DOCKER_OLLAMA_BASE_URL=http://ollama:11434` |

Ollama도 컨테이너로 띄울 때는 모델을 한 번 받아야 합니다 (볼륨 `ollama`에 남음).

```bash
docker compose --profile ollama up -d --build
```

```bash
docker compose exec ollama ollama pull qwen3:8b
```

문제가 있으면 백엔드 로그를 봅니다.

```bash
docker compose logs -f backend
```

## 4. 정기 브리핑

매주 월요일 지난주(월~일)의 미국 관보·국내 고시·EU 개정 법령을 같은 브리핑 그래프로 정리해 **정기 브리핑** 탭에 저장합니다. 담당자는 읽고 "검토 완료"로 표시합니다. 처음 실행하면 `data/weekly/`의 지난 3주 예시가 채워집니다.

스케줄러는 `WEEKLY_SCHEDULE=true`일 때만 돕니다(Docker 기본). 지난 주차를 직접 만들려면:

```bash
uv run python scripts/run_weekly.py --backfill 3
```

```bash
uv run python scripts/run_weekly.py --start 2026-10-12
```

## 5. 규제 DB 갱신 (감지 → 승인 → 반영)

규제 목록 DB는 확인일(2026-10-20) 기준입니다. 공식 원본이 개정되면 에이전트가 새 버전을 찾아 **후보**로 올리고, 담당자가 **승인해야** 반영됩니다.

1. 관리자 페이지 **DB 갱신** → **지금 확인** (또는 매주 정기 브리핑 뒤 자동)
2. 감시 목록(EU CLP 부속서 VI · REACH 부속서 XVII)의 최신 통합본을 받아 지금 DB와 행을 비교
3. 후보를 얹은 임시 DB로 전체 제품을 다시 판정 → **승인하면 바뀌는 판정**을 먼저 보여 줌
4. 승인 → DB를 한 번에 바꿔 끼움 / 반려 → 그대로

승인한 갱신은 `REG_UPDATES_DIR`에 남고, 서버가 시작할 때 DB에 다시 반영됩니다. 저장소의 원본 CSV는 바뀌지 않습니다. 그 밖의 목록(SVHC 후보 목록·국내·미국·중국·일본)은 `scripts/import_official_lists.py`나 수동 확인으로 갱신합니다.

예 (2026-10-21 확인): CLP 2027-01-01 기준 통합본에서 이산화티타늄 분류가 삭제됨 → P002·P004·P010의 CLP 판정이 사라짐. 적용 예정 판이라 반영 시점은 담당자가 판단합니다.

## 6. 테스트·평가

```bash
uv run pytest -q
```

```bash
cd frontend && npm test
```

Before(LLM 단독) vs After(에이전트) 평가 — 입력은 저장본으로 고정됩니다(`FEED_MODE=snapshot`).

```bash
LLM_BACKEND=ollama uv run python scripts/run_eval.py --judge
```

결과는 `docs/experiments/`에 Markdown·JSON으로 저장되고 관리자 페이지 **품질 평가** 탭에 보입니다. `.env`에 `LANGSMITH_TRACING=true`와 `LANGSMITH_API_KEY`를 넣고 `--langsmith`를 붙이면 Dataset과 실험도 LangSmith에 기록됩니다. 지표·채점 방식은 [Step 6 실습 문서](lab/step06-eval.md)에 있습니다.
