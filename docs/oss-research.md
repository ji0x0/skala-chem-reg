# GitHub 오픈소스 AI 서비스 탐색

3단계 결과. 2026-10-20 기준으로 GitHub API에서 ★, 라이선스, 마지막 push를 직접 조회했고, README와 일부 소스를 읽어 정리했다.

탐색 기준
- **A. 서비스 템플릿**: FastAPI + LangGraph로 "에이전트를 서비스로" 만든 저장소 → 코드 구조 레퍼런스
- **B. AI SRE 에이전트**: Base와 같은 도메인(장애 조사, 근본 원인 분석) → 기능·안전장치 레퍼런스
- **C. LLM 앱 플랫폼**: 대형 플랫폼 → 직접 사용보다는 트렌드 참고

---

## 1. 후보 요약

| 그룹 | 저장소 | ★ | 언어 | 라이선스 | 최근 push | 한 줄 특징 |
| --- | --- | --- | --- | --- | --- | --- |
| A | [JoshuaC215/agent-service-toolkit](https://github.com/JoshuaC215/agent-service-toolkit) | 4,534 | Python | MIT | 2026-10-18 | LangGraph + FastAPI + Streamlit 풀 툴킷. 멀티 에이전트, SSE, 피드백, 체크포인터 |
| A | [wassim249/fastapi-langgraph-agent-production-ready-template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template) | 2,711 | Python | MIT | 2026-10-17 | 운영 중심 템플릿. 인증, 레이트 리밋, 메트릭, 모델 폴백, 평가 |
| A | [NicholasGoh/fastapi-mcp-langgraph-template](https://github.com/NicholasGoh/fastapi-mcp-langgraph-template) | 558 | Python | MIT | 2026-03-03 | MCP 중심 템플릿. MCP 서버 컨테이너 + Inspector + Nginx |
| A | [google-gemini/gemini-fullstack-langgraph-quickstart](https://github.com/google-gemini/gemini-fullstack-langgraph-quickstart) | 18,351 | Python | Apache-2.0 | 2026-06-14 | React + LangGraph 리서치 에이전트. 성찰(reflection) 반복 루프, 인용 |
| A | [langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research) | 12,680 | Python | MIT | 2026-08-10 | 딥 리서치 에이전트 (**archived**) |
| B | [HolmesGPT/holmesgpt](https://github.com/HolmesGPT/holmesgpt) | 3,640 | Python | Apache-2.0 | 2026-10-19 | CNCF Sandbox SRE 에이전트. Toolset, 읽기 전용, MCP |
| B | [Tracer-Cloud/opensre](https://github.com/Tracer-Cloud/opensre) | 12,233 | Python | Apache-2.0 | 2026-10-20 | AI SRE 프레임워크 (퍼블릭 알파). 가설 검증 루프, 근거 연결 답변 |
| B | [Arvo-AI/aurora](https://github.com/Arvo-AI/aurora) | 438 | Python | Apache-2.0 | 2026-10-19 | LangGraph 멀티에이전트 장애 조사. 지식 베이스 RAG, 의존성 그래프 |
| B | [k8sgpt-ai/k8sgpt](https://github.com/k8sgpt-ai/k8sgpt) | 8,259 | Go | Apache-2.0 | 2026-10-19 | Kubernetes 문제 진단 CLI |
| B | [keephq/keep](https://github.com/keephq/keep) | 12,420 | Python | 별도 | 2026-09-28 | AIOps·알림 관리 플랫폼 |
| C | [langgenius/dify](https://github.com/langgenius/dify) | 158,944 | Python | 별도 | 2026-10-20 | 에이전트 워크플로·RAG 노코드 플랫폼 |
| C | [infiniflow/ragflow](https://github.com/infiniflow/ragflow) | 92,496 | Go | Apache-2.0 | 2026-10-20 | RAG 엔진 |
| C | [langchain-ai/agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui) | 3,234 | TypeScript | MIT | 2026-10-19 | LangGraph 에이전트용 채팅 UI |
| 참고 | [langchain-ai/langgraph-supervisor-py](https://github.com/langchain-ai/langgraph-supervisor-py) | 1,656 | Python | MIT | 2026-07-15 | Supervisor 라이브러리 (**archived**) |

> archived 저장소(`open_deep_research`, `langgraph-supervisor-py`)는 개념만 참고하고 의존성으로 쓰지 않는다. Supervisor는 Base처럼 `StateGraph`로 직접 구성한다.

---

## 2. 그룹 A — 서비스 템플릿

### 2-1. agent-service-toolkit ⭐ 구조 레퍼런스 1순위

- **구성**: LangGraph 에이전트 / FastAPI 서비스 / Python 클라이언트(`AgentClient`) / Streamlit UI. 모든 입출력은 Pydantic 스키마
- **구조**: `src/agents/`(에이전트 정의), `src/schema/`(프로토콜), `src/core/`(LLM·설정), `src/service/service.py`(FastAPI), `src/client/`, `tests/`
- **에이전트 여러 개를 한 서비스에서**: `/{agent_id}/stream`처럼 경로로 선택. `chatbot`, `research_assistant`, `rag_assistant`, `interrupt_agent`(Human-in-the-loop), `langgraph_supervisor_agent`, `github_mcp_agent`, `safeguard`(콘텐츠 모더레이션) 등
- **스트리밍**: `POST /stream` + Pydantic `StreamInput` 본문 → SSE. 이벤트는 `token`(토큰) / `message`(완성 메시지) / `error`, 끝에 `[DONE]`. 예외도 `error` 이벤트로 내려준다
- **세션**: `lifespan`에서 체크포인터(단기 기억)와 Store(장기 기억)를 초기화해 에이전트에 붙인다. SQLite / Postgres / MongoDB 선택. `/threads`로 이전 대화 목록 조회
- **피드백**: `POST /feedback`이 LangSmith `create_feedback`을 감싼다. UI 별점 → LangSmith Run에 기록
- **보안**: `Depends(verify_bearer)`로 라우터 전체에 Bearer 토큰 검사
- **테스트**: pytest 단위·통합 테스트, Docker 스모크 테스트

**가져올 것**: 디렉토리 구조, `POST` 스트리밍 + 에러 이벤트, `/feedback` → LangSmith, lifespan 체크포인터, 에이전트 레지스트리

### 2-2. fastapi-langgraph-agent-production-ready-template ⭐ 운영 레퍼런스

- **관측성**: Langfuse LLM 트레이싱 + Prometheus 메트릭 + Grafana 대시보드, 프로파일링 미들웨어
- **구조화 로그**: 모든 로그 줄에 요청·세션·사용자 컨텍스트 포함
- **복원력**: tenacity 지수 백오프 재시도 → 재시도가 소진되면 `LLMRegistry`의 **다음 모델로 폴백**, 전체 호출에 **타임아웃 예산**
- **메모리**: LangGraph 체크포인터(Postgres) + mem0 장기 기억(pgvector)
- **보안**: JWT 인증, slowapi 레이트 리밋, 입력 정제
- **평가**: `evals/`에 `evaluator.py`, `metrics/`, 리포트 생성
- **구조**: `app/api/v1/`, `app/core/`(langgraph, prompts, middleware, limiter), `app/schemas/`, `app/services/`

**가져올 것**: 컨텍스트가 붙은 구조화 로그, 모델 폴백 + 타임아웃 예산, `evals/` 폴더 구성, 프롬프트 분리(`core/prompts`)

### 2-3. fastapi-mcp-langgraph-template — MCP 배치 레퍼런스

- MCP 서버(DBHub, YouTube, 커스텀)를 **각각 별도 컨테이너**로 띄우고 API 서버가 MCP Python SDK로 연결
- **MCP Inspector를 compose에 포함**해 개발 중 바로 서버를 호출해 볼 수 있음
- Nginx 리버스 프록시로 브라우저 요청을 API로 전달 (Base의 `web_demo_server.py` 프록시와 같은 발상)
- Supabase(Postgres + PGVector), Langfuse

**가져올 것**: MCP 서버를 독립 프로세스로 두고 Inspector로 검증하는 개발 흐름 (R04, R08)

### 2-4. gemini-fullstack-langgraph-quickstart — 반복 조사 루프 레퍼런스

- 그래프: 검색어 생성 → 웹 검색 → **성찰(지식 공백 판단)** → 부족하면 후속 검색어로 반복(**최대 횟수 설정**) → **출처 인용**을 포함한 답변
- React(Vite) + Tailwind + Shadcn 프론트, LangGraph 백엔드
- 운영 배포에서는 Redis(pub-sub 스트리밍)와 Postgres(스레드·실행 기록·장기 기억)를 쓴다

**가져올 것**: Base의 `replan_check`는 "런북이 있는가"만 본다. 이걸 **LLM이 지식 공백을 판단하고 후속 조사를 만드는 루프**로 바꾸는 근거 (R19). 답변에 근거 출처를 붙이는 방식 (R21)

---

## 3. 그룹 B — AI SRE 에이전트 (Base와 같은 도메인)

### 3-1. HolmesGPT

- 프로덕션 장애 근본 원인을 찾는 에이전트. CNCF Sandbox, Microsoft 기여
- **에이전틱 루프**로 Prometheus, Grafana, Datadog, Kubernetes, 클라우드, Loki, Elasticsearch 등 **toolset**을 조회
- 여러 toolset이 **MCP**로 제공됨
- **기본 읽기 전용**, RBAC 준수 → 운영 환경에서 실행해도 안전하다는 설계
- Operator 모드: 24/7 감지 → Slack 알림, 수정 PR 제안

### 3-2. OpenSRE (퍼블릭 알파)

- 조사 파이프라인: ① 로그·메트릭·트레이스·최근 배포 수집 → ② **LLM 호출 전 민감 식별자 마스킹** → ③ 도구 호출 루프로 **가설 검증** → ④ **근거와 연결된 답변** + 다음 조치 제안 → ⑤ Slack 등에 요약 게시
- 세션별 **토큰 비용 추적**, 재개 가능한 세션
- 실제 장애 시나리오 **e2e 테스트**
- 모델 제공자 다수 (Ollama 포함)

### 3-3. Aurora

- 알림 수신 → 에이전트 자동 조사 → **구조화된 RCA** → 포스트모템 생성, 수정 PR, Slack 알림
- **LangGraph 멀티에이전트**가 30개 이상 도구를 동적으로 선택하고 **병렬 조사**
- **지식 베이스 RAG**: 조사 지식이 시간이 지나며 쌓임
- **인프라 의존성 그래프**로 영향 범위(blast radius) 추적
- 가드레일: RBAC, 조직 단위 명령 정책, 프롬프트 인젝션 탐지 입력 레일
- Ollama로 완전 오프라인 운영 가능

### 3-4. k8sgpt, Keep

- **k8sgpt**: Kubernetes 클러스터를 스캔해 문제를 찾아 설명하는 Go CLI
- **Keep**: 알림을 모으고 상관 분석하는 AIOps 플랫폼

---

## 4. 그룹 C — 플랫폼

- **Dify**, **RAGFlow**: 규모가 커서 3일 프로젝트의 레퍼런스로는 과함. "워크플로 + RAG + 모델 교체"가 업계 표준 기능 묶음이라는 점만 참고
- **agent-chat-ui**: LangGraph 서버용 채팅 UI. 우리는 Base의 Vue 화면을 유지하므로 UI 구성 아이디어만 참고

---

## 5. 공통 패턴

조사한 저장소들에서 반복해서 나온 것:

| 패턴 | 나온 곳 | Base 현재 | 관련 요구사항 |
| --- | --- | --- | --- |
| `POST` 스트리밍 + Pydantic 입력 + `error` 이벤트 | toolkit | `GET` + 쿼리스트링, 에러 이벤트 없음 | R09, R10, R50 |
| LangGraph 체크포인터를 lifespan에서 초기화 | toolkit, wassim249, gemini | 별도 메시지 테이블 | R33 |
| UI 피드백 → LangSmith/Langfuse | toolkit | 없음 | R41 |
| 평가 폴더(evaluator + metrics + 리포트) | wassim249, OpenSRE(e2e) | 없음 | R42, R43 |
| 구조화 로그 + 메트릭 대시보드 | wassim249 | 없음 | R38, R39 |
| 재시도 → **모델 폴백** → 타임아웃 예산 | wassim249 | 재시도만 | R24 (확장) |
| 지식 공백 판단 → 후속 조사 반복(상한) | gemini, OpenSRE | 런북 유무만 확인, 1회 | R19 |
| **근거 연결 답변**(인용) | gemini, OpenSRE | 없음 | R21 |
| 기본 **읽기 전용** + 위험 조치는 승인 | HolmesGPT, toolkit(interrupt) | 없음 | PDF 예시 4 (HITL) |
| 지식 베이스 **RAG** | Aurora, wassim249(mem0) | 키워드 규칙 | PDF 예시 1 |
| LLM 호출 전 **민감정보 마스킹** / 입력 가드레일 | OpenSRE, Aurora, toolkit(safeguard) | 없음 | 신규 후보 |
| 멀티에이전트 **병렬 조사** | Aurora | 노드 1개 + 공용 Lock | R13, R30 |
| 프롬프트를 코드 밖으로 분리 | wassim249(`core/prompts`) | LLM 클래스 안 하드코딩 | R44 |

---

## 6. 레퍼런스 사용 결정

| 용도 | 레퍼런스 | 이유 |
| --- | --- | --- |
| 코드 구조, API 설계 | agent-service-toolkit | 규모가 적당하고 캡스톤 요구사항(SSE, 체크포인터, 피드백, 테스트)을 거의 다 갖춤 |
| 운영 품질 (로그, 폴백, 평가) | fastapi-langgraph production template | 관측성·복원력·평가 폴더 구성이 구체적 |
| 반복 조사 루프, 인용 | gemini-fullstack quickstart | Base `replan_check`의 약점을 정확히 보완 |
| MCP 개발 흐름 | fastapi-mcp-langgraph-template | MCP 서버 분리 + Inspector |
| 도메인 기능 아이디어 | HolmesGPT, OpenSRE, Aurora | 읽기 전용 안전성, 가설 검증, RAG 지식 베이스, 마스킹 |

- 라이선스: 위 레퍼런스는 모두 MIT 또는 Apache-2.0. **코드를 복사하지 않고 설계만 참고**한다. 일부를 가져올 경우 출처와 라이선스를 README에 표기
- 이 문서의 기능은 4단계 주제가 정해진 뒤 범위에 맞게 고른다

## 7. 4단계(주제 선정)에 주는 시사점

- **Base 도메인(장애 대응)을 유지하는 경우**: SRE 에이전트들이 보여준 기능(근거 연결 답변, RAG 지식 베이스, 가설 검증, 읽기 전용 + 승인)이 그대로 개선 포인트가 되고, Base 회귀 쿼리로 Before/After를 바로 측정할 수 있다
- **새 주제로 가는 경우**: agent-service-toolkit 구조 + Base의 그래프 골격을 가져가고, MCP 서버·데이터·프롬프트를 새 도메인으로 교체한다. Before/After 기준선을 새로 만들어야 한다

---

## 출처

- GitHub REST API `repos/{owner}/{repo}` (★, 라이선스, push 일자, 2026-10-20 조회)
- [agent-service-toolkit README](https://github.com/JoshuaC215/agent-service-toolkit), [service.py](https://github.com/JoshuaC215/agent-service-toolkit/blob/main/src/service/service.py)
- [fastapi-langgraph-agent-production-ready-template README](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template)
- [fastapi-mcp-langgraph-template README](https://github.com/NicholasGoh/fastapi-mcp-langgraph-template)
- [gemini-fullstack-langgraph-quickstart README](https://github.com/google-gemini/gemini-fullstack-langgraph-quickstart)
- [HolmesGPT README](https://github.com/HolmesGPT/holmesgpt), [OpenSRE README](https://github.com/Tracer-Cloud/opensre), [Aurora README](https://github.com/Arvo-AI/aurora)
- 검색: [agent-service-toolkit (SourcePulse)](https://www.sourcepulse.org/projects/1849351), [production-ready template (SourcePulse)](https://www.sourcepulse.org/projects/2335328), [FastAPI MCP LangGraph Template](https://docsearch.algolia.com/mcp/docs/repo/nicholasgoh/fastapi-mcp-langgraph-template), [OpenSRE](https://github.com/Tracer-Cloud/opensre), [Aurora (SourcePulse)](https://www.sourcepulse.org/projects/30455343)
