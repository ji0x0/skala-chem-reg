# Base Agent 분석 (`all_total_vue_student`)

2단계 결과. Base 코드를 읽고 `fake` 백엔드로 실제 기동해 확인한 내용이다.
요구사항별 구현 여부는 [REQUIREMENTS.md](../REQUIREMENTS.md)의 `Base` 열에 반영했다 (✅ 17 / 🔺 15 / ❌ 18).

## 1. 한눈에 보기

- **주제**: 운영 인시던트 대응 에이전트. "OO 서비스가 느려요" → 모니터링 조회 + 런북 조회 → 번호 절차로 대응 보고
- **규모**: Python 약 1,400줄 + Vue 단일 HTML. 테스트, 평가 코드 없음
- **LLM 백엔드**: `LLM_BACKEND=fake | ollama | openai` 환경변수로 교체
- **포트**: 백엔드 `:8100`, 프론트(프록시) `:8600`

```
브라우저(web_chat.html, Vue CDN)
  → web_demo_server.py :8600  (정적 파일 + /chat/stream 프록시 → CORS 회피)
    → server.py :8100  (FastAPI, lifespan 싱글턴)
      → agent/graph.py  (LangGraph StateGraph)
         route ─chat→ chat_answer → END
               └incident→ plan → gate → research ⇄ replan_check → analysis → write ⇄ validate → finalize
      → agent/mcp_client.py → mcp_server.py("ops": Tool/Resource/Prompt), mcp_server_docs.py("docs": decoy)
      → agent/session_store.py → session.db (SQLite)
      → LangSmith (@traceable 계층 트레이스)
```

## 2. 파일별 역할

| 파일 | 역할 | 캡스톤 대응 |
| --- | --- | --- |
| `server.py` | FastAPI. `lifespan`에서 MCP·LLM·세션·그래프 1회 생성. `/health`, `/version`, `POST /chat`, `GET /chat/stream` | Wave 1, 3, 12, 14 |
| `agent/graph.py` | 노드 10개, `AgentState`(TypedDict), `partial`로 deps 주입 | Wave 4~8, 10b, 13, 15 |
| `agent/deps.py` | `SupervisorDeps(fast_llm, quality_llm, mcp, session_store, version)` | Wave 13 |
| `agent/mcp_client.py` | stdio MCP 세션 2개, `find_prompt` / `find_resource_template`로 서버 탐색. 첫 Tool 호출은 일부러 Timeout | Wave 2, 9 |
| `agent/retry.py` | `asyncio.TimeoutError`만 지수 백오프 재시도 (0.3 → 0.9초, 최대 3회) | Wave 9 |
| `agent/session_store.py` | `thread_id`별 메시지를 SQLite에 저장 | Wave 12 |
| `agent/supervisor_v1.py` | 라우팅·게이트·검증 없는 legacy 파이프라인. `SUPERVISOR_VERSION=v1`로 롤백 | Wave 14 |
| `agent/fake_llm.py` / `ollama_llm.py` / `openai_llm.py` | 같은 인터페이스(`route`, `plan`, `analyze`, `chat`, `write`)의 LLM 3종. 프롬프트가 클래스 안에 하드코딩 | Wave 10a |
| `mcp_server.py` | Tool `get_monitoring_status`, Resource `runbook://incident-response/{type}`, Prompt `incident_analysis_prompt` | Wave 2 |
| `mcp_server_docs.py` | API 문서 Resource만 제공하는 decoy 서버 (에이전트는 사용 안 함) | Wave 2 멀티 서버 |
| `data/monitoring.json` | 시스템 6개 상태 (cpu/memory 기준값 + 알림) | |
| `data/runbooks/*.md` | 런북 6종 (각 5~7줄) | |
| `web_chat.html` | Vue 3 CDN 채팅 화면, `EventSource`로 SSE 수신, 진행 상태 표시 | Wave 3 |

## 3. 실행 확인 (fake 백엔드, 2026-10-20)

| 확인 | 결과 |
| --- | --- |
| `/health` | `creation_count=1`, 싱글턴 확인 |
| 인사 "안녕, 너는 누구야?" | `route=chat`, `task_count=0`, 즉시 응답 |
| SSE "web-01 CPU 급증" | `RouteDecided → PlanCreated → GateApplied(분석 task 1개 제거) → TaskCompleted(retries=1) → ReplanCheck(부족) → 런북 추가 조사 → ReplanCheck(충분) → AnalysisSkipped → DraftWritten#1 → Validation 불합격 → DraftWritten#2 → 합격 → FinalAnswer → [DONE]` |
| 재시작 후 "제 이름이 뭐였죠?" | "민수님이라고 말씀하셨어요" — SQLite 세션 유지 확인 |
| CORS preflight (`Origin: localhost:5173`) | `405 Method Not Allowed` — CORS 미들웨어 없음 |

## 4. 발견한 약점 (개선 후보)

실행과 코드 읽기로 확인한 것. **굵은 항목**은 실제로 재현했다.

| # | 약점 | 근거 | 관련 요구사항 |
| --- | --- | --- | --- |
| 1 | **증상과 다른 런북을 고른다.** "web-01 CPU 급증"에 DB Down 런북으로 답함 | `_classify_incident_type`이 쿼리가 아니라 모니터링 알림 키워드만 본다. web-01은 healthy(알림 0건)라 규칙에 안 걸려 `db-down`으로 폴백 | R19, RAG(PDF 예시 1) |
| 2 | **키워드 라우팅이 표현 변화에 약하다.** "결제 응답이 느려지고 CPU가 치솟았어요"가 `chat`으로 분류됨 | fake 라우터 정규식(`장애|진단|다운|지연|급증...`)에 "느려", "치솟" 없음. 실모델은 LLM이 판단하지만 파싱 실패 시 같은 정규식으로 폴백 | R16, R17 |
| 3 | 검증이 형식만 본다 | `validate_node`: 30자 이상 + `"1)"` 포함이면 합격. 내용·근거 일치는 보지 않음 | R20, R21 |
| 4 | 상한 도달 시 미달 사실을 숨긴다 | 3회째에 `"합격(최대 시도 도달 — 통과 처리)"`로 바꿔 그대로 전달. 사용자에게 안내 없음 | R23 |
| 5 | 병렬 조사가 사실상 직렬이다 | `MCPClient`가 모든 세션에 `asyncio.Lock` 하나를 공유. 병렬 효과는 노드의 인위적 `sleep(0.35)`에서만 나옴 | R30 |
| 6 | 하나만 실패해도 요청 전체가 실패한다 | `research_node`의 `asyncio.gather`에 task 단위 try/except 없음 | R26, R27 |
| 7 | async 노드 안의 블로킹 호출 | `ollama_llm` / `openai_llm`의 `route`, `plan`, `analyze`가 동기 `httpx.post` 사용 → 이벤트 루프 정지 | R32 |
| 8 | 하드코딩 | 프롬프트가 LLM 클래스 안 문자열, 시스템 미언급 시 `auth-service` 폴백, 런북 규칙 표 | R44, PDF 예시 7 |
| 9 | SSE 형식이 표준 이벤트명을 안 쓴다 | `data:`만 사용하고 `event:` 없음, 이벤트가 dict(Pydantic 아님), `[DONE]` 센티널. 변환 로직이 `server.py` 안에 섞임 | R10, R11 |
| 10 | 질문이 URL에 실린다 | `GET /chat/stream?message=...` — 길이 제한, 로그·히스토리에 질문 노출 | R09, R50 |
| 11 | 대화 상태가 메시지 기록뿐이다 | LangGraph 체크포인터가 아니라 별도 테이블. 그래프 중간 상태는 저장 안 됨. 최근 10턴만 사용, 요약 없음 | R33, PDF 예시 5 |
| 12 | 평가·피드백·테스트가 없다 | README는 Dataset 평가·Feedback을 언급하지만 학생 배포본에 `eval/`, `tests/` 없음 | R37, R41~R43 |
| 13 | 런북 데이터가 빈약하다 | 6종, 각 5~7줄. 의미 검색을 붙이기엔 데이터가 적음 | PDF 예시 8 |

## 5. 재사용할 것

- **구조**: `lifespan` 싱글턴, `SupervisorDeps` + `partial` 주입, LLM 3종 교체 구조, v1/v2 버전 토글
- **그래프 골격**: route → plan → gate → research → replan → analysis → write → validate → finalize
- **MCP 사용법**: Tool/Resource/Prompt 3종, 서버 탐색(`find_*`)
- **스트리밍 방식**: `astream(stream_mode=["updates", "custom"])` + `get_stream_writer()`로 토큰 전송
- **실행 스크립트**: venv, Ollama 준비, 백엔드별 LangSmith 프로젝트 분리
- **회귀 쿼리**: `doc/regression_test_queries.md` 10개 → Before/After 측정 입력으로 사용

Base에 있지만 REQUIREMENTS.md에 없던 패턴: **v1/v2 버전 토글(Wave 14)**과 **research 가드(Wave 15, 실행할 목록을 검사)**. 같이 가져간다.

## 6. 다음 단계에 주는 시사점

- ✅ 17개는 Base 구조를 가져오면 바로 확보된다. 개발 시간은 🔺 15개와 ❌ 18개에 쓴다
- 약점 1, 2, 3, 5는 **같은 입력으로 Before/After 수치를 내기 좋다** (런북 정확도, 라우팅 정확도, 검증 점수, 조사 소요 시간)
- 4단계에서 새 주제를 고르더라도 위 구조는 그대로 옮길 수 있다. 주제를 바꾸면 MCP 서버, 데이터, 프롬프트가 바뀌는 범위다

## 참고

- 실행: `bash sh/setup_venv.sh` 후 `LLM_BACKEND=fake .venv/bin/python3 server.py` (Ollama, API 키 없이 동작)
- Ollama 모드는 아직 실행하지 않음 (`qwen3:0.6b`/`8b` 필요, Ollama 서버 꺼져 있음)
