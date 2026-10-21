# 핸즈온 랩 — 국내외 화학물질 규제 브리핑·영향 분석 에이전트 만들기

한 단계씩 쌓아 올린다. 각 단계는 ① 만들 파일 목록 → ② 파일별 코드 설명 → ③ 실행 확인 → ④ 커밋 순서로 진행하고, **단계가 끝나면 항상 실행 가능한 상태**가 된다.

각 문서는 그 단계를 마친 시점의 기록이다. 뒤 단계에서 바뀐 부분은 문서 맨 위 **이후 변경**에 적었다.

| 단계 | 문서 | 만드는 것 | 상태 |
| --- | --- | --- | --- |
| 0 | [step00-setup.md](step00-setup.md) | uv 프로젝트, 설정, 구조화 로그 | ✅ |
| 1 | [step01-data.md](step01-data.md) | 규제 목록·가상 제품·용어집·관보 스냅샷, CAS 검증, 규제 DB | ✅ |
| 2 | [step02-mcp.md](step02-mcp.md) | 판정 코어(지역·형태·함량·합산·불순물), 번역 검사, 이름→CAS 매칭, MCP 서버 3개 | ✅ |
| 3a | [step03a-llm.md](step03a-llm.md) | LangChain LLM 계층, 근거 원문 추출, MCP 도구 연결 (실모델 스모크) | ✅ |
| 3b | [step03b-graph.md](step03b-graph.md) | LangGraph 멀티에이전트 (chat·lookup·briefing, 병렬 수집·코드 판정·근거·검토), Before 그래프 | ✅ |
| 4 | [step04-api.md](step04-api.md) | FastAPI REST + SSE, 제품 관리·규제 목록 API (제품은 앱 DB가 원본) | ✅ |
| 5a | [step05a-frontend-chat.md](step05a-frontend-chat.md) | Vue 화면: 질의응답·브리핑 스트리밍, 근거 원문 카드, 피드백, 새로고침 복원 | ✅ |
| 5b | [step05b-frontend-manage.md](step05b-frontend-manage.md) | Vue 화면: 제품 관리(추가·수정·검증·판정), 규제 목록(등재 물질·검색) | ✅ |
| 6 | [step06-eval.md](step06-eval.md) | 평가: 회귀 질문 11개·코드 채점기·LLM-as-Judge, Before/After 실측, LangSmith 트레이스·피드백·Dataset | ✅ |
| 7 | [step07-admin.md](step07-admin.md) | 관리자 페이지: 실행 기록·피드백·품질 평가·규제 데이터 상태 (토큰 잠금, 사용자 화면과 분리) | ✅ |
| 8 | [step08-kr-feed.md](step08-kr-feed.md) | 국내 변경 수집: 법제처 행정규칙 ReAct 에이전트 + 안전장치, 개정 내용으로 영향 판단, 1년 재검색 | ✅ |
| 9 | [step09-routing.md](step09-routing.md) | 질문 이해·범위 판정: 의도 분해, 범위 밖·확인 불가 안내, 규제 설명·목록 조회, 후속 질문, 대화 승인 제거 | ✅ |
| 10 | [step10-weekly.md](step10-weekly.md) | 정기 브리핑: 기간 고정 수집, 주차별 저장, 매주 월요일 스케줄러, 정기 브리핑 탭·검토 완료, 지난 3주 예시 | ✅ |
| 11 | [step11-eu-feed.md](step11-eu-feed.md) | EU 수집: REACH·CLP 개정 법령(Cellar SPARQL·본문), 채택일·관보 게재일, SVHC 한계 안내 | ✅ |
| 12 | [step12-db-update.md](step12-db-update.md) | 규제 DB 갱신 제안: 공식 통합본 새 버전 감지 → 바뀐 행·제품 판정 변화 → 담당자 승인(`interrupt`) 후 반영 | ✅ |
