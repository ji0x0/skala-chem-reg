# AI Mini-Project 진행 계획

> 출처: `example/AI-Mini-Project_20261004_2.pdf`
> Day1 = 2026-10-20(화) 기준으로 작성. 진행 중 수정 가능.

## 1. 과제 개요

- **Base AI Agent**: `all_total_vue` (장애 분석 에이전트, LangGraph 기반). 메인 매뉴얼은 `doc/README.md`
- **과제 선택 (택 1)**
  1. Base AI Agent 기능 개선/추가 — 제약 없음
  2. 신규 프로젝트 개발 — 주제 제약 없음 (Base Agent 주제를 다른 주제로 바꿔 신규 Agent로 개발해도 됨)
- AI 도구 사용 제약 없음. **단, 작성한 코드와 내용을 직접 설명할 수 있어야 함**

## 2. 최종 산출물

| 산출물 | 마감 | 제출처 |
| --- | --- | --- |
| 선택 과제 + 진행계획(초안) | Day1 17:00 | Google Spread (소속 반에 UID, 성함 작성) |
| GitHub 저장소 주소 (코드) | Day3 13:00 | Google Spread |
| 결과보고서 주소 (온라인 문서, **읽기 권한이 부여된 링크**) | Day3 13:00 | Google Spread |
| 발표 PPT | Day3 13:00 | 결과보고서와 함께 제출 |
| 개인별 발표 | Day3 17:30 | 반별 자율 진행, **자기 자리에 앉아서 발표** |

> **Git 주소와 최종 보고서 주소는 Day3 13:00까지 입력 필수.** 보고서 링크는 제출 전에 로그인하지 않은 상태(시크릿 창)로 열리는지 확인한다.
>
> 코드와 PPT 모두 Day3 13:00 마감. **코드 개발은 Day2에 끝내고(코드 프리즈), Day3은 PPT·보고서만 작업한다.**

진행계획 양식: `순번 | 영역 | 무엇을 바꾸나 | 추가 설명` (2번 과제는 주제 + 세부 기능 리스트)

## 3. 서비스 구성

상용 서비스 기준으로 **사용자 프론트엔드(Vue) + 백엔드 API(FastAPI) + 관리자 대시보드(LangSmith)** 3개로 구성한다. 발표 데모도 이 세 화면을 보여준다.

교수님 가이드라인(필수): LangChain + LangGraph + LangSmith 멀티에이전트, MCP(직접 제작 또는 외부 서버), REST API 기반 FastAPI, Vue.js 프론트엔드, 스트리밍 응답, **스텝 바이 스텝(핸즈온 랩) 형식으로 완성**. 상세는 [REQUIREMENTS.md](REQUIREMENTS.md) "0-1".

## 3-1. 평가 항목 (총 100 + 보너스 10)

| 항목 | 배점 | 기준 | 대응 방안 |
| --- | --- | --- | --- |
| 기능 구현 완성도 | 30 | 선택한 개선안이 실제로 동작하는가 | 기능별 데모 시나리오 + 회귀 쿼리로 동작 확인 |
| Before/After 실측 비교 | +10 (보너스) | 같은 입력으로 개선 전/후 수치(지연시간, 비용, 검색 정확도, retry 횟수 등) 비교 | 구현 전에 baseline 먼저 측정해 두기 |
| 기술 요소 반영 | 30 | Multi-Agent, MCP, RAG, 의존성 주입, LangSmith, 모듈화, 단위 테스트 | 기능 리스트에 기술 요소를 매핑해서 누락 방지 |
| 한계·트레이드오프 설명 | 20 | 개선이 새로 만든 약점을 스스로 짚었는가 (예: 임베딩 비용·지연, 그래프 무한 루프) | DEVLOG에 기능마다 트레이드오프 메모 |
| 발표 PPT 및 발표 | 20 | 문제 → 개선/추가 포인트 → Before/After 수치 → 한계 및 추가 개선 순서 | PPT 목차를 이 순서로 고정 |

## 4. Base Agent 실행 순서 (참고)

| 순번 | 명령 | 비용 | 용도 |
| --- | --- | --- | --- |
| 1 | `bash sh/setup_venv.sh` | 없음 | `.venv` 생성 + requirements 설치 |
| 2 | `bash sh/setup_ollama.sh` | 없음 | 로컬 Ollama 모델(qwen3:0.6b/8b) 리셋 |
| 3-1 | `bash sh/run_agent_ollma.sh` | 없음 | 백엔드 기동 (로컬 추론) |
| 3-2 | `bash sh/run_agent_openai.sh` | **과금** | 백엔드 기동 (OpenAI API) |
| 4 | `bash sh/run_frontend.sh` | 백엔드에 따름 | http://localhost:8600 채팅 UI |

- 실행 순서: 1 → 2 → 3-1 → 4. 개발이 어느 정도 정리된 뒤 3-1 대신 3-2로 테스트
- 테스트 쿼리: `doc/regression_test_queries.md`

## 5. PDF의 개선 포인트 예시 (과제 1번용)

| 순번 | 영역 | 무엇을 바꾸나 |
| --- | --- | --- |
| 1 | RAG | 키워드 기반 incident_type 매핑 → runbook 벡터DB 의미 검색 |
| 2 | 모듈화 | 그래프 노드를 별도 모듈로 분리 |
| 3 | 그래프 개선 | research 노드를 로그/메트릭/런북 서브에이전트로 분리 (멀티에이전트) |
| 4 | 그래프 개선 | Human-in-the-loop 승인 노드 (`interrupt()`, write → validate 사이) |
| 5 | 메모리 | 10턴 이상 시 과거 턴 요약 압축 — 토큰·컨텍스트 실측 비교 |
| 6 | 평가 | `eval/run_eval.py`에 LLM-as-judge 평가자 추가 |
| 7 | 그래프 개선 | 프롬프트 조회, 기본 Target System 등 하드코딩 개선 |
| 8 | 데이터 보강 | incident_type 등 샘플 데이터 확장 |

## 6. 진행 단계

| 단계 | 내용 | 결과물 |
| --- | --- | --- |
| 0 | PDF 확인 → 산출물·요구사항 파악, 일정 수립 | 이 문서 |
| 1 | AI capstone 강의 흐름 파악 → 프로세스 적용 | [REQUIREMENTS.md](REQUIREMENTS.md) (요구사항 53개, 수행 업무 W1~W13) |
| 2 | `all_total_vue_student` 실행·분석 → 레퍼런스화 | [docs/base-analysis.md](docs/base-analysis.md), REQUIREMENTS.md `Base` 열 |
| 3 | GitHub 오픈소스 ai-service 탐색 | [docs/oss-research.md](docs/oss-research.md) |
| 4 | 페르소나 + 페인포인트 정의 → 주제 선정 | [docs/topic-final.md](docs/topic-final.md) (주제, 페르소나, 페인포인트, Spread 진행계획) |
| 5 | 개발 중 상시 기록 | `DEVLOG.md`, `troubleshooting.md` |

## 7. 일정

### Day1 — 10/20(화)
- [x] 09:00–10:00 Base AI Agent 및 과제 설명
- [x] 0단계: 요구사항·일정 정리
- [x] 1단계: capstone 강의 요약 + 실습 10종 정리 → REQUIREMENTS.md
- [x] 2단계: Base Agent 기동(fake) + 코드 구조 분석 → [docs/base-analysis.md](docs/base-analysis.md)
- [x] 3단계: GitHub 오픈소스 탐색 → [docs/oss-research.md](docs/oss-research.md)
- [x] 4단계: 주제 확정 → **국내외 화학물질 규제 브리핑·영향 분석 에이전트** ([docs/topic-final.md](docs/topic-final.md)). 과정 기록: [1차](docs/topic-selection.md), [2차](docs/topic-domain.md)
- [ ] **17:00까지 Google Spread에 선택 과제 + 진행계획(초안) 등록**

- [ ] **Day1 오후~저녁: 코드 완성** — 핸즈온 랩 단계(`docs/lab/`)로 한 단계씩 쌓고, 단계마다 설명·실행 확인·커밋
  - 1차 초안은 한 번에 작성돼 단계별 확인이 어려워 `_backup/full-draft-20261020/`에 백업 후 Step 0부터 다시 진행
  - Step 0 프로젝트 골격 → Step 1 가상 공정 데이터 → Step 2 분석 코어·MCP 서버 → Step 3 LLM·멀티에이전트 그래프 → Step 4 FastAPI REST·SSE → Step 5 Vue 프론트 → Step 6 평가·테스트

### Day2 — 10/21(수) · 트러블슈팅·디벨롭
- [ ] Ollama 실모델로 전체 시나리오 실행, 발견한 문제 수정 (`troubleshooting.md` 기록)
- [ ] Before(baseline) vs After(v2) 측정, 비교표 작성
- [ ] 디벨롭: 우선 2·3 규제(XVII, CLP, 중국 우선관리, 화심법) 확장, 외부 MCP 서버, Prompt Hub (topic-final.md)
- [ ] ADR, README 정리, **코드 프리즈 + GitHub push**

### Day3 — 10/22(목) · PPT·보고서만
- [ ] 오전: 발표 PPT 작성 (문제 → 개선 포인트 → Before/After 수치 → 한계 및 추가 개선)
- [ ] 오전: 결과보고서 작성 (Google Spread)
- [ ] **13:00까지 Google Spread에 Git 주소 + 결과보고서 주소 등록, PPT 제출**
- [ ] 오후: 발표 리허설
- [ ] 17:30 개인별 결과보고서 발표
