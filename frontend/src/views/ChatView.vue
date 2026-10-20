<script setup>
// 질의응답·브리핑 화면 — 질문을 보내면 SSE로 진행 상황·토큰·근거·승인 요청을 받아 그린다
// 대화 ID는 브라우저에 저장해 새로고침해도 이어진다 (서버 체크포인터에 상태가 있음)
import { nextTick, onMounted, ref } from 'vue'
import { api } from '../api/client.js'
import { approvalStream, chatStream } from '../api/sse.js'
import { renderMarkdown } from '../lib/markdown.js'
import { describe } from '../lib/progress.js'
import ApprovalPanel from '../components/ApprovalPanel.vue'
import CitationList from '../components/CitationList.vue'
import ProgressLog from '../components/ProgressLog.vue'

const props = defineProps({ health: Object })

const THREAD_KEY = 'chem-reg.thread'
const EXAMPLES = [
  { label: '제품 조회', text: 'P002 규제 문제 있어?' },
  { label: '물질 조회', text: '트리클로로에틸렌이 들어간 제품과 해당 규제 알려줘' },
  { label: '변경 브리핑', text: '이번 주 미국 EPA 규제 변경 브리핑해줘' },
  { label: '물질 동향', text: 'TSCA 트리클로로에틸렌 최근 규제 동향 브리핑해줘' },
  { label: '서비스 안내', text: '이 서비스는 뭘 할 수 있어?' },
]
const OUTCOMES = [
  ['exceeds', '기준 초과 — 조치 필요'],
  ['listed', '등재 — 함량과 무관하게 해당'],
  ['review', '확인 필요 — 불순물·기준 미확정'],
  ['below', '기준 이하'],
]

const threadId = ref(load(THREAD_KEY))
const messages = ref([])
const input = ref('')
const busy = ref(false)
const scroller = ref(null)
let controller = null

function load(key) { try { return localStorage.getItem(key) } catch { return null } }
function save(key, value) { try { value ? localStorage.setItem(key, value) : localStorage.removeItem(key) } catch { /* 저장 불가 환경 */ } }

function newAssistant(extra = {}) {
  messages.value.push({
    role: 'assistant', status: 'running', progress: [], draft: '', attempt: 1, content: '',
    citations: [], usage: null, runId: null, approval: null, decision: null, error: '',
    feedback: null, highlight: null, started: performance.now(), elapsed: null, ...extra,
  })
  return messages.value.at(-1)            // 반응형 프록시를 받아야 화면이 갱신된다
}

// SSE 이벤트 하나 → 답변 메시지 상태 변경
function handler(msg) {
  return (event, data) => {
    switch (event) {
      case 'run_started':
        threadId.value = data.thread_id
        save(THREAD_KEY, data.thread_id)
        msg.runId = data.run_id
        break
      case 'token':
        if (data.attempt !== msg.attempt) { msg.draft = ''; msg.attempt = data.attempt }   // 재작성 → 새 초안
        msg.draft += data.delta
        scrollToBottom()
        break
      case 'final':
        msg.content = data.content
        msg.citations = data.citations ?? []
        msg.usage = data.usage ?? null
        break
      case 'approval_required':           // 승인 대기: final이 없으므로 승인할 브리핑·근거가 여기 같이 온다
        msg.approval = { impacted_products: data.impacted_products, message: data.message }
        if (data.draft) msg.content = data.draft
        msg.citations = data.citations ?? []
        break
      case 'error':
        msg.error = data.message
        break
      case 'done':
        msg.status = data.status
        msg.elapsed = (performance.now() - msg.started) / 1000
        break
      default: {
        const line = describe(event, data)
        if (line) {
          msg.progress.push({ ...line, at: (performance.now() - msg.started) / 1000 })
          scrollToBottom()
        }
      }
    }
  }
}

async function run(msg, start) {
  busy.value = true
  controller = new AbortController()
  try {
    await start({ onEvent: handler(msg), signal: controller.signal })
    if (msg.status === 'running') msg.status = 'failed'          // done 없이 끊김
  } catch (e) {
    msg.status = e.name === 'AbortError' ? 'stopped' : 'failed'
    if (e.name !== 'AbortError') msg.error = e.message
  } finally {
    busy.value = false
    controller = null
    scrollToBottom()
  }
}

async function send(text = input.value) {
  text = text.trim()
  if (!text || busy.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: text })
  const msg = newAssistant()
  scrollToBottom(true)
  await run(msg, opts => chatStream(text, threadId.value, opts))
}

async function decide(msg, decision) {
  msg.decision = decision
  msg.approval = null
  msg.status = 'running'
  scrollToBottom(true)
  msg.started = performance.now() - (msg.progress.at(-1)?.at ?? 0) * 1000
  await run(msg, opts => approvalStream(threadId.value, decision.approved, decision.comment, decision.approver, opts))
}

async function sendFeedback(msg, score) {
  try {
    await api.feedback(msg.runId, score)
    msg.feedback = score
  } catch (e) {
    msg.error = `피드백 저장 실패: ${e.message}`
  }
}

function stop() { controller?.abort() }

function newThread() {
  if (busy.value) return
  threadId.value = null
  save(THREAD_KEY, null)
  messages.value = []
}

// 본문의 [n]을 누르면 아래 근거 카드로 이동해 강조
function onBodyClick(e, msg, index) {
  const ref = e.target.closest('.cite-ref')
  if (!ref) return
  e.preventDefault()                                          // href="#" (키보드 접근용) 기본 이동 막기
  const n = Number(ref.dataset.cite)
  msg.highlight = n
  document.getElementById(`m${index}-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  setTimeout(() => { if (msg.highlight === n) msg.highlight = null }, 2500)
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {   // 한글 조합 중 Enter는 무시 (두 번 전송 방지)
    e.preventDefault()
    send()
  }
}

// 맨 아래에 붙어 있을 때만 따라 내려간다. 사용자가 위로 올려 읽는 중이면 따라가지 않는다
// (내용이 늘어나는 것만으로는 scroll 이벤트가 없으므로, 사용자가 스크롤할 때만 상태를 갱신)
let stick = true
function onScroll() {
  const el = scroller.value
  stick = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

async function scrollToBottom(force = false) {
  await nextTick()
  const el = scroller.value
  if (!el) return
  if (force) stick = true
  if (stick) el.scrollTop = el.scrollHeight
}

const STATUS_TEXT = { completed: '완료', awaiting_approval: '승인 대기', failed: '실패', stopped: '중단됨', running: '처리 중' }
const tokens = n => n?.toLocaleString('ko-KR')

// 새로고침 후 이전 대화 복원 — 서버 체크포인터에서 기록·승인 대기를 읽는다
onMounted(async () => {
  if (!threadId.value) return
  try {
    const state = await api.thread(threadId.value)
    if (!state.exists) return newThread()
    for (const m of state.history) {
      if (m.role === 'user') messages.value.push({ role: 'user', content: m.content })
      else newAssistant({ status: 'completed', content: m.content, started: 0 })
    }
    if (state.awaiting_approval) {
      newAssistant({ status: 'awaiting_approval', approval: state.pending_approval, citations: state.citations,
        content: state.draft, restored: true })
    } else if (messages.value.at(-1)?.role === 'assistant') {
      messages.value.at(-1).citations = state.citations
    }
    scrollToBottom(true)
  } catch {
    /* 백엔드가 꺼져 있으면 빈 대화로 시작 */
  }
})
</script>

<template>
  <div class="chat">
    <aside class="side">
      <section class="panel box">
        <div class="row">
          <h2>대화</h2>
          <span class="spacer"></span>
          <button class="small" :disabled="busy" @click="newThread">새 대화</button>
        </div>
        <p class="small muted mono">{{ threadId ?? '첫 질문을 보내면 시작됩니다' }}</p>
      </section>
      <section class="panel box">
        <h2>예시 질문</h2>
        <button v-for="ex in EXAMPLES" :key="ex.text" class="example" :disabled="busy" @click="send(ex.text)">
          <span class="small muted">{{ ex.label }}</span>
          {{ ex.text }}
        </button>
      </section>
      <section class="panel box small legend-box">
        <h2>판정 결과</h2>
        <div v-for="[o, text] in OUTCOMES" :key="o" class="legend">
          <span class="badge" :class="o">{{ o }}</span> {{ text }}
        </div>
        <p class="muted">판정은 코드가 규제 DB와 제품 배합을 대조해 내리고, LLM은 설명만 합니다.</p>
      </section>
    </aside>

    <section class="main">
      <div class="messages" ref="scroller" @scroll.passive="onScroll">
        <div v-if="!messages.length" class="empty muted">
          <p>제품·물질의 국내외 규제 해당 여부를 묻거나, 최근 규제 변경 브리핑을 요청해 보세요.</p>
          <p class="small">브리핑은 미국 연방 관보를 실시간으로 조회하고, 회사 제품 배합과 대조해 영향 제품을 찾습니다.</p>
        </div>

        <template v-for="(m, i) in messages" :key="i">
          <div v-if="m.role === 'user'" class="bubble user">{{ m.content }}</div>

          <article v-else class="bubble assistant panel">
            <ProgressLog :items="m.progress" :running="m.status === 'running'" :started="m.started" />

            <p v-if="m.restored" class="small muted">새로고침 전에 작성된 브리핑이 승인을 기다리고 있습니다.</p>
            <div v-if="m.content || m.draft" class="markdown" @click="onBodyClick($event, m, i)"
                 v-html="renderMarkdown(m.content || m.draft, m.citations.map(c => c.id))"></div>
            <p v-else-if="m.status === 'running'" class="muted small">생각하는 중…</p>
            <span v-if="m.status === 'running' && m.draft && !m.content" class="caret">▍</span>

            <div v-if="m.error" class="error-box small">{{ m.error }}</div>

            <CitationList :citations="m.citations" :highlight="m.highlight" :prefix="`m${i}`" />

            <!-- 승인자는 브리핑과 근거를 읽은 뒤 결정한다 -->
            <ApprovalPanel v-if="m.approval" :request="m.approval" :busy="busy" @decide="d => decide(m, d)" />
            <p v-if="m.decision" class="small muted">
              {{ m.decision.approver }}: {{ m.decision.approved ? '승인' : '반려' }}{{ m.decision.comment ? ` — ${m.decision.comment}` : '' }}
            </p>

            <footer class="row small muted meta" v-if="m.status !== 'running'">
              <span class="badge" :class="{ below: m.status === 'completed', listed: m.status === 'awaiting_approval', exceeds: m.status === 'failed' }">
                {{ STATUS_TEXT[m.status] }}
              </span>
              <span v-if="m.elapsed">{{ m.elapsed.toFixed(1) }}초</span>
              <span v-if="m.usage?.tokens">토큰 {{ tokens(m.usage.tokens) }}</span>
              <span v-if="m.usage?.usd && props.health?.llm_backend === 'openai'">${{ m.usage.usd.toFixed(4) }}</span>
              <span class="spacer"></span>
              <template v-if="m.status === 'completed' && m.runId">
                <span v-if="m.feedback !== null">피드백 감사합니다 {{ m.feedback ? '👍' : '👎' }}</span>
                <template v-else>
                  <button class="ghost" title="도움이 됐어요" @click="sendFeedback(m, 1)">👍</button>
                  <button class="ghost" title="도움이 안 됐어요" @click="sendFeedback(m, 0)">👎</button>
                </template>
              </template>
            </footer>
          </article>
        </template>
      </div>

      <form class="composer panel" @submit.prevent="send()">
        <textarea v-model="input" rows="2" maxlength="2000" :disabled="busy"
                  placeholder="예: P001을 EU로 수출하는데 문제 있어? (Enter 전송 · Shift+Enter 줄바꿈)"
                  @keydown="onKeydown"></textarea>
        <button v-if="busy" type="button" @click="stop">중지</button>
        <button v-else class="primary" type="submit" :disabled="!input.trim()">보내기</button>
      </form>
    </section>
  </div>
</template>

<style scoped>
.chat { display: grid; grid-template-columns: 280px 1fr; gap: 16px; height: 100%; padding: 16px 20px; }
.side { display: flex; flex-direction: column; gap: 12px; overflow-y: auto; }
.box { padding: 12px 14px; }
h2 { font-size: 13px; margin: 0 0 8px; }
.box .row h2 { margin: 0; }
.example {
  display: flex; flex-direction: column; align-items: flex-start;
  width: 100%; text-align: left; margin-bottom: 6px; line-height: 1.4;
}
.legend { margin-bottom: 4px; }
.main { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.messages { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding-bottom: 12px; }
.empty { margin: auto; text-align: center; max-width: 460px; }
.bubble { max-width: 860px; }
.user {
  align-self: flex-end; background: var(--accent); color: #fff;
  padding: 8px 14px; border-radius: 14px 14px 4px 14px; white-space: pre-wrap;
}
.assistant { align-self: stretch; padding: 14px 16px; }
.caret { color: var(--accent); animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.meta { margin-top: 10px; flex-wrap: wrap; }
.meta button { padding: 2px 6px; }
.composer { display: flex; gap: 8px; padding: 8px; align-items: flex-end; }
.composer textarea { border: none; resize: none; outline: none; }
.composer button { white-space: nowrap; flex: none; }
.composer textarea:focus { outline: none; }
@media (max-width: 760px) {
  .chat { grid-template-columns: 1fr; grid-template-rows: auto 1fr; padding: 12px; }
  .side { flex-direction: row; overflow-x: auto; max-height: 130px; }
  .side .box { min-width: 220px; overflow-y: auto; }
  .legend-box { display: none; }
}
</style>
