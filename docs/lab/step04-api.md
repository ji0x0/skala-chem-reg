# Step 4 — FastAPI REST + SSE

## 목표
Step 3b 그래프를 HTTP로 노출한다. 질문은 SSE로 진행 상황·토큰을 흘려보내고, 승인은 별도 API로 이어서 실행한다.
제품 관리(R54)·규제 목록(R55) API를 함께 만들고, 제품은 이번 단계부터 **앱 DB(`data/app.db`)가 원본**이다.

```
Vue(:5173) ──CORS──▶ FastAPI(:8000) ── lifespan 싱글턴 AgentService
                       ├ /api/v1/chat/stream        ─▶ graph.astream ─▶ convert ─▶ SSE
                       ├ /api/v1/threads/{id}        ─▶ 체크포인터(SQLite)에서 상태 조회
                       ├ /api/v1/threads/{id}/approval ─▶ Command(resume) ─▶ SSE
                       ├ /api/v1/products (GET·POST·PUT) ─▶ ProductDB ─▶ 판정 코어
                       └ /api/v1/regulations, /substances ─▶ RegDB
                                      MCP 서버 3개 (stdio 자식 프로세스, 연결 유지)
```

## 만드는 파일

| 파일 | 역할 | 캡스톤 연결 |
| --- | --- | --- |
| `app/domain/products.py` | 제품·성분 Pydantic 모델 + 업무 규칙 검증 (CAS, 중복, 함량 합계 100±0.5) | Wave 2 구조화 |
| `app/repositories/product_db.py` | 제품 저장소 (CSV로 최초 1회 채움, 추가·수정은 한 트랜잭션) | Wave 13 저장소 분리 |
| `app/repositories/reg_db.py` (수정) | 제품 조회를 ProductDB에 위임 | — |
| `scripts/build_reg_db.py` (수정) | 규제 DB만 빌드, 제품 CSV는 검증만 → 재빌드해도 사용자 제품 보존 | — |
| `mcp_servers/_common.py` (수정) | MCP 서버도 앱 DB의 제품을 읽음 | — |
| `app/streaming/events.py` | SSE 이벤트 스키마 (화면과의 약속) | Wave 11 스트리밍 |
| `app/streaming/sse.py`, `converter.py` | `event:`/`data:` 직렬화, 그래프 이벤트 → 스키마 변환 | Wave 11 |
| `app/service.py` | AgentService: LLM·MCP·체크포인터·그래프를 한 번 만들고 공유, 대화별 잠금 | Wave 12 서비스 계층 |
| `app/api/schemas.py`, `chat.py`, `products.py`, `regulations.py` | REST 라우터 | Wave 12 FastAPI |
| `app/main.py` | `create_app()`, lifespan, CORS 허용 출처 명시 | Wave 12, R49 CORS |
| `scripts/run_backend.sh`, `.claude/launch.json` | 백엔드 실행 | — |
| `tests/test_products.py`, `tests/test_api.py` | 저장소 규칙, API·SSE·승인 흐름 (fake LLM + 메모리 MCP) | Wave 13 테스트 |

## API 목록

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/api/v1/health` | 파이프라인·모델·도구·제품/물질 수 |
| POST | `/api/v1/chat/stream` | 질문 → SSE (`thread_id` 비우면 새 대화) |
| GET | `/api/v1/threads/{id}` | 대화 상태, 승인 대기 여부, 근거 |
| POST | `/api/v1/threads/{id}/approval` | 승인·반려 → SSE로 이어서 실행 (대기 중 아니면 409) |
| POST | `/api/v1/feedback` | 👍/👎 (Step 6에서 LangSmith 연동) |
| GET·POST | `/api/v1/products` | 목록(판정 요약 포함) / 추가(검증 실패 422 + 오류 목록) |
| GET·PUT | `/api/v1/products/{id}` | 상세+판정 / 수정(성분 전체 교체) |
| GET | `/api/v1/regulations`, `/regulations/{id}` | 규제 목록(등재 수·미검증 수), 규제별 등재 물질 |
| GET | `/api/v1/substances?q=` | 물질 검색 → 등재 규제 + 함유 제품 |

## SSE 이벤트 순서

```
run_started → (progress | tool_call_start | tool_call_end | token)* → (approval_required | final) → done
오류: error → done(status=failed)
```

`final`에는 `citations`(원문·번역·출처·기준일·검증 상태, R56)와 `usage`(토큰·비용 환산)가 들어 있다.

## 설계 포인트
- **싱글턴**: MCP 프로세스·체크포인터·컴파일된 그래프는 lifespan에서 한 번만 만든다. 종료 시 `AsyncExitStack`이 정리
- **의존성 주입**: `create_app(settings, llm=..., tools=..., checkpointer=...)` → 테스트는 fake LLM + 메모리 MCP로 결정론적 실행
- **체크포인터**: `AsyncSqliteSaver`(`data/checkpoints.db`) → 서버를 재시작해도 승인 대기 대화를 이어서 승인할 수 있다
- **대화별 잠금**: 같은 `thread_id`에 동시 요청이 오면 두 번째는 `error` + `done(failed)`. 다른 대화끼리는 병렬
- **스트림 중간 오류**: 예외를 HTTP 500으로 끊지 않고 `error` 이벤트로 알린 뒤 `done`으로 정상 종료
- **CORS**: `CORS_ORIGINS`에 적힌 출처만 허용 (`*` 금지), 메서드 GET/POST/PUT
- **제품 저장 후**: `refresh_catalog()`로 에이전트의 제품 ID 목록을 갱신 → 새로 추가한 제품을 바로 질문할 수 있다

## 따라 하기

```bash
uv add fastapi "uvicorn[standard]"
uv add --dev httpx
```

## 확인

1) 테스트

```bash
uv run pytest -q
```

```
64 passed
```

2) 서버 실행 (다른 터미널, `.env`의 `LLM_BACKEND=ollama`)

```bash
bash scripts/run_backend.sh
```

브라우저에서 http://127.0.0.1:8000/docs 를 열면 Swagger UI로 모든 API를 직접 호출해 볼 수 있다.

3) 상태·조회 API

```bash
curl -s http://127.0.0.1:8000/api/v1/health
```

```bash
curl -s "http://127.0.0.1:8000/api/v1/substances?q=트리클로로에틸렌"
```

→ EU SVHC · KR 특별관리물질 · US TSCA 제6조 · EU CLP 등재, 함유 제품 `P003`

4) 제품 검증 실패 (의도된 422)

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/products -H 'content-type: application/json' -d '{"product_name":"테스트","product_form":"mixture","export_regions":["EU"],"ingredients":[{"cas":"71-43-3","ingredient_name":"오타","role":"주원료","wt_pct":70}]}'
```

```
{"detail":{"message":"제품 정보가 규칙에 맞지 않습니다.","errors":["1번 성분 '오타': CAS 번호 오류 '71-43-3' (형식 또는 체크 디지트)","함량 합계 70 wt% — 100 ± 0.5 wt%여야 함"]}}
```

5) 질의응답 스트림 (lookup)

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/stream -H 'content-type: application/json' -d '{"message":"P002 규제 문제 있어?"}'
```

```
event: run_started
event: progress ...
event: tool_call_start  {"agent": "lookup", "tool": "judge_product_compliance", ...}
event: tool_call_end    {"summary": "exceeds 2 · listed 2 · review 0 · below 3", ...}
event: token ×274
event: final            {"content": "제품 P002 저취 PVC 바닥재 (수출 EU)은 규제 문제 있습니다. ...", "citations": [4개]}
event: done             {"status": "completed"}
```

6) 브리핑 → 승인 대기 → 승인

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/stream -H 'content-type: application/json' -d '{"message":"TSCA 트리클로로에틸렌 최근 규제 동향 브리핑해줘","thread_id":"b-1"}'
```

```
progress ×22 · tool_call ×8 · token ×560
event: approval_required {"impacted_products": [{"product_id": "P003", "document_number": "2026-20964", "outcomes": ["listed", "review"]}], ...}
event: done              {"status": "awaiting_approval"}
```

```bash
curl -s http://127.0.0.1:8000/api/v1/threads/b-1
```

→ `awaiting_approval: true`, 근거 9개

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/threads/b-1/approval -H 'content-type: application/json' -d '{"approved":true,"comment":"P003 고객 공지 진행","approver":"규제담당"}'
```

→ `final`에 "## 승인 결과 — 규제담당: 승인 — 관련 부서에 공유 (P003 고객 공지 진행)", 근거 9개, 이어서 `done(completed)`.
같은 요청을 다시 보내면 **409** (승인 대기 항목 없음).

관찰 결과 (2026-10-20, Ollama qwen3:8b):

| 확인 | 결과 |
| --- | --- |
| lookup 1건 | 약 16초, 근거 4개 |
| 서로 다른 대화 2건 동시 | 2건 모두 32초에 완료, 판정·근거가 섞이지 않음 (P002 4개 / P006 3개) |
| 같은 대화 동시 2건 | 두 번째 요청 `error: 이 대화에서 이미 처리 중인 요청이 있습니다.` + `done(failed)` |
| 브리핑 | 106초, 승인 대기 → 승인 후 최종본, 토큰 6,236 |
| 재승인 | 409 |
| 서버 로그 | 오류·경고 없음 |

> `usage.usd`는 설정의 단가(`FAST_USD_PER_1K`, `QUALITY_USD_PER_1K`)로 환산한 **참고 비용**이다. Ollama 로컬 실행은 실제 과금이 없다.

## 다음 단계
Step 5에서 Vue 화면을 만든다: 브리핑·질의응답(SSE 진행 표시, 근거 원문·번역·출처), 승인 버튼, 제품 관리, 규제 목록.
