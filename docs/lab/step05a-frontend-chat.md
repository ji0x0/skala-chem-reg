# Step 5a — Vue 화면: 질의응답·브리핑

## 목표
Step 4 API에 붙는 Vue 화면을 만든다. 질문을 보내면 진행 단계·토큰이 실시간으로 흐르고, 답변의 `[n]`을 누르면 근거 원문으로 이동하며, 영향 제품은 근거를 본 뒤 승인·반려한다.
(5b에서 제품 관리·규제 목록 화면을 추가한다.)

```
브라우저(:5173, Vite + Vue 3) ──fetch(REST)──────────▶ FastAPI(:8000)
                               ──fetch + ReadableStream(SSE, POST)──▶ /chat/stream, /threads/{id}/approval
                                        ↑ CORS 허용 출처 (Step 4)
```

## 기술 선택
- **Vite + Vue 3 SFC**: 레퍼런스(`all_total_vue`)는 CDN Vue 한 장이지만, 화면이 3개라 컴포넌트로 나누고 빌드 도구를 쓴다. 라우터 없이 탭 상태로 전환
- **프록시 없이 CORS**: 레퍼런스는 같은 출처 프록시 서버로 CORS를 피했지만, 우리는 백엔드가 허용 출처를 명시(Step 4)
- **SSE는 `fetch` + `ReadableStream`**: `EventSource`는 GET만 되는데 질문은 POST 본문으로 보낸다 (R50)
- **Markdown은 `marked` + `DOMPurify`**: LLM 글을 `v-html`로 넣으므로 반드시 정화 (XSS 방지)

## 만드는 파일

| 파일 | 역할 |
| --- | --- |
| `frontend/package.json`, `vite.config.js`, `.env.example` | 의존성, 포트 5173 고정(`strictPort`), API 주소 |
| `frontend/index.html`, `src/main.js` | 진입점 |
| `src/api/client.js` | REST 공통: 서버 오류 3가지 모양(문자열 / {message, errors} / Pydantic 목록) → `ApiError` 하나로 |
| `src/api/sse.js` (+ `sse.test.js`) | SSE 파서: 빈 줄까지 버퍼링, CRLF·주석·여러 줄 data, 청크 경계에서 잘린 한글 바이트 |
| `src/lib/progress.js` | 진행 이벤트 → 한 줄 문구·색 |
| `src/lib/markdown.js` (+ `lib.test.js`) | Markdown → 안전한 HTML, 실제 있는 `[n]`만 근거 링크, 코드 블록 감싸기 제거 |
| `src/App.vue` | 상단 바(백엔드 상태), 탭 |
| `src/views/ChatView.vue` | 대화·스트리밍·승인·피드백·새로고침 복원 |
| `src/components/ProgressLog.vue` | 단계(노드)별로 묶은 진행 과정, 경과 시간 |
| `src/components/CitationList.vue` | 근거 카드: 번역 → 원문 펼치기, 판정·이유, 출처 링크, 기준일, 검증 상태 (R56) |
| `src/components/ApprovalPanel.vue` | 영향 제품 표, 승인자·의견, 승인/반려 |
| `src/style.css` | 색 변수(라이트/다크), 판정 결과 배지 색 통일 |
| `scripts/run_frontend.sh`, `.claude/launch.json` | 실행 (백엔드 응답 확인, 5173 정리) |
| (백엔드) `app/streaming/events.py`, `app/service.py` | 승인 대기 이벤트에 초안·근거 추가 (아래 "실제로 겪은 문제") |

## 화면 동작 포인트
- **재작성 반영**: 품질 검토 불합격으로 다시 쓰면 `token.attempt`가 2가 되고 화면은 초안을 비우고 새로 그린다
- **승인 흐름**: 같은 답변 카드에서 `/approval` 스트림을 이어 받는다. 승인 패널은 근거 **아래** — 읽고 나서 결정
- **새로고침 복원**: 대화 ID를 `localStorage`에 두고 `GET /threads/{id}`로 기록·승인 대기·근거를 다시 읽는다 (서버 SQLite 체크포인터)
- **한글 입력**: 조합 중 Enter(`isComposing`)는 무시 → 두 번 전송 방지
- **자동 스크롤**: 사용자가 위로 올려 읽는 중이면 따라가지 않는다
- **비용 표시**: OpenAI일 때만. Ollama는 토큰 수만 (실제 과금 없음)

## 따라 하기

```bash
cd frontend && npm install
```

## 확인

1) 단위 테스트

```bash
cd frontend && npm test
```

```
Test Files  2 passed (2)
     Tests  9 passed (9)
```

```bash
uv run pytest -q
```

```
64 passed
```

2) 실행 — 터미널 2개 (`.env`의 `LLM_BACKEND=ollama`)

```bash
bash scripts/run_backend.sh
```

```bash
bash scripts/run_frontend.sh
```

브라우저에서 http://127.0.0.1:5173 → 오른쪽 위 초록 점 `v2 · ollama:qwen3:8b · 도구 11`

3) 질의응답: 예시 질문 **"P002 규제 문제 있어?"**
- 진행 과정: 질문 분류 → 규제 조회·판정(`judge_product_compliance` 완료 — exceeds 2 · listed 2 …) → 최종 정리
- 답변의 `[1]`을 누르면 아래 근거 카드로 이동해 파랗게 강조
- 근거 카드: `exceeds` · 판정 이유(Entry 51 합계 0.11 wt% > 0.1 wt%) · 등재 내용 · 출처 · `원본 확인 전`

4) 브리핑 → 승인: 예시 질문 **"이번 주 미국 EPA 규제 변경 브리핑해줘"** (약 100초)
- 진행 과정 10단계(질문 분류 → 브리핑 계획 → 계획 검증 → 수집 결과 확인 → 문서 요약·근거 번역 → 제품 영향 판정 → 브리핑 작성 → 사실·근거 검사 → 품질 검토 → 담당자 승인)
- 초안 5개 절 + 근거 9개(관보 원문 문장·번역 + 규제 DB 등재) + 승인 패널(P003, 2026-20964, listed·review)
- 이 상태에서 **새로고침** → 같은 초안·근거·승인 패널이 복원됨
- 의견 입력 후 **승인** → "## 승인 결과" 절이 붙은 최종본, `완료` · 토큰 · 👍/👎
- 👍 → `data/feedback.jsonl`에 기록 (LangSmith 연동은 Step 6)

관찰 결과 (2026-10-20, Ollama qwen3:8b): lookup 약 21초, 브리핑 96~110초, 최종본 6개 절, 화면 코드 블록 0개, 가로 넘침 없음, 모바일 폭(375px)에서도 승인 가능.

## 실제로 겪은 문제
- **승인 대기 화면이 코드 블록 한 덩어리 + 근거 없음** → 토큰 스트림은 모델 원문(```markdown 감싸기 포함)이고 승인 대기에서는 `final` 이벤트가 없음. 서버가 `approval_required`에 가드 통과 초안·근거를 함께 보내고, 화면도 스트리밍 중 감싸기를 벗김
- **긴 브리핑에서 자동 스크롤이 멈춤** → "맨 아래 고정" 상태를 사용자 스크롤 때만 갱신
- **미리보기 백엔드 포트 자동 변경** → `autoPort: false` (CORS 허용 출처와 포트가 어긋나지 않게)
- 자세한 내용: [troubleshooting.md](../../troubleshooting.md)

## 다음 단계
Step 5b: 제품 관리(추가·수정, 검증 오류 행 표시, 저장 직후 판정)와 규제 목록(규제별 등재 물질, 물질 검색) 화면.
