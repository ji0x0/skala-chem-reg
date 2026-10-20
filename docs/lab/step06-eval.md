# Step 6 — 평가와 LangSmith

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

## 결과 (2026-10-20, Ollama qwen3:8b, 1회)
전체 표: [docs/experiments/2026-10-20-1854-ollama-qwen3-8b.md](../experiments/2026-10-20-1854-ollama-qwen3-8b.md)

| 지표 (briefing 5문항) | Before (LLM 단독) | After (v2) |
| --- | --- | --- |
| 영향 제품 정밀도 | 0.357 | **0.8** |
| 무관한 제품 지목 수 | **21** | 1 |
| 핵심 날짜 재현율 | 1 | 1 |
| 지어낸 날짜 | 1 | 0 |
| 답변당 근거 수 / 근거 요건 충족률 | 0 / 0.2 | **9.8 / 1.0** (근거 49개 전부 원문 대조 통과) |
| Judge 근거 충실성 · 합격률 | 3.8 · 0.6 | 4.2 · 1.0 |
| 평균 시간 · 토큰 | 91초 · 8,151 | 97초 · 6,395 |

v2 전체 11문항 회귀: 라우팅 1.0 · 영향 제품 정밀도 0.909 · 재현율 1.0 · 금지 표현 0 · 실행 오류 0

**관찰**
- Before의 가장 큰 문제는 **무관한 제품 지목**: B5("DEHP 관련 변경 있어?")에서 12개 제품 전부를 "EPA 통보가 필요할 수 있음"이라고 씀 — SNUR(신규 사용 규칙) 의무를 모든 성분에 갖다 붙임. TCE 효력일 `2026-12-31`도 지어냄
- 날짜 재현율은 둘 다 1 — 원문을 통째로 주면 LLM도 날짜는 잘 옮긴다. 차이는 "어느 제품이 왜 해당하는가"에서 난다
- **LLM-as-Judge의 한계가 수치로 보임**: 위 B5 Before 답변(12개 오탐 + 지어낸 날짜)에 Judge가 5점. 같은 소형 모델이 채점하면 관대하다 → 코드 채점기를 주 지표로, Judge는 보조로 쓴다
- **v2 약점 (Day2 개선 대상)**: B5에서 "DEHP 관련 변경은 없다"고 답하지 않고 TCE 문서를 브리핑하며 P003을 영향 제품으로 듦. 사실은 맞지만 질문에 답하지 않음 → 요청 물질과 관련된 문서가 없으면 그 사실을 먼저 밝히도록 개선 예정
- v2는 토큰이 22% 적다 — 원문 전체 대신 코드가 고른 근거 문장만 LLM에 준다. 시간은 검토·재작성 때문에 비슷

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
