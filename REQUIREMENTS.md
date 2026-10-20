# 캡스톤 적용 요구사항

AI capstone 강의 요약과 실습 자료 전체를 이 프로젝트의 요구사항으로 옮긴 문서.
**모든 항목을 프로젝트에 적용하는 것이 목표**이며, 각 항목은 "어떻게 검증하는가"까지 갖는다.

- 출처
  - 강의 요약 (§1~§14)
  - 실습 안내: FastAPI, MCP, SSE, Query Routing, LangSmith (`example/AI capstone 실습/*.md`)
  - 나머지 실습: Wave 8 Validator, 10a 비용, 10b 병렬, 12 Stateless 세션, 13 모듈화 (`skala-ai_capstone/AICapstone_나머지_실습.zip`)
  - 미니프로젝트 안내 메모: 상용 서비스 구성, AJAX, CORS (2026-10-20)
  - 실습 교수님 가이드라인 (2026-10-20): 아래 "0-1" 참고
- `Base` 열: `all_total_vue_student` 구현 여부 (✅ 이미 있음 / 🔺 부분 / ❌ 없음). 근거는 [docs/base-analysis.md](docs/base-analysis.md)

---

## 1. 캡스톤에서 가져올 개발 프로세스

모든 실습은 같은 형식을 따른다. 이 프로젝트의 기능도 같은 방식으로 개발한다.

```
문제 정의 → 나이브(Before) 구현/측정 → 개선(After) 구현 → 같은 입력으로 재측정 → 비교표 → 한계·트레이드오프 기록
```

| 실습 원칙 | 프로젝트 적용 |
| --- | --- |
| 나이브와 개선을 **둘 다** 실행 가능하게 남긴다 | 설정 플래그나 별도 엔트리포인트로 Before/After 전환 가능하게 구현 |
| "숫자가 아니라 패턴"을 확인한다 | 비교표에 판정 기준(✅/❌)을 함께 적는다 |
| 실제 실행 결과만 기록한다 | `docs/experiments/`에 실행 명령, 원본 출력, 비교표를 남긴다 |
| LLM 판단은 비결정적이다 | 라우팅·계획 등은 N회 반복 실행해 안정성을 표로 남긴다 |
| 실습용 가정값을 구분한다 | 단가·부하 등 가정값은 "가정"이라고 명시한다 |

평가 항목 연결: **Before/After 실측(+10)**, **한계·트레이드오프(20)**, **발표 흐름(문제 → 개선 → 수치 → 한계)**

---

## 2. 요구사항 체크리스트

### 0. 서비스 구성 (상용 서비스 기준)

최종 결과물은 상용 서비스처럼 세 부분으로 구성한다.

| 구성 | 역할 | 이 프로젝트에서 |
| --- | --- | --- |
| 사용자 프론트엔드 | 사용자가 질문하고 진행 상황과 답변을 보는 화면 | Vue 채팅 UI (Base 제공 화면 기반) |
| 백엔드 API | 요청 처리, 에이전트 실행, 스트리밍 | FastAPI |
| 관리자 대시보드 | 실행 기록, 지연, 비용, 평가 확인 | LangSmith (Project, Trace, Feedback, Experiment) |

### 0-1. 실습 교수님 가이드라인 (필수 조건)

> 최종 목표: **상용 서비스 수준의 LLM 서비스**. 주어진 시간 2일, 개인 목표는 Day2까지 코드 완성.

| 가이드라인 | 이 프로젝트에서 | 관련 요구사항 |
| --- | --- | --- |
| 서비스 아키텍처 | 프론트엔드 / 백엔드 API / MCP 서버 / 저장소 / 관리자 대시보드 구성도와 ADR | R01, 0번 표 |
| LangChain + LangGraph + LangSmith 멀티에이전트 | LangChain(모델, 프롬프트, 구조화 출력, 도구) + LangGraph(Supervisor, 서브에이전트, 체크포인터) + LangSmith(트레이스, 평가, 피드백) | R13~R15, R40~R44, R51 |
| MCP (직접 만들거나 가져오기) | 직접 만든 MCP 서버 + 공개 MCP 서버 1개 이상 연결 검토 | R04~R08, R53 |
| REST API 기반 FastAPI | 리소스 단위 REST 엔드포인트 + Pydantic 스키마 + OpenAPI 문서 | R02, R03, R49 |
| 사용자 프론트엔드 Vue.js | Vue 화면 (채팅, 진행 상황, 승인, 피드백) | R12, R50 |
| 응답 대기는 스트리밍 | SSE 스트리밍 | R09~R11 |
| 스텝 바이 스텝(핸즈온 랩)으로 완성 | 단계별로 실행 가능한 상태를 쌓아 가며 개발하고, 단계마다 따라 할 수 있는 실습 문서를 남김 | R52 |

### A. 설계 기록

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R01 | ADR 작성 | `docs/adr/NNNN-제목.md`. 문제, 비교한 대안, 선택, 감수한 단점을 기록. 최소 대상: 스트리밍 방식, 멀티에이전트 구조, 체크포인터 저장소, 모델 분리, MCP Tool/Resource 구분 | ADR 5건 이상 | §2 | ❌ |

### B. API 서버 (FastAPI)

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R02 | FastAPI + Uvicorn + Pydantic | 요청/응답/이벤트를 모두 Pydantic 모델로 정의 | `/docs`에서 스키마 확인 | §3 | 🔺 |
| R49 | CORS 미들웨어 | 프론트엔드와 백엔드는 출처(포트)가 다르므로 FastAPI `CORSMiddleware`로 허용 출처를 명시. 운영 기준으로 `*` 대신 프론트 출처만 허용 | 브라우저에서 CORS 에러 없이 호출, 허용 외 출처 차단 확인 | 안내 메모 | ❌ |
| R03 | lifespan 싱글턴 | 그래프, LLM, MCP 클라이언트, 체크포인터를 `lifespan`에서 1회 생성해 `app.state`에 저장하고 종료 시 정리 | 요청 2회에서 `instance_id` 동일, `creation_count=1`. 첫 요청 지연 Before/After 비교 | §3, FastAPI 실습 | ✅ |

### C. MCP

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R04 | FastMCP 서버 | 도메인 데이터를 제공하는 MCP 서버 구현 | MCP Inspector로 직접 호출 | §4, MCP 실습 | ✅ |
| R05 | Tool / Resource / Prompt 3종 | Tool: 시점마다 바뀌는 조회와 행위. Resource: 매뉴얼 같은 참고 문서. Prompt: 재사용 지시문 템플릿 | Inspector에서 3종 모두 목록 확인 | §4 | ✅ |
| R06 | 동적 데이터는 캐시 없이 조회 | 실시간 값은 Tool로 매번 새로 조회. Resource를 쓸 경우 갱신 방법 명시 | 같은 조회 3회: Before(캐시) 값 동일 vs After 값 변화 | MCP 실습 | ✅ |
| R07 | 멀티 MCP 서버 연결 | `MultiServerMCPClient`(또는 `fastmcp.Client` 멀티 설정)로 MCP 서버 2개 이상 연결, 서버 이름 접두사로 구분 | 에이전트가 두 서버의 도구를 모두 호출 | §4, MCP 실습 | 🔺 |
| R08 | Handshake 이해 | 연결 초기 capability 교환 로그 확인 | 기동 로그 캡처 | §4 | ✅ |

### D. 스트리밍 (SSE)

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R09 | SSE 엔드포인트 | `POST /chat/stream` | `curl -N`으로 이벤트가 시간차를 두고 도착 | §5, SSE 실습 | 🔺 |
| R10 | 이벤트 스키마 | `token` / `tool_call_start` / `tool_call_end` / `done(thread_id)` Pydantic 정의, 노드 진행 이벤트 추가 | 이벤트 순서 확인 | SSE 실습 | 🔺 |
| R11 | 변환 계층 분리 | `streaming/event_converter.py`(LangGraph `astream` 이벤트 → 도메인 이벤트), `streaming/sse_formatter.py`(→ `event:/data:/빈 줄`) | 단위 테스트 | SSE 실습 | ❌ |
| R12 | 진행 상황 UI | Vue 화면에 "조사 시작 / 도구 호출 / 작성 중" 표시 | 화면 캡처 | §5 | ✅ |
| R50 | 비동기 통신(AJAX) | 페이지 새로고침 없이 `fetch`로 요청하고 응답 영역만 갱신. 스트림은 `fetch` + `ReadableStream`으로 SSE 이벤트 파싱 (POST 요청이라 `EventSource` 대신) | 새로고침 없이 대화 이어짐 | 안내 메모 | 🔺 |

Before/After 지표: 첫 이벤트 도착 시간(TTFB) vs 전체 완료 시간. SSE가 총 처리 시간을 줄이지는 않는다는 점을 한계에 명시.

### E. 멀티에이전트 그래프

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R13 | Supervisor 구조 | Supervisor가 Research / Analysis / Writing 에이전트에 작업 배정. 역할별 프롬프트·도구·모델 분리 | 트레이스에서 노드 경로 확인 | §6 | 🔺 |
| R14 | 공유 State | `TypedDict` State: messages, route, reasoning, plan, tasks, current_task_index, 수집 결과, draft, 카운터 | State 스키마 문서화 | §6, Routing 실습 | ✅ |
| R15 | ReAct 서브에이전트 | 판단 → 도구 → 관찰 반복 (`create_react_agent`) | 도구 호출 이벤트 확인 | §6, SSE 실습 | ❌ |

### F. 라우팅과 계획

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R16 | Query Routing | LLM 구조화 출력으로 `simple` / `complex` + `reasoning` 판단 → `add_conditional_edges` 분기 | 인사 질문: Before(항상 계획) vs After(즉시 응답) LLM 호출 수·지연 비교 | §7, Routing 실습 | 🔺 |
| R17 | 라우팅 안정성 | 같은 입력 N회 반복 분류 | 반복 실행 결과표 | Routing 실습 | ❌ |
| R18 | 가드 게이트 | LLM 판단 모순을 코드로 정리 (예: 분석 불필요 판단인데 분석 task가 있으면 제거) | 단위 테스트 | §7 | ✅ |
| R19 | Dynamic Planning | 수집 결과 충분성 판단 → 부족하면 추가 조사 task 추가, **최대 반복 횟수 상한** | 추가 조사 발생 케이스 로그, 상한 도달 테스트 | §8 | 🔺 |

### G. 품질 검증

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R20 | Validator (LLM-as-a-Judge) | 관련성, 완전성, 도메인 적합성, 명확성 4기준을 구조화 출력으로 평가 + 피드백 | 불합격 → 재작성 → 합격 케이스 재현 | §9, Wave 8 | ❌ |
| R21 | Faithfulness 확인 | 답변이 수집한 근거와 일치하는지 별도 기준으로 평가 | 근거 없는 수치를 넣은 답변이 불합격 | §9 | ❌ |
| R22 | 재작성 루프 안전장치 | `writing_attempts`(최대 2), `validation_attempts`(최대 3) 이중 카운터. 시도 횟수는 성공·실패와 무관하게 증가 | 무한 루프 없음 테스트 | Wave 8 | 🔺 |
| R23 | Graceful Degradation | 상한 도달 시 draft + "품질 기준 미달" 안내, draft 없으면 사과 메시지 | 단위 테스트 | Wave 8 | 🔺 |

Before/After 지표: 검증 없음 vs 검증 있음의 평가 점수, 재작성 횟수, 추가 지연·비용.

### H. 에러 처리

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R24 | 일시적 오류 재시도 | 타임아웃 등 일시적 오류만 지수 백오프 재시도 (0.5s → 1.5s → 4.5s), 횟수·총 시간 상한 | 장애 주입 테스트 | §10 | ✅ |
| R25 | 영구 오류 즉시 실패 | 권한·설정 오류는 재시도 없이 실패 보고 | 단위 테스트 | §10 | ✅ |
| R26 | Task 단위 에러 격리 | 개별 task를 try/except로 감싸 `failed` 결과 반환, 나머지 결과 보존 | 1개 실패 시 나머지 성공 | §10, Wave 10b | ❌ |
| R27 | 부분 결과 표시 | 확인하지 못한 항목을 답변에 명시 | 응답 예시 캡처 | §10 | ❌ |

### I. 비용과 속도

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R28 | 모델 분리 | `fast_llm`(라우팅·분류) / `quality_llm`(분석·작성·검증) | 단계별 토큰·비용표 Before(전부 quality) vs After | §11, Wave 10a | ✅ |
| R29 | 품질 유지 확인 | 저비용 모델로 바꾼 단계의 정확도 비교 | 라우팅 정확도 비교 | §11 | ❌ |
| R30 | 병렬 실행 | 독립 조회를 `asyncio.gather`로 fan-out / fan-in | 순차 합계 vs 최장 task 시간 실측 | §11, Wave 10b | 🔺 |
| R31 | 동시성 제한 | `asyncio.Semaphore`로 동시 요청 수 제한 | 설정값 테스트 | §11 | ❌ |
| R32 | 블로킹 호출 금지 | async 노드 안에서 동기 I/O 사용 금지 (필요 시 `to_thread`) | 코드 리뷰 | §11 | ❌ |

비용 단가는 공식 요금표 기준으로 계산하고, 가정값을 쓰면 명시한다. Wave 10a 교훈: 토큰이 적은 단계보다 **호출 빈도와 단가 배율이 큰 단계**를 노려야 효과가 크다.

### J. 세션과 상태

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R33 | 영속 Checkpointer | `thread_id`별 대화 상태를 SQLite(또는 Postgres) 체크포인터에 저장 | 서버 재시작 후 "제 이름이 뭐였죠?"에 정답 | §12, Wave 12 | 🔺 |
| R34 | Stateless 서버 | 서버 프로세스에 상태를 두지 않고 저장소에서 복원 | Before(MemorySaver: 재시작 후 소실) vs After(복원) | §12, Wave 12 | ✅ |

### K. 코드 구조와 테스트

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R35 | 모듈화 | `nodes/`, `agents/`, `mcp_servers/`, `streaming/`, `schemas/`, `api/` 등 역할별 분리 | 구조도 | §13, Wave 13 | 🔺 |
| R36 | 의존성 주입 | `Deps` dataclass + `functools.partial`로 노드에 주입. closure·전역 변수 의존 금지 | 노드를 단독 import해 호출 가능 | §13, Wave 13 | ✅ |
| R37 | 단위 테스트 | pytest + fake LLM 주입으로 라우팅, 가드 게이트, 검증 루프, SSE 포맷터, 에러 격리 테스트 | `pytest` 통과 | §13 | ❌ |

### L. 관측성과 평가

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R38 | 구조화 로그 | JSON 로그, 공통 필드명 통일 (`trace_id`, `thread_id`, `node`, `latency_ms`) | 로그 샘플 | §14 | ❌ |
| R39 | 메트릭 | 요청별 지연, 실패율, 토큰·비용 집계 | 실험 결과표 | §14 | 🔺 |
| R40 | LangSmith Tracing | Run이 Project 아래 쌓이고 노드별 부모·자식 스팬 확인 | LangSmith 화면 캡처 | §14, LangSmith 실습 | ✅ |
| R41 | LangSmith Feedback | UI 👍/👎를 해당 Run의 feedback으로 기록 | `list_feedback` 재조회 | LangSmith 실습 | ❌ |
| R42 | Dataset + evaluate() | 회귀 질문 세트를 Dataset으로 등록, Before/After 실험 비교 | 실험 점수 비교 | LangSmith 실습 | ❌ |
| R43 | 평가자 2종 | 키워드 매칭 + LLM-as-judge(근거 인용 정확성). 키워드 점수의 한계 명시 | 두 점수 비교 | §14, PDF 예시 6 | ❌ |
| R44 | Prompt Hub | 프롬프트를 Hub에 push하고 이름으로 pull (하드코딩 제거). 핸들이 없으면 비공개로 커밋 | 버전 이력 확인 | LangSmith 실습 | ❌ |

"실행 성공 ≠ 답변 정확" — 오류 없이 끝난 것과 품질은 별도로 측정한다.

### M. 개발 환경

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R45 | 가상환경 | `uv venv --python 3.11` + 의존성 파일 | 새 환경에서 설치 재현 | 전 실습 | 🔺 |
| R46 | 비밀값 관리 | `.env`(ignore) + `.env.example`(커밋) | 저장소에 키 없음 | LangSmith 실습 | ✅ |
| R47 | 로컬 LLM 우선 | 개발은 Ollama(qwen3), 최종 측정은 OpenAI. LLM 제공자는 설정으로 전환 | 두 모드 모두 기동 | Routing 실습, PDF | ✅ |
| R48 | 실행 스크립트 | venv 준비, 서버 기동, 포트 정리 스크립트 | README대로 실행 | FastAPI·SSE 실습 | ✅ |

---

### N. 가이드라인 추가 항목

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R51 | LangChain 구성요소 사용 | LLM 호출을 직접 HTTP 대신 LangChain 채팅 모델(`init_chat_model`, Ollama/OpenAI)로 통일. `ChatPromptTemplate`, `with_structured_output`, `@tool` 사용 | 코드에 raw HTTP LLM 호출 없음 | 교수님 가이드라인 | ❌ (httpx 직접 호출) |
| R52 | 핸즈온 랩 형식 | `docs/lab/stepNN-*.md`: 단계마다 목표, 실행 명령, 기대 결과, 확인 포인트. 각 단계 끝에서 앱이 실행 가능한 상태 | 문서대로 처음부터 재현 | 교수님 가이드라인, 캡스톤 followup 형식 | ❌ |
| R53 | 외부 MCP 서버 활용 | 공개 MCP 서버(예: 파일시스템, SQLite) 1개 이상을 멀티 서버 클라이언트에 연결해 직접 만든 서버와 함께 사용 | 에이전트가 외부 서버 도구 호출 | 교수님 가이드라인 | ❌ |

### O. 사용자 요청 기능 (2026-10-20)

| ID | 요구사항 | 적용 내용 | 검증 | 출처 | Base |
| --- | --- | --- | --- | --- | --- |
| R54 | 제품 관리 UI | 제품 목록·상세 조회, 제품 추가·수정. 저장 시 CAS 체크 디지트·함량 합계 100 ± 0.5%·수출 지역·성분 역할을 코드로 검증하고 오류 행을 표시. 저장 직후 판정 결과 표시. 제품은 앱 DB가 원본(CSV는 초기 데이터) | 잘못된 CAS·합계로 저장 거부, 추가한 제품이 재시작 후에도 유지 | 사용자 요청 | ❌ |
| R55 | 규제 목록 UI | 규제 목록(지역·법·판정 방식·의무·출처), 규제별 등재 물질, CAS·이름 검색, 검증 상태(to_verify) 표시 | 화면에서 13개 규제·등재 물질 조회 | 사용자 요청 | ❌ |
| R56 | 답변 근거 원문 표시 | 답변에 쓴 근거마다 원문 문장(코드가 문서·등재 데이터에서 추출) + 한국어 번역(무결성 검사 통과) + 출처 URL + 기준일 + 검증 상태. LLM이 원문을 직접 쓰지 않음 | 근거 원문이 출처 문서에 실제로 존재(문자열 포함 검사), 번역 무결성 통과 | 사용자 요청 | ❌ |

## 3. 수행 업무 리스트

| # | 업무 | 관련 요구사항 | 산출물 |
| --- | --- | --- | --- |
| W1 | Base 분석: 위 표의 `Base` 열 채우기 | 전체 | 이 문서 갱신 |
| W2 | 주제 확정 후 요구사항을 주제 도메인으로 구체화 | 전체 | PLAN.md 기능 리스트 |
| W3 | 프로젝트 골격: 모듈 구조, Deps, 설정, lifespan, CORS, 로깅 | R02, R03, R35, R36, R38, R45~R49 | 기동 가능한 서버 |
| W4 | MCP 서버 2개 + 멀티 클라이언트 | R04~R08 | MCP 서버, Inspector 캡처 |
| W5 | 그래프: 라우팅 → 계획 → 가드 → 병렬 조사 → 충분성 → 분석 → 작성 → 검증 → 확정 | R13~R23, R26, R30, R31 | Supervisor 그래프 |
| W6 | 에러 처리 공통 모듈 (재시도, 격리) | R24~R27 | `core/retry.py` 등 |
| W7 | 모델 분리와 비용 집계 | R28, R29, R39 | 비용표 |
| W8 | SSE 스트리밍과 Vue 연동 | R09~R12, R50 | 스트리밍 화면 |
| W9 | 영속 체크포인터 | R33, R34 | 재시작 복원 데모 |
| W10 | LangSmith: tracing, feedback, dataset, evaluate, hub | R40~R44 | 실험 링크, 캡처 |
| W11 | 단위 테스트 | R37 | `tests/` |
| W12 | Before/After 실험과 비교표 | 1장 프로세스 | `docs/experiments/` |
| W13 | ADR, README, 결과보고서(읽기 권한 공개 링크), PPT | R01 | 문서, 발표 자료 |

---

## 4. 범위 리스크

Day3은 PPT·보고서만 작업하므로, 요구사항 56개를 사실상 Day1 오후~Day2 안에 구현해야 해서 일정이 매우 빠듯하다.

- Base(`all_total_vue_student`)가 이미 구현한 부분은 재사용하고 **개선 부분에 시간을 쓴다** (W1 결과로 판단)
- 구현 순서는 그래프 핵심(W3~W5) → 관측·평가(W10, W12) → 나머지로, 시간이 부족해도 Before/After 수치는 확보한다
- 구현하지 못한 항목은 삭제하지 말고 "한계 및 추가 개선"으로 발표에 남긴다
