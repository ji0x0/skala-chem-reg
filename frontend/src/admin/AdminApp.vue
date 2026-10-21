<script setup>
// 관리자 페이지 (규제대응 팀장) — 사용자 화면과 분리된 페이지(/admin/), 관리자 토큰이 있어야 열린다
// 앱이 가진 기록(실행·승인·피드백·평가·규제 데이터)을 모아 보여 주고, 상세 추적은 LangSmith로 넘긴다
import { computed, onMounted, ref } from 'vue'
import { adminApi, loadToken, localTime, ROUTE_KO, RUN_STATUS_KO, saveToken } from './api.js'

const tabs = [
  { id: 'overview', label: '운영 요약' },
  { id: 'approvals', label: '승인 이력' },
  { id: 'feedback', label: '피드백' },
  { id: 'evaluations', label: '품질 평가' },
  { id: 'runs', label: '실행 기록' },
]
const active = ref('overview')
const tokenInput = ref('')
const unlocked = ref(false)
const loading = ref(false)
const error = ref('')

const overview = ref(null)
const approvals = ref({ pending: [], history: [] })
const feedback = ref([])
const evaluations = ref([])
const evalIndex = ref(0)
const runs = ref([])
const runKind = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [o, a, f, e, r] = await Promise.all([adminApi.overview(), adminApi.approvals(), adminApi.feedback(),
      adminApi.evaluations(), adminApi.runs(runKind.value)])
    overview.value = o; approvals.value = a; feedback.value = f; evaluations.value = e; runs.value = r
    unlocked.value = true
  } catch (e) {
    if (e.status === 401 || e.status === 503) { unlocked.value = false; saveToken('') }
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function unlock() {
  saveToken(tokenInput.value.trim())
  tokenInput.value = ''
  await load()
}

function lock() {
  saveToken('')
  unlocked.value = false
  overview.value = null
}

async function reloadRuns() {
  try { runs.value = await adminApi.runs(runKind.value) } catch (e) { error.value = e.message }
}

onMounted(() => { if (loadToken()) load() })

const pct = v => (v === null || v === undefined || v === '' ? '—' : `${Math.round(v * 100)}%`)
const num = v => (v ?? 0).toLocaleString('ko-KR')
const secs = ms => (ms === null || ms === undefined ? '—' : `${(ms / 1000).toFixed(1)}초`)

const tiles = computed(() => {
  const o = overview.value
  if (!o) return []
  const t = o.runs.totals
  return [
    { label: '처리한 요청', value: num(t.runs), sub: `대화 ${num(t.threads)}개 · 실패 ${num(t.failed)}` },
    { label: '승인 대기', value: num(o.pending_approvals), sub: `승인 ${num(t.approved)} · 반려 ${num(t.rejected)}`,
      warn: o.pending_approvals > 0 },
    { label: '브리핑 품질 검토 통과율', value: pct(t.quality_pass_rate), sub: '가드 + LLM-as-Judge' },
    { label: '담당자 피드백', value: `👍 ${o.feedback.up} · 👎 ${o.feedback.down}`, sub: `전체 ${o.feedback.total}건` },
    { label: '토큰 사용량', value: num(t.tokens), sub: `가정 단가 기준 $${t.usd}` },
    { label: '규제 데이터', value: `${o.regulations.count}종 · ${num(o.regulations.listings)}행`,
      sub: `공식 확인 ${o.regulations.unverified ? `(확인 전 ${o.regulations.unverified}행)` : '전부'} · ${o.regulations.verified_on ?? ''}` },
  ]
})

// 품질 평가: 같은 질문 세트에서 Before(LLM 단독) vs After(v2) — scripts/run_eval.py 결과
const METRICS = [
  ['product_precision', '영향 제품 정밀도', 'up', 'ratio'],
  ['product_recall', '영향 제품 재현율', 'up', 'ratio'],
  ['false_positive_products', '무관한 제품 지목 수', 'down', 'int'],
  ['invented_dates', '지어낸 날짜', 'down', 'int'],
  ['invented_cas', '지어낸 CAS', 'down', 'int'],
  ['cite_ok_rate', '근거 요건 충족률', 'up', 'ratio'],
  ['judge_faithfulness', 'Judge 근거 충실성 (1~5)', 'up', 'dec'],
  ['judge_completeness', 'Judge 완전성 (1~5)', 'up', 'dec'],
  ['latency_s', '평균 시간 (초)', 'down', 'dec'],
  ['tokens', '평균 토큰', 'down', 'int'],
]
const evaluation = computed(() => evaluations.value[evalIndex.value] ?? null)
const fmt = (v, kind) => (v === null || v === undefined ? '—'
  : kind === 'ratio' ? v.toFixed(2) : kind === 'dec' ? v.toFixed(1) : num(Math.round(v)))
function better(key, dir) {
  const b = evaluation.value?.summary?.briefing
  if (!b?.baseline || !b?.v2) return false
  return dir === 'up' ? b.v2[key] > b.baseline[key] : b.v2[key] < b.baseline[key]
}
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <h1>규제 브리핑 관리자</h1>
        <span class="muted small">처리량·승인·피드백·품질 — 상세 추적은 LangSmith</span>
      </div>
      <nav v-if="unlocked" class="tabs">
        <button v-for="t in tabs" :key="t.id" :class="{ on: active === t.id }" @click="active = t.id">
          {{ t.label }}
          <span v-if="t.id === 'approvals' && overview?.pending_approvals" class="count">{{ overview.pending_approvals }}</span>
        </button>
      </nav>
      <div v-if="unlocked" class="row">
        <button :disabled="loading" @click="load">{{ loading ? '불러오는 중…' : '새로고침' }}</button>
        <button class="ghost" @click="lock">잠금</button>
      </div>
    </header>

    <main class="content">
      <!-- 잠금 화면 -->
      <form v-if="!unlocked" class="panel login" @submit.prevent="unlock">
        <h2>관리자 토큰</h2>
        <p class="muted small">서버 .env의 ADMIN_TOKEN 값을 입력하세요. 이 탭을 닫으면 지워집니다.</p>
        <label class="sr-only" for="admin-token">관리자 토큰</label>
        <input id="admin-token" v-model="tokenInput" type="password" autocomplete="current-password" required>
        <button class="primary" type="submit" :disabled="loading || !tokenInput.trim()">열기</button>
        <div v-if="error" class="error-box" role="alert">{{ error }}</div>
      </form>

      <template v-else>
        <div v-if="error" class="error-box" role="alert">{{ error }}</div>

        <!-- 운영 요약 -->
        <section v-if="active === 'overview' && overview" class="stack">
          <div class="tiles">
            <div v-for="t in tiles" :key="t.label" class="panel tile" :class="{ warn: t.warn }">
              <div class="muted small">{{ t.label }}</div>
              <div class="value">{{ t.value }}</div>
              <div class="muted small">{{ t.sub }}</div>
            </div>
          </div>
          <div class="grid2">
            <div class="panel pad">
              <h3>경로별 처리량</h3>
              <table>
                <thead><tr><th>경로</th><th class="num">요청</th><th class="num">실패</th><th class="num">평균 시간</th></tr></thead>
                <tbody>
                  <tr v-for="r in overview.runs.by_route" :key="r.route">
                    <td>{{ ROUTE_KO[r.route] ?? r.route }}</td><td class="num">{{ r.runs }}</td>
                    <td class="num">{{ r.failed }}</td><td class="num">{{ secs(r.avg_latency_ms) }}</td>
                  </tr>
                  <tr v-if="!overview.runs.by_route.length"><td colspan="4" class="muted">아직 기록이 없습니다</td></tr>
                </tbody>
              </table>
            </div>
            <div class="panel pad">
              <h3>날짜별 (최근 14일, UTC)</h3>
              <table>
                <thead><tr><th>날짜</th><th class="num">요청</th><th class="num">토큰</th></tr></thead>
                <tbody>
                  <tr v-for="d in overview.runs.daily" :key="d.day">
                    <td class="mono">{{ d.day }}</td><td class="num">{{ d.runs }}</td><td class="num">{{ num(d.tokens) }}</td>
                  </tr>
                  <tr v-if="!overview.runs.daily.length"><td colspan="3" class="muted">아직 기록이 없습니다</td></tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="panel pad row wrap">
            <div>
              <h3>LangSmith</h3>
              <p class="muted small">
                노드·MCP 도구 호출 트레이스, 👍/👎 피드백(user_score), Before/After Dataset 실험 ·
                프로젝트 <span class="mono">{{ overview.langsmith.project }}</span> ·
                {{ overview.langsmith.enabled ? '전송 중' : '꺼짐 (LANGSMITH_TRACING·API 키 필요)' }}
              </p>
            </div>
            <span class="spacer"></span>
            <a class="button" :href="overview.langsmith.url" target="_blank" rel="noopener">LangSmith 열기</a>
          </div>
          <p class="muted small">
            파이프라인 {{ overview.pipeline }} · LLM {{ overview.llm_backend }} · 제품 {{ overview.products }}개 ·
            비용은 가정 단가(설정값)로 계산한 비교용 수치이며 실제 요금이 아닙니다
          </p>
        </section>

        <!-- 승인 이력 -->
        <section v-else-if="active === 'approvals'" class="stack">
          <div class="panel pad">
            <h3>승인 대기 ({{ approvals.pending.length }})</h3>
            <table>
              <thead><tr><th>요청 시각</th><th>대화</th><th>질문</th><th>영향 제품</th></tr></thead>
              <tbody>
                <tr v-for="p in approvals.pending" :key="p.run_id">
                  <td class="nowrap">{{ localTime(p.created_at) }}</td><td>{{ p.title }}</td>
                  <td>{{ p.question }}</td><td class="mono">{{ p.impacted }}</td>
                </tr>
                <tr v-if="!approvals.pending.length"><td colspan="4" class="muted">대기 중인 승인이 없습니다</td></tr>
              </tbody>
            </table>
          </div>
          <div class="panel pad">
            <h3>승인·반려 이력</h3>
            <table>
              <thead><tr><th>결정 시각</th><th>결정</th><th>담당자</th><th>코멘트</th><th>대화</th><th>영향 제품</th></tr></thead>
              <tbody>
                <tr v-for="h in approvals.history" :key="h.run_id">
                  <td class="nowrap">{{ localTime(h.created_at) }}</td>
                  <td><span class="badge" :class="h.approved ? 'below' : 'exceeds'">{{ h.approved ? '승인' : '반려' }}</span></td>
                  <td>{{ h.approver }}</td><td>{{ h.comment ?? '' }}</td><td>{{ h.title }}</td>
                  <td class="mono">{{ h.impacted }}</td>
                </tr>
                <tr v-if="!approvals.history.length"><td colspan="6" class="muted">아직 결정한 승인이 없습니다</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- 피드백 -->
        <section v-else-if="active === 'feedback'" class="panel pad">
          <h3>담당자 피드백 ({{ feedback.length }})</h3>
          <table>
            <thead><tr><th>시각</th><th>평가</th><th>코멘트</th><th>경로</th><th>질문</th></tr></thead>
            <tbody>
              <tr v-for="f in feedback" :key="f.run_id + f.ts">
                <td class="nowrap">{{ localTime(f.ts) }}</td>
                <td>{{ f.score > 0 ? '👍' : '👎' }}</td><td>{{ f.comment }}</td>
                <td class="nowrap">{{ ROUTE_KO[f.route] ?? '—' }}</td><td>{{ f.question ?? '(기록 이전 실행)' }}</td>
              </tr>
              <tr v-if="!feedback.length"><td colspan="5" class="muted">아직 피드백이 없습니다</td></tr>
            </tbody>
          </table>
        </section>

        <!-- 품질 평가 -->
        <section v-else-if="active === 'evaluations'" class="panel pad">
          <div class="row wrap">
            <h3>Before(LLM 단독) vs After(v2) — 브리핑 질문</h3>
            <span class="spacer"></span>
            <label class="sr-only" for="eval-select">평가 실행</label>
            <select v-if="evaluations.length" id="eval-select" v-model.number="evalIndex" class="narrow">
              <option v-for="(e, i) in evaluations" :key="e.name" :value="i">{{ e.name }}</option>
            </select>
          </div>
          <p v-if="!evaluation" class="muted">평가 결과가 없습니다. <span class="mono">uv run python scripts/run_eval.py</span>로 만드세요.</p>
          <template v-else>
            <p class="muted small">
              LLM {{ evaluation.meta.llm }} · {{ evaluation.meta.started }} · 질문 {{ evaluation.meta.questions?.length }}개 ·
              LLM-as-Judge {{ evaluation.meta.judge }}
            </p>
            <table v-if="evaluation.summary.briefing">
              <thead><tr><th>지표</th><th class="num">Before</th><th class="num">After</th></tr></thead>
              <tbody>
                <tr v-for="[key, label, dir, kind] in METRICS" :key="key">
                  <td>{{ label }} <span class="muted small">{{ dir === 'up' ? '↑' : '↓' }}</span></td>
                  <td class="num">{{ fmt(evaluation.summary.briefing.baseline?.[key], kind) }}</td>
                  <td class="num" :class="{ good: better(key, dir) }">{{ fmt(evaluation.summary.briefing.v2?.[key], kind) }}</td>
                </tr>
              </tbody>
            </table>
            <p v-if="evaluation.summary.v2_all" class="muted small">
              v2 전체 회귀 {{ evaluation.summary.v2_all.n }}문항 · 라우팅 정확도 {{ fmt(evaluation.summary.v2_all.route_acc, 'ratio') }} ·
              근거 요건 {{ fmt(evaluation.summary.v2_all.cite_ok_rate, 'ratio') }} · 오류 {{ evaluation.summary.v2_all.errors }}
            </p>
          </template>
        </section>

        <!-- 실행 기록 -->
        <section v-else-if="active === 'runs'" class="panel pad">
          <div class="row wrap">
            <h3>최근 실행 ({{ runs.length }})</h3>
            <span class="spacer"></span>
            <label class="sr-only" for="run-kind">종류</label>
            <select id="run-kind" v-model="runKind" class="narrow" @change="reloadRuns">
              <option value="">전체</option><option value="question">질문</option><option value="approval">승인·반려</option>
            </select>
          </div>
          <div class="scroll">
            <table>
              <thead><tr><th>시각</th><th>종류</th><th>경로</th><th>상태</th><th>질문</th>
                <th class="num">시간</th><th class="num">토큰</th><th>품질 검토</th></tr></thead>
              <tbody>
                <tr v-for="r in runs" :key="r.run_id">
                  <td class="nowrap">{{ localTime(r.created_at) }}</td>
                  <td class="nowrap">{{ r.kind === 'approval' ? (r.approved ? '승인' : '반려') : '질문' }}</td>
                  <td class="nowrap">{{ ROUTE_KO[r.route] ?? '—' }}</td>
                  <td class="nowrap"><span class="badge" :class="{ exceeds: r.status === 'failed', review: r.status === 'awaiting_approval' }">
                    {{ RUN_STATUS_KO[r.status] ?? r.status }}</span></td>
                  <td>{{ r.question }}</td>
                  <td class="num">{{ secs(r.latency_ms) }}</td><td class="num">{{ num(r.tokens) }}</td>
                  <td class="nowrap">{{ r.quality_passed === null ? '—' : r.quality_passed ? '통과' : '미통과' }}</td>
                </tr>
                <tr v-if="!runs.length"><td colspan="8" class="muted">아직 기록이 없습니다</td></tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </main>
  </div>
</template>

<style scoped>
.shell { display: flex; flex-direction: column; min-height: 100%; }
.topbar {
  display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
  padding: 10px 20px; background: var(--panel); border-bottom: 1px solid var(--border);
}
.brand { display: flex; flex-direction: column; line-height: 1.3; }
.brand h1 { font-size: 16px; margin: 0; }
.tabs { display: flex; gap: 4px; flex: 1; flex-wrap: wrap; }
.tabs button { border-color: transparent; background: transparent; color: var(--muted); font-weight: 600; }
.tabs button.on { background: var(--accent-soft); color: var(--accent); }
.count { margin-left: 4px; padding: 0 6px; border-radius: 999px; background: var(--warn-soft); color: var(--warn); font-size: 12px; }
.content { padding: 20px; max-width: 1200px; width: 100%; margin: 0 auto; box-sizing: border-box; }
.stack { display: flex; flex-direction: column; gap: 16px; }
.pad { padding: 14px 16px; overflow-x: auto; }
h2, h3 { margin: 0 0 8px; font-size: 15px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.tile { padding: 12px 14px; }
.tile.warn { border-color: var(--warn); }
.tile .value { font-size: 22px; font-weight: 700; margin: 4px 0; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
td.good { color: var(--ok); font-weight: 700; }
.wrap { flex-wrap: wrap; }
.narrow { width: auto; }
.scroll { overflow-x: auto; }
.login { max-width: 360px; margin: 60px auto; padding: 20px; display: flex; flex-direction: column; gap: 10px; }
.button {
  display: inline-block; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--accent);
  color: var(--accent); text-decoration: none; white-space: nowrap;
}
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
