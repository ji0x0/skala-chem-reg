<script setup>
// 정기 브리핑 (Step 10) — 지난주(월~일) 국내외 규제 변경을 주차별로 모아 보고, 담당자가 "검토 완료"로 표시한다
// 생성은 서버의 스케줄러(매주 월요일)·스크립트가 한다. 화면은 읽기와 검토만
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client.js'
import { renderMarkdown } from '../lib/markdown.js'
import CitationList from '../components/CitationList.vue'

const weeks = ref([])
const selected = ref(null)
const loading = ref(false)
const error = ref('')
const reviewer = ref('규제 담당자')
const comment = ref('')
const saving = ref(false)
const highlight = ref(null)

const STATUS = { pending_review: ['검토 대기', 'review'], reviewed: ['검토 완료', 'below'], failed: ['생성 실패', 'exceeds'] }
const status = s => STATUS[s] ?? [s, '']
const md = (s) => s.slice(5).replace('-', '.')                       // 2026-10-12 → 10.12

async function load() {
  loading.value = true
  error.value = ''
  try {
    weeks.value = await api.weekly()
    if (weeks.value.length && !selected.value) await open(weeks.value[0].week_id)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function open(weekId) {
  try {
    selected.value = await api.weeklyOne(weekId)
    comment.value = ''
  } catch (e) {
    error.value = e.message
  }
}

async function markReviewed() {
  saving.value = true
  try {
    selected.value = await api.reviewWeekly(selected.value.week_id, reviewer.value.trim() || '규제 담당자', comment.value.trim())
    const row = weeks.value.find(w => w.week_id === selected.value.week_id)
    if (row) Object.assign(row, { status: selected.value.status, reviewer: selected.value.reviewer })
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

const citationIds = computed(() => (selected.value?.citations ?? []).map(c => c.id))

function onBodyClick(e) {
  const ref = e.target.closest('.cite-ref')
  if (!ref) return
  e.preventDefault()
  const n = Number(ref.dataset.cite)
  highlight.value = n
  document.getElementById(`w-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  setTimeout(() => { if (highlight.value === n) highlight.value = null }, 2500)
}

const localTime = ts => (ts ? new Date(ts).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' }) : '')

onMounted(load)
</script>

<template>
  <div class="weekly">
    <aside class="panel list">
      <div class="row">
        <h2>정기 브리핑</h2>
        <span class="spacer"></span>
        <button class="ghost small" :disabled="loading" @click="load">새로고침</button>
      </div>
      <p class="muted small">매주 월요일 지난주(월~일) 미국 관보·국내 고시·EU 개정 법령을 정리합니다.</p>
      <div v-if="error" class="error-box small" role="alert">{{ error }}</div>
      <p v-if="!loading && !weeks.length" class="muted small">아직 정기 브리핑이 없습니다.</p>
      <button v-for="w in weeks" :key="w.week_id" class="week" :class="{ on: selected?.week_id === w.week_id }"
              @click="open(w.week_id)">
        <div class="row">
          <strong>{{ w.week_id }}</strong>
          <span class="muted small">{{ md(w.period_start) }}~{{ md(w.period_end) }}</span>
          <span class="spacer"></span>
          <span class="badge" :class="status(w.status)[1]">{{ status(w.status)[0] }}</span>
        </div>
        <div class="small muted">
          관련 변경 {{ w.documents }}건 · 영향 제품 {{ w.impacted ? w.impacted.replaceAll(',', ', ') : '없음' }}
        </div>
      </button>
    </aside>

    <section class="panel detail" v-if="selected">
      <header class="row wrap">
        <div>
          <h2>{{ selected.week_id }} 정기 브리핑</h2>
          <p class="muted small">
            기간 {{ selected.period_start }} ~ {{ selected.period_end }} · 생성 {{ localTime(selected.generated_at) }}
            <template v-if="selected.latency_ms"> · {{ (selected.latency_ms / 1000).toFixed(0) }}초</template>
          </p>
        </div>
        <span class="spacer"></span>
        <span class="badge" :class="status(selected.status)[1]">{{ status(selected.status)[0] }}</span>
      </header>

      <div class="markdown body" @click="onBodyClick"
           v-html="renderMarkdown(selected.content, citationIds)"></div>
      <CitationList :citations="selected.citations" :highlight="highlight" prefix="w" />

      <!-- 검토 완료: 승인이 아니라 "담당자가 읽고 확인했다"는 기록 -->
      <footer class="review">
        <p v-if="selected.status === 'reviewed'" class="small">
          ✓ {{ selected.reviewer }} 검토 완료 · {{ localTime(selected.reviewed_at) }}
          <template v-if="selected.comment"> — {{ selected.comment }}</template>
        </p>
        <form v-else-if="selected.status === 'pending_review'" class="row wrap" @submit.prevent="markReviewed">
          <label class="sr-only" for="reviewer">검토자</label>
          <input id="reviewer" v-model="reviewer" class="narrow" maxlength="50" placeholder="검토자">
          <label class="sr-only" for="review-comment">의견</label>
          <input id="review-comment" v-model="comment" maxlength="500" placeholder="의견 (예: P003 고객사 공지 준비)">
          <button class="primary" type="submit" :disabled="saving">{{ saving ? '저장 중…' : '검토 완료' }}</button>
        </form>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.weekly { display: grid; grid-template-columns: 320px 1fr; gap: 16px; height: 100%; padding: 16px 20px; box-sizing: border-box; }
.list { display: flex; flex-direction: column; min-height: 0; padding: 12px; gap: 8px; overflow-y: auto; }
.list h2, .detail h2 { font-size: 15px; margin: 0; }
.week { text-align: left; display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; }
.week.on { border-color: var(--accent); background: var(--accent-soft); }
.detail { padding: 16px 20px; overflow-y: auto; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
.body { border-top: 1px solid var(--border); padding-top: 12px; }
.review { border-top: 1px solid var(--border); padding-top: 12px; }
.review input { flex: 1; min-width: 180px; }
.review input.narrow { flex: 0 0 140px; min-width: 120px; }
.wrap { flex-wrap: wrap; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (max-width: 860px) {
  .weekly { grid-template-columns: 1fr; grid-template-rows: 240px 1fr; padding: 12px; }
}
</style>
