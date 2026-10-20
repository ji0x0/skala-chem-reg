# DEVLOG

개발 진행 기록. 날짜별로 한 일, 결정한 것과 이유, 트레이드오프, 다음 할 일을 남긴다.

---

## 2026-10-20 (Day1)

### 한 일
- 작업 폴더 구성: 참고 자료(PDF, capstone 실습 안내, `all_total_vue_student`)는 `example/`에 모으고 `.gitignore`로 제외
- 0단계: `AI-Mini-Project` PDF를 확인해 산출물, 평가 항목, 일정을 [PLAN.md](PLAN.md)에 정리
- 1단계: AI capstone 강의 요약, 실습 안내 5종(FastAPI, MCP, SSE, Query Routing, LangSmith), 나머지 실습 5종(Validator, 비용, 병렬, Stateless 세션, 모듈화) 코드를 확인해 [REQUIREMENTS.md](REQUIREMENTS.md)로 정리
- 2단계: `all_total_vue_student` 코드 전체를 읽고 fake 백엔드로 기동해 확인 → [docs/base-analysis.md](docs/base-analysis.md). REQUIREMENTS.md `Base` 열 채움 (✅ 17 / 🔺 15 / ❌ 18)
  - 재현한 약점: "web-01 CPU 급증"에 DB Down 런북을 고름(증상 분류가 모니터링 알림만 봄), "느려지고 CPU가 치솟았어요"가 chat으로 오분류(키워드 라우팅), 상한 도달 시 검증 미달을 숨기고 합격 처리
  - 코드로 확인한 약점: MCP 공용 Lock 때문에 병렬 조사가 사실상 직렬, task 단위 에러 격리 없음, async 노드 안 동기 HTTP 호출, CORS 미들웨어 없음(프록시로 회피)

- 3단계: GitHub 오픈소스 14개(서비스 템플릿 5, AI SRE 5, 플랫폼 등 4)를 GitHub API와 README로 조사 → [docs/oss-research.md](docs/oss-research.md)
- 4단계: 페르소나(주니어 온콜 엔지니어, SRE 팀 리드)와 페인포인트 8개 정의, 주제 후보 3개 비교 → [docs/topic-selection.md](docs/topic-selection.md). 추천은 후보 A(Base 개선: 장애 대응 코파일럿), 최종 선택은 대기
- 4단계 2차: 전공(재료화학공학)과 고분자·화장품 연구 경력을 살린 후보 3개 추가 → [docs/topic-domain.md](docs/topic-domain.md). Base의 장애 조사 흐름이 QC 실험실의 시험 이상(OOS) 조사와 1:1로 대응됨을 확인. 추천은 후보 D(품질 시험 이상 조사 에이전트), 최종 선택은 대기
- 실습 교수님 가이드라인 반영: REQUIREMENTS.md "0-1"에 필수 조건 정리, R51(LangChain 구성요소), R52(핸즈온 랩 문서), R53(외부 MCP 서버) 추가 → 총 53개
- 이전 LangChain 실습(품질 판정 도우미)과 후보 D의 중복 검토 → topic-domain.md "3-1". 도메인은 같지만 판정(무엇)이 아니라 조사(왜)를 다루고, 노트북의 "한계와 개선 방향"을 해결하는 확장으로 판단
- 4단계 확정: 주제를 **공정 운전 이상 조사 에이전트**로 결정 → [docs/topic-final.md](docs/topic-final.md). 이전 LangChain 실습(실험실 시험값 판정)과 겹치지 않고(공정 센서 시계열), Base의 모니터링 → 런북 구조와 더 잘 맞으며, 운전 조건 변경 승인(HITL)과 금지 조치 차단(가드 게이트)의 필요성이 분명함

- **코드 1차 구현 (핸즈온 랩 Step 0~6)** → [docs/lab/](docs/lab/README.md)
  - Step 0: uv 프로젝트, `Settings`, JSON 구조화 로그
  - Step 1: 가상 공정 데이터 (3개 설비·13개 태그·24시간, 이상 시나리오 6개 + 계측기 드리프트 함정), 절차서 10개, 평가 질문 11개
  - Step 2: 추세 요약 코어(선행 태그·단일 계측기 이탈·이중 계측기 비교), 가드, RAG, MCP 서버 3개(Tool 9·Resource 1·Prompt 1), `MCPToolProvider`(지속 세션·Semaphore·지수 백오프 재시도)
  - Step 3: LangChain LLM 계층(Ollama/OpenAI, 구조화 출력, fast/quality 분리) + Fake LLM, LangGraph Supervisor(route → plan → gate → 서브에이전트 3개 `Send` 병렬 → review 재조사 → diagnose → write → guard → validate → approval `interrupt` → finalize), Before(baseline) 그래프
  - Step 4: FastAPI REST 7개 엔드포인트 + SSE 이벤트 9종, lifespan 싱글턴, `AsyncSqliteSaver`, CORS(허용 출처만), 승인 API(409 처리)
  - Step 5: Vue 3 화면 (토큰 스트리밍, 진행 타임라인, 승인 카드, 👍/👎)
  - Step 6: pytest 23개 통과, Before/After 평가 스크립트(+LangSmith Dataset 옵션)
  - fake LLM 평가: 라우팅 0.455 → 1.0, 원인 0.25 → 1.0, 절차서 0.25 → 1.0, 승인 요청 0.125 → 1.0 (fake는 규칙 기반이라 파이프라인 동작 확인용)
- Ollama 실모델(qwen2.5:0.5b / qwen3:8b) 스모크 테스트: 전체 경로 동작 확인 (E01 약 156초). 발견한 문제는 아래 "다음 할 일"

- Step 4: FastAPI REST + SSE, 제품 관리·규제 목록 API, 제품 저장소 분리(앱 DB가 원본). 실서버 확인: 다른 대화 2건 동시 처리, 같은 대화 동시 요청 차단, 승인 후 재개·재승인 409
- Step 5a: Vue 3 + Vite 화면 — 질의응답·브리핑 SSE 스트리밍, 진행 단계 표시, 근거 원문·번역·출처 카드, 본문 [n] → 근거 이동, 승인·반려, 👍/👎, 새로고침 후 대화·승인 대기 복원. 승인 대기 화면 문제(코드 블록·근거 누락) 발견·수정
- Step 5b: 제품 관리 화면(목록·판정 요약, 배합표, 추가·수정 폼 — 입력 중 CAS·합계 검사, 저장 직후 판정), 규제 목록 화면(지역별 규제·등재 물질, 물질 검색 → 등재 규제·함유 제품 → 제품 탭 이동). 화면에서 추가한 제품을 질의응답이 바로 인식 확인. 접근성 문제(href 없는 링크) 수정

### 결정 사항
- 참고 자료는 저장소에 올리지 않는다 (`example/` 전체 ignore). 강의 자료 무단 배포 금지 문구가 있음
- 캡스톤 내용은 전부 적용 대상으로 보고 요구사항 48개(R01~R48)로 정리. 이후 안내 메모의 CORS(R49), AJAX(R50)를 추가해 총 50개
- 서비스 구성은 상용 서비스 기준: 사용자 프론트엔드(Vue) + 백엔드 API(FastAPI) + 관리자 대시보드(LangSmith)
- 결과보고서는 읽기 권한이 부여된 온라인 링크로 제출. 발표는 자기 자리에서 진행
- 개발 프로세스는 캡스톤 실습 형식을 따른다: 나이브(Before) → 개선(After) → 같은 입력으로 실측 → 비교표 → 한계 기록. 평가 항목의 Before/After 보너스와 한계·트레이드오프 항목에 그대로 대응됨
- 레퍼런스: 구조는 agent-service-toolkit, 운영 품질은 fastapi-langgraph production template, 반복 조사 루프는 gemini-fullstack quickstart, 도메인 기능은 HolmesGPT/OpenSRE/Aurora. 코드는 복사하지 않고 설계만 참고
- archived 저장소(open_deep_research, langgraph-supervisor-py)는 의존성으로 쓰지 않음
- 기본 실행은 fake LLM: API 키·모델 없이 화면·API·테스트가 결정론적으로 돈다. 실모델은 `LLM_BACKEND` 하나로 전환
- 서브에이전트는 1차로 "코드가 도구 호출 순서를 정하고 LLM은 요약"하는 방식. 실모델 도구 선택(ReAct)은 Day2 디벨롭 후보
- **단계별 재구축 결정**: 1차 초안(Step 0~6)을 한 번에 작성해 폴더·파일·코드를 단계별로 따라가며 확인할 수 없었음 → 초안은 Git에 넣지 않고 `_backup/full-draft-20261020/`(gitignore)에 백업만 하고, 작업 폴더를 기획 문서만 남기고 비운 뒤 Step 0부터 다시 쌓기로 함. 단계마다 ① 만들 파일 목록 → ② 파일별 코드 설명 → ③ 실행 확인 → ④ 커밋(Conventional Commits) 순서. 최종본 완성 후 백업 삭제 예정
- **주제 변경 (최종)**: 공정 운전 이상 조사 → **국내외 화학물질 규제 브리핑·영향 분석 에이전트**. 이유: 공정 데이터를 지어내야 하는 약점, 재미·참신성·포트폴리오 논리성 부족. 새 주제는 실제 공개 규제 원문(미국 연방 관보 API 실시간 호출 확인)을 쓰고, 해당 여부·함량 기준·번역 정확성을 코드가 판정 → [docs/topic-final.md](docs/topic-final.md). 화장품 규제(MoCRA·CPNP·CSAR)는 제외하고 산업용 화학물질로 한정
  - 범위: 국내 화관법·산안법·변경 감지(법제처) / 해외 TSCA·REACH SVHC·부속서 XVII·CLP·중국 우선관리·화심법. 우선순위 1(국내 3 + TSCA + SVHC) → 2(XVII, CLP) → 3(중국·일본, 번역 시연)
  - Step 0(골격)은 주제와 무관해 그대로 사용
- **사용자 요청 기능 추가 (R54~R56)**: 제품 관리 UI(CAS 포함 제품 추가·조회), 규제 목록 UI, 답변 근거의 원문·출처 표시. 제품은 Step 4부터 앱 DB를 원본으로 하고 CSV는 초기 데이터로만 사용(재빌드 시 사용자 추가 제품 소실 방지). 근거 원문은 LLM이 아니라 코드가 문서에서 추출하고 LLM은 번역·설명만 담당
- **Step 3b 예비 Before/After (실모델 1회, 정식 측정은 Step 6)**: 같은 브리핑 질문에서 Before(LLM 단독)는 무관한 제품 2개(P007·P010)를 영향 있다고 판단하고 "MIT는 TSCA 규제 대상"이라는 규제 상태를 지어냄, 다른 문서의 의무(90일 전 통보)를 TCE에 섞음, 근거 0개, 8,083토큰. v2는 P003만, 불순물 확인 필요 2건, 근거 9개, 5,994토큰, 검토 5/5/5/5
- 개인 경력·경험은 주제 선정 근거로만 사용. 이후 공정 설계, 페르소나, 페인포인트는 경력과 무관하게 정의하고 언급하지 않음
- **화면은 Vite + Vue 3 SFC**: 레퍼런스(all_total_vue)는 CDN Vue 한 장(빌드 없음 + 같은 출처 프록시)이지만, 화면이 3개(질의응답·제품·규제)라 컴포넌트 분리가 필요하고 상용 서비스 기준에 맞춰 빌드 도구를 씀. 프록시 대신 백엔드 CORS 허용 출처로 직접 호출. 라우터 없이 탭 상태로 전환(화면 3개)
- 일정 변경: 코드와 PPT 모두 Day3 13:00 마감이므로 Day2에 코드 개발을 끝내고(코드 프리즈), Day3은 PPT·결과보고서만 작업

### 다음 할 일 (Day2 트러블슈팅·디벨롭)
- Ollama 실모델로 평가 11개 실행 → 실제 Before/After 수치 확보
- 실모델에서 발견: E01(냉각수 저하)을 qwen3:8b가 `sensor_drift`로 오진. 추론문은 "냉각수 유량이 먼저 떨어졌다"고 맞게 쓰고도 "TT-101 교정 기한 초과 + 과거 오인 사례"에 끌려 결론을 뒤집음 → 진단 결과와 코드 근거(단일 계측기 이탈·이중 계측기 일치 여부)가 모순되면 바로잡는 **진단 가드** 구현 후 Before/After 측정
- 실모델 라우터(qwen2.5:0.5b)가 "예?" 같은 짧은 메시지를 조사 요청으로 분류 → 라우터 모델 교체(qwen3:8b) 또는 짧은 메시지 코드 처리 비교
- (해결) 화면 답변이 "깡통" → fake 모드 + 라우팅 키워드 부족 + 설비 임의 추정 문제 수정, `.env`를 Ollama로 전환
- (해결) 실모델 보고서가 검토 5점인데 불합격 → 수치 대조 부호 문제, 합격 코멘트가 피드백에 섞이는 문제 수정 (troubleshooting.md)
- 첫 실모델 실행에서 서브에이전트 요약 호출이 ReadTimeout으로 그래프 전체를 멈춤 → LLM 실패 격리 추가함. 원인(동시 요청·모델 로딩) 재현 필요
- 디벨롭 후보: 서브에이전트 ReAct화, 외부 MCP 서버, Prompt Hub, 추세 차트, ADR
