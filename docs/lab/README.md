# 핸즈온 랩 — 국내외 화학물질 규제 브리핑·영향 분석 에이전트 만들기

한 단계씩 쌓아 올린다. 각 단계는 ① 만들 파일 목록 → ② 파일별 코드 설명 → ③ 실행 확인 → ④ 커밋 순서로 진행하고, **단계가 끝나면 항상 실행 가능한 상태**가 된다.

| 단계 | 문서 | 만드는 것 | 상태 |
| --- | --- | --- | --- |
| 0 | [step00-setup.md](step00-setup.md) | uv 프로젝트, 설정, 구조화 로그 | ✅ |
| 1 | [step01-data.md](step01-data.md) | 규제 목록·가상 제품·용어집·관보 스냅샷, CAS 검증, 규제 DB | ✅ |
| 2 | [step02-mcp.md](step02-mcp.md) | 판정 코어(지역·형태·함량·합산·불순물), 번역 검사, 이름→CAS 매칭, MCP 서버 3개 | ✅ |
| 3 | step03-agents.md | LangChain LLM 계층, LangGraph 멀티에이전트 | |
| 4 | step04-api.md | FastAPI REST + SSE | |
| 5 | step05-frontend.md | Vue 화면 | |
| 6 | step06-eval-test.md | 평가, LangSmith | |
