# Step 2 — 판정 코어와 MCP 서버

## 목표
1. **규제 해당 여부를 코드가 판정**한다 (LLM 없음). 이 결과가 이후 LLM이 지어내지 못하게 막는 근거가 된다.
2. 번역·요약 결과의 숫자·CAS·날짜를 원문과 대조하는 검사기를 만든다.
3. 이 기능들과 해외 규제 원문 조회를 **MCP 서버 3개**로 노출한다.

## 만드는 파일

```
app/
├── core/config.py           관보 API 주소, 법제처 OC 키, HTTP 타임아웃 추가
├── repositories/reg_db.py   SQLite 조회 (DB 접근은 여기 한 곳)
└── domain/
    ├── judge.py             판정 규칙: 지역 → 형태 → 함량 판정 불가 사유 → 함량·합산 비교 → 등재·불순물
    ├── integrity.py         원문 vs 번역문 CAS·날짜(ISO 통일)·숫자 대조
    └── mentions.py          문서 본문에서 물질 이름·약어 → CAS 매칭
mcp_servers/
├── _common.py
├── product_server.py        MCP product: list_products, get_product, find_products_by_cas
├── reg_db_server.py         MCP reg-db: list_regulations, lookup_substance, judge_product_compliance,
│                            judge_all_products, glossary_lookup / Resource regulation://{reg_id} /
│                            Prompt briefing_procedure
└── reg_feed_server.py       MCP reg-feed: search_federal_register, get_federal_register_document,
                             search_kr_admin_rules (LAW_API_OC 설정 시)
scripts/mcp_stdio_check.py   3개 서버를 stdio 프로세스로 띄워 한 클라이언트로 연결
tests/test_judge.py, test_integrity.py, test_mcp_servers.py
```

## 판정 규칙 (judge.py)

| 순서 | 규칙 | 예 |
| --- | --- | --- |
| 1 | 적용 지역: 규제 지역이 수출 지역에 없으면 제외. 국내 규제는 국내 생산이라 항상 적용 | P003(미국·국내)의 EU 규제 → skipped "EU 미수출" |
| 2 | 적용 형태: SVHC 제33조·Entry 51은 성형품만. 혼합물 SVHC 0.1% 초과는 제31조 확인 | P004 BPA 0.3% → review |
| 3 | 함량으로 판정 불가: 방출량 기준, 세부 기준이 데이터에 없음 | P009 Entry 77 → review "방출 시험 필요" |
| 4 | 함량 비교 (합산 규칙은 그룹 합계) | P002 DEHP 0.08 + DBP 0.03 = 0.11 > 0.1 → exceeds |
| 5 | 함량 기준 없는 등재 → listed, 단 불순물 × 제한·신고 규칙 → review | P003 사염화탄소 불순물 → review |

결과: `exceeds` / `listed` / `review` / `below` + 적용 제외(`skipped`)와 이유. 모든 결과에 판정 이유 문장, 출처, 데이터 검증 상태가 붙는다.

한계: CLP 분류는 등재 여부만 본다 (혼합물 분류 농도 한계는 미반영).

## Tool / Resource / Prompt 나눈 기준
- **Tool**: 인자에 따라 결과가 달라지는 조회·계산 (판정, 관보 검색)
- **Resource**: URI로 식별되는 읽을거리 (`regulation://EU_REACH_SVHC` 규제 설명서)
- **Prompt**: 재사용하는 지시문 (`briefing_procedure` 브리핑 작성 절차)

## 실제로 겪은 문제
- **실제 규제 문서에 해당 물질의 CAS가 없다**: EPA TCE 규칙 제안 본문에 TCE의 CAS(79-01-6)는 없고 이름만 167회 나온다 → 이름·약어 매칭(`mentions.py`) 추가
- **"Lead"가 동사 "lead"로 오탐** → 일반 영단어와 겹치는 물질명은 엄격 패턴으로만 인정
- 자세한 내용: [troubleshooting.md](../../troubleshooting.md)

## 따라 하기

```bash
uv add "mcp>=1.10,<2" fastmcp
```

```bash
uv add --dev pytest-asyncio
```

`mcp`를 2 미만으로 고정하는 이유: Step 3에서 쓸 `langchain-mcp-adapters`가 `mcp` 2.x에서 import 오류가 난다 (1차 초안에서 겪은 문제).

## 확인

1) 전체 제품 판정 (코드만, LLM 없음)

```bash
uv run python -c "from app.repositories.reg_db import RegDB; from app.domain.judge import judge_portfolio; [print(j.product_id, j.product_name, j.summary()) for j in judge_portfolio(RegDB('data/regulations.db'))]"
```

```
P001 연질 PVC 전선 피복 컴파운드 {'exceeds': 4, 'listed': 3, 'review': 0, 'below': 1}
P002 저취 PVC 바닥재 {'exceeds': 2, 'listed': 2, 'review': 0, 'below': 3}
P003 금속 탈지 세정제 {'exceeds': 1, 'listed': 1, 'review': 2, 'below': 0}
...
P010 수성 아크릴 도료 {'exceeds': 0, 'listed': 0, 'review': 0, 'below': 0}
```

2) MCP 서버 3개를 실제 프로세스로 띄워 연결 (실시간 관보 호출 포함)

```bash
uv run python scripts/mcp_stdio_check.py
```

```
연결된 도구 11개:
  - product_find_products_by_cas
  ...
  - reg_feed_search_kr_admin_rules

  언급 물질: [('트리클로로에틸렌', 167), ('사염화탄소', 1), ('테트라클로로에틸렌', 1)]
  영향 후보 제품: ['P003']
  P003 금속 탈지 세정제: 미국 판정 [["테트라클로로에틸렌", "review"], ["사염화탄소", "review"], ["트리클로로에틸렌", "listed"]]
```

멀티 서버 설정에서는 도구 이름 앞에 서버 이름이 붙는다 (`reg_db_judge_product_compliance`). fastmcp가 "stdio 세션 하나를 모든 요청이 공유해 동시 요청에서 맥락이 섞일 수 있다"는 경고를 낸다 → Step 4에서 동시 요청 처리 시 확인한다.

3) (선택) MCP Inspector로 서버 하나를 화면에서 호출

처음 실행하면 npx가 패키지 설치 여부를 묻는다. `-y`로 질문 없이 진행한다. **다른 확인 명령과 한꺼번에 붙여 넣지 말고 이 명령만 실행**한다 (질문에 다음 명령이 입력돼 `npm error canceled`로 취소된 적이 있다).

```bash
npx -y @modelcontextprotocol/inspector uv run python mcp_servers/reg_db_server.py
```

터미널에 나온 `http://localhost:6274/...` 주소를 열어 Tools·Resources·Prompts 탭에서 `judge_product_compliance`(P002), `regulation://EU_REACH_SVHC`, `briefing_procedure`를 호출해 본다. 끝나면 `Ctrl+C`로 종료한 뒤 다음 확인으로 넘어간다.

4) 테스트

```bash
uv run pytest -q
```

```
35 passed
```

## 다음 단계
Step 3에서 LangChain LLM 계층과 LangGraph 멀티에이전트 그래프를 만들어, 이 MCP 도구들로 국내외 규제 브리핑을 작성한다.
