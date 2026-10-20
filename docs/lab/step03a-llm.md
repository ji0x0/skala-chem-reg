# Step 3a — LLM 계층, 근거 추출, 도구 연결

## 목표
그래프(Step 3b)를 만들기 전에 부품 세 가지를 따로 만들고 실모델로 확인한다.
1. **LLM 계층**: LangChain으로 Ollama·OpenAI를 같은 코드로 부르고, 구조화 출력·토큰 스트리밍 지원
2. **근거 추출 (R56)**: 원문 문장은 코드가 문서에서 잘라 온다. LLM은 그 문장만 보고 요약·번역한다
3. **도구 연결**: MCP 서버 3개에 지속 세션으로 연결하고, 오류를 `ToolError`로 통일

## 만드는 파일

```
app/core/config.py         LLM 백엔드·모델(fast/quality)·가정 단가·도구 타임아웃
app/llm/
├── schemas.py             RouteDecision, BriefingPlan, DocumentSummary(+KeyDate), Judgement
├── prompts.py             ROUTE, PLAN, SUMMARIZE_DOC, WRITE_BRIEFING, JUDGE, ANSWER + 근거 규칙
├── base.py                AgentLLM 인터페이스 (6개 메서드, 모두 (결과, usage) 반환)
├── fake.py                결정론 Fake (테스트 전용, 화면 데모에 쓰지 않음)
└── langchain_llm.py       init_chat_model, with_structured_output(include_raw), astream, build_llm()
app/domain/citations.py    extract_quotes, quote_in_source, from_document, from_listing, official_dates
app/tools/provider.py      MCPToolProvider(stdio 지속 세션) / InMemoryToolProvider(테스트) / call_with_retry
scripts/llm_smoke.py       관보 문서 → 근거 문장 → 용어집 → LLM 요약 → 무결성 검사
tests/test_citations.py, test_llm.py, test_provider.py
```

## 설계 요점

| 원칙 | 구현 |
| --- | --- |
| 공급자를 바꿔도 코드는 그대로 | `LLM_BACKEND=fake/ollama/openai` 하나로 전환 (`build_llm`) |
| LLM 답은 양식으로 받는다 | Pydantic 스키마 + `with_structured_output`. 형식이 깨지면 `None` → 부르는 쪽이 코드 규칙으로 대체 |
| 원문은 코드가, 해석은 LLM이 | `extract_quotes`가 물질이 나온 문장을 원문 그대로 추출 (날짜 있는 문장 우선), `quote_in_source`로 출처에 실제 있는지 확인 |
| 날짜는 코드가 | 게시일·의견 마감일·시행일은 관보 API 값을 그대로 (`official_dates`) |
| 오류는 한 가지 모양으로 | 두 제공자 모두 `ToolError(transient)`. 시간 초과만 0.5초 → 1.5초 재시도 |

## 따라 하기

```bash
uv add langchain langchain-core langchain-ollama langchain-openai langchain-mcp-adapters
```

`.env`에 `LLM_BACKEND=ollama`를 넣거나 명령 앞에 붙인다. Ollama가 떠 있고 `qwen3:8b`가 있어야 한다.

```bash
ollama list
```

## 확인

1) 질문 분류·계획 (실모델)

```bash
LLM_BACKEND=ollama uv run python -c "import asyncio; from app.core.config import Settings; from app.llm.langchain_llm import build_llm; llm = build_llm(Settings()); print(asyncio.run(llm.route('이번 주 미국 EPA랑 국내 규제 바뀐 거 브리핑해줘')))"
```

실행 결과 예시 (qwen3:8b, 첫 호출은 모델 로딩 포함 약 6초, 이후 2~3초):

| 질문 | 분류 |
| --- | --- |
| 안녕, 뭘 할 수 있어? | chat |
| 트리클로로에틸렌 79-01-6 미국에서 규제 대상이야? | lookup |
| 이번 주 미국 EPA랑 국내 규제 바뀐 거 브리핑해줘 | briefing |
| 예? | chat (1차 초안의 0.5B 모델은 briefing으로 오분류) |

계획: "최근 2주 미국이랑 EU 규제 중 P003, DEHP 관련 브리핑" → `days=14 regions=['US','EU'] substances=['DEHP'] product_ids=['P003']`

2) 부품 연결 스모크 (실제 관보 + 실모델)

```bash
LLM_BACKEND=ollama uv run python scripts/llm_smoke.py
```

```
[문서] 2026-20964 (live, full_text) Trichloroethylene (TCE); Regulation Under the Toxic Substances Control Act (TSCA
[언급 물질] [('트리클로로에틸렌', 167), ('사염화탄소', 1), ('테트라클로로에틸렌', 1)]
[근거 문장] 본문 42,923자 → 6개 2,129자 (원문 포함 확인)
[용어집] ['Federal Register', 'Section 6', 'TSCA', 'compliance date', 'mixture']

[LLM 요약] ollama:qwen3:8b 12.4s, 토큰 1184
  제목: 트리클로로에틸렌(TCE); 독성물질관리법(TSCA) 하의 규제; 준수 기한 연장
  요약: 환경보호국(EPA)은 TCE에 대한 규제를 받는 특정 기업의 준수 기한을 2027년 12월 31일까지 연장하려고 한다. ...
  본문 속 날짜(LLM): [('게시일', '2026-10-14'), ('의견 마감일', '2026-11-13'), ('준수 기한 연장', '2027-12-31'), ('기존 준수 기한', '2027-06-07')]
  공식 날짜(코드): [('게시일', '2026-10-14'), ('의견 제출 마감', '2026-11-13')]
  할 일: 해당 용도 사용 여부 확인 및 의견 제출 검토
[무결성 검사] 통과 {... 'extra_dates': [], 'extra_numbers': [], 'ok': True}
```

본문 4만 자를 근거 문장 2천 자로 줄여 LLM에 넣는다 → 토큰·시간·지어낼 여지가 함께 준다.

3) 테스트

```bash
uv run pytest -q
```

```
47 passed
```

## 실제로 겪은 문제
- **요약의 "할 일"에 판정 라벨(exceeds)이 들어감, 핵심 날짜를 비움** → 판정 규칙을 요약 프롬프트에서 분리, 공식 날짜는 코드가 채움, 무결성 검사에 `reference`(메타데이터 사실: 써도 되고 빠져도 됨) 추가
- **문장 나누기가 "TSCA. You"를 붙임** → 대문자 두 글자 이상 뒤 마침표에서 끊도록 수정 ("U.S."는 보호)
- 자세한 내용: [troubleshooting.md](../../troubleshooting.md)

## 다음 단계
Step 3b에서 LangGraph로 이 부품들을 묶는다: 질문 분류 → 계획 → 국내·해외 수집과 규제 DB 대조 병렬 → 문서 요약 → 영향 판정 → 브리핑 작성 → 가드·검토 → 승인.
