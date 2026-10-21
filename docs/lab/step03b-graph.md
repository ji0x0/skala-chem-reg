# Step 3b — LangGraph 멀티에이전트

> **이후 변경**: Step 9에서 그래프 앞부분이 바뀌었다. 질문 분류(`route`)는 **질문 이해·범위 판정**(`understand → inform`)으로, 대화 답변의 `approval` 노드(영향 제품 공유 승인)는 **제거**했다 — 승인해도 실제로 일어나는 일이 없었다 ([설계 9절](../routing-architecture.md)). 아래 `run_graph.py --approve`도 함께 없앴다. 수집 에이전트는 Step 8(국내 ReAct)·Step 11(EU)에서 늘었다.

## 목표
Step 3a의 부품(LLM·근거 추출·MCP 도구)을 LangGraph로 묶는다. 경로를 한 갈래씩 붙여 가며 실행해 본다.

```
route ─ chat ────▶ chat_answer ──────────────────────────────────────────────▶ finalize
      ├ lookup ──▶ lookup (물질·제품 → 등재 조회·코드 판정 → 근거 답변) ──────▶ finalize
      └ briefing ▶ plan ▶ gate ═Send═▶ [us_feed | kr_feed | regdb] (병렬) ▶ review ─부족─▶ (재조사)
                    ▶ summarize(요약·근거 번역·무결성) ▶ impact(코드 판정) ▶ write(스트리밍)
                    ▶ guard ▶ validate ─불합격(상한 내)─▶ write
                                      └─▶ approval(영향 제품 공유 승인, interrupt) ▶ finalize
```

## 만드는 파일

| 파일 | 역할 | 캡스톤 연결 |
| --- | --- | --- |
| `app/agents/state.py` | 공유 State + 리듀서 (병렬 결과 합치기, 질문마다 RESET) | Wave 4 State |
| `app/agents/deps.py` | AgentDeps (설정·LLM·도구, 물질·제품 목록 1회 로드) | Wave 13 의존성 주입 |
| `app/agents/tooling.py` | 도구 호출 공통: 진행 이벤트, 재시도, 실패 격리 | Wave 9 에러 처리 |
| `app/agents/subagents.py` | 해외 수집 / 국내 수집 / 규제 DB 대조 (Send 병렬) | Wave 10b 병렬 |
| `app/agents/graph.py` | v2 그래프 (chat·lookup·briefing) | Wave 4~8, 15 |
| `app/agents/baseline.py` | Before: LLM 단독 | Wave 14 버전 비교 |
| `scripts/run_graph.py` | 질문 하나를 실행해 진행 이벤트 출력 (`--approve`, `--baseline`) | — |
| `tests/test_graph.py` | 경로·병렬·승인·격리·가드·상태 초기화·Before | Wave 13 테스트 |

## 노드별 역할 (briefing)

| 노드 | 하는 일 | LLM |
| --- | --- | --- |
| plan | 기간·지역·물질·제품 추출 (형식 오류 시 코드 규칙) | fast |
| gate | 계획을 코드로 검증: 없는 제품 제외, 질문 속 제품 ID 보정, 물질 → CAS, 수집 가능한 지역만 작업 생성 | — |
| research ×N | 해외 수집(관보 → 회사 관련 물질이 언급된 문서만 → 근거 문장) ∥ 국내 수집(키 없으면 비활성 기록) ∥ 제품 판정 | — |
| review | 관련 문서 0건이면 기간을 30일로 넓혀 재조사(1회). 실패·비활성·요약본 대체를 "확인하지 못한 항목"으로 | — |
| summarize | 문서 요약 + 근거 문장별 번역 + 무결성 검사 (번역: 누락도 오류 → 번역 버리고 원문만 / 요약: 지어냄만 오류) | quality |
| impact | 문서에 언급된 물질 → 그 물질이 든 제품 → 그 문서 지역 판정만 (코드) | — |
| write | 5개 절, 근거 번호, 토큰 스트리밍, 코드 블록 감싸기 제거 | quality |
| guard | 지어낸 숫자·CAS·날짜, 없는 근거 번호, 빠진 절, 근거 미표기 (코드) | — |
| validate | LLM-as-Judge + 코드 검사. 작성 2회·검토 3회 상한, 미달이면 안내 문구 | quality |
| approval | 영향 제품이 있으면 `interrupt()`로 공유 승인 대기 → `Command(resume=...)`로 재개 | — |

## 따라 하기

```bash
uv add langgraph langgraph-checkpoint-sqlite
```

## 확인 (Ollama 실모델, qwen3:8b)

1) chat · lookup

```bash
LLM_BACKEND=ollama uv run python scripts/run_graph.py "P002 규제 문제 있어?"
```

```
     2.2s [tool_call_end] {"agent": "lookup", "tool": "judge_product_compliance", "ok": true, "summary": "exceeds 2 · listed 2 · review 0 · below 3", ...}
제품 P002 저취 PVC 바닥재 (수출 EU)은 규제 문제 있습니다.
[1] exceeds · EU 부속서 XVII 제한 물질 · 프탈산 비스(2-에틸헥실) (DEHP) 0.08% · Entry 51 대상 물질 합계 0.11 wt% > 기준 0.1 wt%
...
공식 원본 확인 전 데이터입니다. 법률 자문이 아니며 최종 판단은 담당자가 합니다.
[완료] 15.8s · 토큰 1,330 · 근거 4개
```

2) briefing (v2) — 자동 승인까지

```bash
LLM_BACKEND=ollama uv run python scripts/run_graph.py --approve "이번 주 미국 EPA랑 국내 규제 변경 브리핑해줘"
```

```
     3.9s [plan] {"days": 7, "regions": ["US", "KR"], "tasks": ["us_feed", "kr_feed"], ...}
     3.9s [agent_end] {"agent": "kr_feed", "ok": true, "summary": "비활성 — 키 미설정"}
     6.3s [agent_end] {"agent": "us_feed", "ok": true, "summary": "문서 3건 중 회사 관련 물질 언급 1건"}
    43.1s [summary] {"document_number": "2026-20964", "title_ko": "트리클로로에틸렌(TCE)의 독성물질관리법(TSCA) 규제 준수 기한 연장", "citations": 6}
    43.1s [impact] {"products": ["P003"], "findings": 3}
## 요약 ... ## 규제 변경 (지역별) ... ## 우리 제품 영향 ... ## 할 일과 기한 ... ## 확인이 필요한 항목 ...
    77.2s [guard] {"invented": {}, "unknown_citations": [], "missing_sections": [], "uncited": false}
    88.5s [validation] {"attempt": 1, "passed": true, "scores": {"relevance": 5, "completeness": 5, "faithfulness": 5, "clarity": 5}}
  ⏸ 승인 대기: {"impacted_products": [{"product_id": "P003", ...}]}
[완료] 88.5s · 토큰 5,994 · 근거 9개
```

3) 같은 질문을 Before(LLM 단독)로

```bash
LLM_BACKEND=ollama uv run python scripts/run_graph.py --baseline "이번 주 미국 EPA랑 국내 규제 변경 브리핑해줘"
```

관찰 결과 (2026-10-20, 1회 실행 — 정식 측정은 Step 6):

| 항목 | Before (LLM 단독) | v2 |
| --- | --- | --- |
| 영향 제품 | P003 + P007(PFOA)·P010(MIT) — 이번 문서와 무관, "MIT는 TSCA 규제 대상"이라고 지어냄 | P003만 (언급 물질 × 제품 CAS 대조) |
| 의무 | "TCE 사용 시 90일 전 EPA 통보, 12/14까지" — 다른 문서(SNUR)의 의무를 TCE에 섞음 | 근거 문장 기반 "의견 제출 검토 (마감 11/13)" |
| 불순물 | 언급 없음 | PCE·사염화탄소 "확인 필요" |
| 근거 | 0개 | 9개 (원문 + 번역 + 출처) |
| 토큰 / 시간 | 8,083 / 84.8초 | 5,994 / 88.5초 |

4) 테스트

```bash
uv run pytest -q
```

```
54 passed
```

## 실제로 겪은 문제
- **관보 본문 동시 요청이 429로 막히고 요약본으로 조용히 대체** → 본문 캐시, 1건씩 다운로드, Retry-After 1회 재시도, 대체 사실을 "확인하지 못한 항목"에 표시
- **문서 요약 무결성 "실패"가 실은 날짜 생략** → 요약은 지어냄=오류·누락=경고, 근거 번역은 누락도 오류
- **브리핑이 ```markdown 코드 블록으로 감싸져 나옴** → 작성 결과에서 벗김
- chat 답변이 막연함 → 서비스 안내를 context로 제공 / lookup 답변에 판정 이유 누락 → 프롬프트에 "결과와 이유를 함께"
- 자세한 내용: [troubleshooting.md](../../troubleshooting.md)

## 다음 단계
Step 4에서 이 그래프를 FastAPI REST + SSE로 노출한다 (SQLite 체크포인터, 승인 API, 제품 관리·규제 목록 API).
