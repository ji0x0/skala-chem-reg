# 핸즈온 랩 — 국내외 화학물질 규제 브리핑·영향 분석 에이전트 만들기

한 단계씩 쌓아 올린다. 각 단계는 ① 만들 파일 목록 → ② 파일별 코드 설명 → ③ 실행 확인 → ④ 커밋 순서로 진행하고, **단계가 끝나면 항상 실행 가능한 상태**가 된다.

| 단계 | 문서 | 만드는 것 | 상태 |
| --- | --- | --- | --- |
| 0 | [step00-setup.md](step00-setup.md) | uv 프로젝트, 설정, 구조화 로그 | ✅ |
| 1 | [step01-data.md](step01-data.md) | 규제 목록·가상 제품·용어집·관보 스냅샷, CAS 검증, 규제 DB | ✅ |
| 2 | [step02-mcp.md](step02-mcp.md) | 판정 코어(지역·형태·함량·합산·불순물), 번역 검사, 이름→CAS 매칭, MCP 서버 3개 | ✅ |
| 3a | [step03a-llm.md](step03a-llm.md) | LangChain LLM 계층, 근거 원문 추출, MCP 도구 연결 (실모델 스모크) | ✅ |
| 3b | [step03b-graph.md](step03b-graph.md) | LangGraph 멀티에이전트 (chat·lookup·briefing, 병렬 수집·코드 판정·근거·검토·승인), Before 그래프 | ✅ |
| 4 | [step04-api.md](step04-api.md) | FastAPI REST + SSE, 제품 관리·규제 목록 API (제품은 앱 DB가 원본) | ✅ |
| 5a | [step05a-frontend-chat.md](step05a-frontend-chat.md) | Vue 화면: 질의응답·브리핑 스트리밍, 근거 원문 카드, 승인, 피드백, 새로고침 복원 | ✅ |
| 5b | [step05b-frontend-manage.md](step05b-frontend-manage.md) | Vue 화면: 제품 관리(추가·수정·검증·판정), 규제 목록(등재 물질·검색) | ✅ |
| 6 | [step06-eval.md](step06-eval.md) | 평가: 회귀 질문 11개·코드 채점기·LLM-as-Judge, Before/After 실측, LangSmith 트레이스·피드백·Dataset | ✅ |
| 7 | [step07-admin.md](step07-admin.md) | 관리자 페이지: 실행 기록·승인 이력·피드백·품질 평가·규제 데이터 상태 (토큰 잠금, 사용자 화면과 분리) | ✅ |
