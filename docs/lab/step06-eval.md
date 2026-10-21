# Step 6 — 평가와 LangSmith

> **이후 변경**: 평가 질문은 Step 8(국내 K1·K2)·Step 9(범위 판정 R1~R11)에서 **23개**로 늘었다. 대화 승인이 없어져 실행기도 승인 없이 끝까지 돈다. 늘어난 문항의 Ollama 재평가는 진행 예정.

## 목표
"개선했다"를 숫자로 보여 준다. 정답이 있는 회귀 질문 세트를 Before(LLM 단독)와 After(v2)에 **같은 입력**으로 넣고, 코드 채점기 + LLM-as-Judge로 비교한다. 화면의 👍/👎는 LangSmith Run 피드백으로 남긴다.

```
data/eval/questions.json (11문항 + 정답)        관보 입력 고정 (FEED_MODE=snapshot)
            │                                        │
            ▼                                        ▼
  scripts/run_eval.py ──▶ Before 그래프 (briefing 5문항) ─┐
                     └──▶ After(v2) 그래프 (11문항) ──────┤
                                                          ▼
              app/eval/metrics.py (코드 채점) + judge() (LLM-as-Judge, 같은 참조 자료)
                                                          ▼
                        docs/experiments/<날짜>-<LLM>.md/.json   (+ --langsmith: Dataset·Experiment)
```

## 만드는 파일

| 파일 | 역할 | 요구사항 |
| --- | --- | --- |
| `data/feeds/fulltext/*.txt` | 스냅샷 관보 4건의 본문 (미국 정부 공개 문서) | 재현성 |
| `app/core/config.py`, `mcp_servers/reg_feed_server.py` (수정) | `FEED_MODE=snapshot`: 실시간 호출 없이 저장된 목록·본문만 | 재현성 |
| `data/eval/questions.json` | 회귀 질문 11개(briefing 5 · lookup 4 · chat 2) + 사람이 정한 정답과 라벨 근거 | R42 |
| `app/eval/metrics.py` | 코드 채점기: 영향 제품 정밀도·재현율, 핵심 날짜, 지어낸 CAS·날짜, 근거 검증, 키워드, 금지 표현 | R43 ① |
| `app/eval/runner.py` | 질문 하나 실행(승인 자동) + 채점 기준 자료(corpus) | — |
| `scripts/run_eval.py` | 실험 실행 → 비교표. `--judge` LLM-as-Judge, `--langsmith` Dataset + `aevaluate()` | R42, R43 ② |
| `app/core/tracing.py`, `app/service.py` (수정) | 👍/👎 → LangSmith Run feedback (`user_score`) | R41 |
| `app/agents/tooling.py` (수정), `tests/conftest.py` | MCP 도구 호출을 LangSmith 도구 Run으로 기록, 테스트에서는 트레이싱 끔 | R40 |
| `tests/test_eval.py`, `tests/test_graph.py` (추가) | 채점기 단위 테스트, 실험 스크립트 스모크, 조회 회귀 | — |

## 설계 포인트
- **입력 고정**: 실시간 관보는 날마다 바뀌어 같은 실험을 반복할 수 없다 → 스냅샷 목록 + 본문 파일
- **정답은 파이프라인과 독립**: 규제 DB·제품 배합·관보 원문을 보고 사람이 정함 (`label_basis`). 음성 대조 문항(B5: DEHP 변경 없음, L4: 없는 제품) 포함
- **같은 채점기로 Before·After**: 답변 텍스트만 본다 (내부 상태를 보면 v2에 유리)
- **LLM-as-Judge도 같은 참조 자료**: 각자의 근거로 채점하면 근거가 없는 Before가 구조적으로 불리 → 라벨 근거·정답표를 둘 다에 준다
- **Before는 briefing만 비교**: lookup·chat은 두 그래프가 같은 코드 → v2 회귀로만 본다
- **채점기의 한계를 명시**: 키워드는 맥락을 못 본다, 영향 제품은 부정 표현 규칙에 의존, Judge는 같은 모델이면 관대할 수 있다

## 따라 하기

```bash
uv run pytest -q
```

```bash
LLM_BACKEND=fake uv run python scripts/run_eval.py --judge
```

fake는 규칙 기반이라 점수 자체는 의미가 없고, 흐름(실행 → 채점 → 보고서) 확인용이다.

```bash
LLM_BACKEND=ollama uv run python scripts/run_eval.py --judge
```

LangSmith (선택): `.env`에 `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT=chem-reg-briefing`

```bash
LLM_BACKEND=ollama uv run python scripts/run_eval.py --judge --langsmith
```

→ Dataset `chem-reg-eval`에 11문항, Experiments에 `baseline-…`·`v2-…` 두 실험. 화면 👍/👎는 해당 Run의 `user_score` 피드백.

## 결과 (2026-10-20, Ollama qwen3:8b)
최종 측정: [docs/experiments/2026-10-21-1007-ollama-qwen3-8b.md](../experiments/2026-10-21-1007-ollama-qwen3-8b.md) — 외부 검토 결함 수정·공식 목록 전체 확장·규정 준수 제품 8개 추가 후

| 지표 (briefing 5문항) | Before (LLM 단독) | After (v2) |
| --- | --- | --- |
| 영향 제품 정밀도 | 0.32 | **1.0** |
| 무관한 제품 지목 수 | 35 | **0** |
| 핵심 날짜 재현율 | 0.9 | **1.0** |
| 지어낸 날짜 | 3 | **0** |
| 답변당 근거 수 / 근거 요건 충족률 | 0 / 0.2 | **8.8 / 1.0** (근거 44개 전부 원문 대조 통과) |
| Judge 근거 충실성 · 합격률 | 4.2 · 1.0 | 4.6 · 1.0 |
| 평균 시간 · 토큰 | 98초 · 9,135 | 95초 · 6,565 |

v2 전체 11문항 회귀: 라우팅 1.0 · 영향 제품 정밀도 1.0 · 재현율 1.0 · 근거 73개 전부 원문 대조 통과 · 금지 표현 0 · 실행 오류 0

**관찰**
- Before의 가장 큰 문제는 **무관한 제품 지목**: B5("DEHP 관련 변경 있어?")에서 제품 20개 전부를 영향 있다고 씀. 규정 준수 제품을 추가하자 오탐이 21 → 35로 늘었다 — 판단을 LLM에 맡기면 제품이 늘수록 틀린다
- After는 B5에 "요청한 범위(DEHP)의 변경 문서를 찾지 못했습니다"를 먼저 말하고, 범위 밖 TCE 문서는 참고로만 적는다 (1차 측정의 약점을 코드로 해결: 요청 범위 확정 → 범위 밖 문서는 영향 분석 제외)
- **LLM-as-Judge의 한계**: Before 합격률 1.0 — 오탐 20개 답변에도 합격. 같은 소형 모델이 채점하면 관대하다 → 코드 채점기를 주 지표로, Judge는 보조로 쓴다
- v2는 토큰이 28% 적다 — 원문 전체 대신 코드가 고른 근거 문장만 LLM에 준다

**측정 과정에서 고친 것** (5회 측정)
- 1차(18:54): 정밀도 0.8 — B5가 범위 밖 문서를 브리핑 → 요청 범위 제어
- 2차(21:47): 조회 근거 일부가 "원문 확인 안 됨" — 채점 기준 자료에 공식 전체 목록(bulk)이 빠져 있었음. L2 답변에 함유 제품 누락, `[근거 N]` 형식 → 채점 범위 수정, 함유 제품 코드 보장, 근거 번호 정규화
- 3차(22:51): B5의 범위 밖 참고 목록에 코드가 넣은 관보 번호를 가드가 "지어낸 숫자"로 잡아 Judge 2점 → 관보 번호·게시일을 가드의 공식 메타데이터에 포함
- 화면 캡처 중: 실모델이 핵심 변경을 "요청 범위 밖"으로 표시 → 범위 안내·참고 목록을 코드가 넣음
- 4차(10-21 09:40): 근거 번호 나열 "[1], [2], … [6]"의 4·5를 가드가 지어낸 숫자로 잡아 재작성 반복(B4 224초) → 숫자 대조에서 `[n]` 제외
- 5차(10:07): 경고 0건 — 위 표

## LangSmith 확인 (R40·R41)
- 트레이스: 질문 1건 = 루트 Run `chem-reg:v2` → 노드(route·lookup·…) → MCP 도구 Run(`mcp:judge_product_compliance`, 입력은 인자·출력은 요약만)
- 피드백: 화면 👍 → 같은 Run에 `user_score = 1` (SSE `run_id` = LangSmith Run ID)
- 테스트 실행은 트레이스를 보내지 않음 (`tests/conftest.py`에서 끔)

## LangSmith Dataset·실험 (R42)

```bash
LLM_BACKEND=ollama uv run python scripts/run_eval.py --langsmith --skip-local --ids B1 B5 L1 L4
```

- Dataset `chem-reg-eval`: 11문항 전부 (입력 = 질문, 정답 = expect, 메타데이터 = id·category)
- 실험 2개 — 같은 코드 채점기를 LangSmith 평가자로 등록해 점수가 Experiments 화면에 남는다

| 실험 (대표 문항) | 영향 제품 정밀도 | 지어낸 사실 | 근거 요건 | 오류 |
| --- | --- | --- | --- | --- |
| `baseline-ollama-qwen3-8b` (B1·B5) | 0.167 | 평균 0.5 | 0.5 | 0 |
| `v2-ollama-qwen3-8b` (B1·B5·L1·L4) | 0.75 | 0 | 1.0 | 0 |

Dataset 화면의 Compare에서 두 실험을 문항별로 나란히 볼 수 있다 (v2의 0.75는 B5 — 위 "v2 약점"과 같은 원인).

## 실제로 겪은 문제
- **평가 세트가 v2 조회 누락 2건을 잡음** — 물질 질문에 함유 제품이 빠짐, 없는 제품을 "ID를 못 찾음"으로 안내 → lookup에 `find_products_by_cas`, 미등록 제품 명시
- **채점기 오탐** — 서비스 안내의 "(예: P003)"를 영향 제품 지목으로 셈 → 예시 표현 제외
- **MCP 도구 호출이 트레이스에 안 보임** → 에이전트가 MCP 세션을 직접 부르므로 LangChain 도구 Run이 생기지 않음 → `traceable(run_type="tool")`로 감쌈
- **테스트가 LangSmith로 트레이스를 보냄** → `.env`의 키를 읽기 때문 → 테스트에서 트레이싱 끔
- **오프라인 테스트가 고정 본문을 읽음** — "본문 없음" 상황 테스트에서 새 고정 본문 폴더도 비움
- 자세한 내용: [troubleshooting.md](../../troubleshooting.md)
