<script setup>
// 규제 목록 화면 (R55) — 지역별 규제 → 등재 물질, 물질 검색(CAS·이름) → 등재 규제와 함유 제품
import { computed, inject, onMounted, ref } from 'vue'
import { api } from '../api/client.js'

const openProduct = inject('openProduct')
const regulations = ref([])
const selected = ref(null)              // 규제 상세 {…, listings}
const query = ref('')
const search = ref(null)                // 물질 검색 결과
const error = ref('')

const REGION_NAMES = { KR: '국내', US: '미국', EU: 'EU', CN: '중국', JP: '일본' }
const RULE_TYPES = { listing: '등재 목록 (함유·함량 기준)', restriction: '제한 (함량 기준·용도)', classification: '유해성 분류', notification: '사전 통보' }
const PRIORITY = { 1: '우선 1', 2: '우선 2', 3: '우선 3' }

const byRegion = computed(() => {
  const groups = {}
  for (const r of regulations.value) (groups[r.region] ??= []).push(r)
  return Object.keys(REGION_NAMES).filter(k => groups[k]).map(k => ({ region: k, items: groups[k] }))
})
const regName = id => regulations.value.find(r => r.reg_id === id)

async function openReg(id) {
  search.value = null
  try {
    selected.value = await api.regulation(id)
  } catch (e) {
    error.value = e.message
  }
}

async function runSearch(q = query.value) {
  q = q.trim()
  if (!q) return
  query.value = q
  try {
    const r = await api.substances(q)
    // 같은 제품이 여러 성분으로 걸리면 제품 하나로 묶는다
    const products = {}
    for (const p of r.products) (products[p.product_id] ??= { ...p, hits: [] }).hits.push(`${p.ingredient_name} ${p.wt_pct}%`)
    search.value = { ...r, productList: Object.values(products) }
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

onMounted(async () => {
  try {
    regulations.value = await api.regulations()
    if (regulations.value.length) openReg(regulations.value[0].reg_id)
  } catch (e) {
    error.value = e.message
  }
})
</script>

<template>
  <div class="regs">
    <aside class="side panel">
      <form class="row" @submit.prevent="runSearch()">
        <input v-model="query" placeholder="물질 검색: CAS 또는 이름 (예: 79-01-6, 납)" maxlength="60" />
        <button type="submit">검색</button>
      </form>
      <div v-if="error" class="error-box small">{{ error }}</div>
      <div class="groups">
        <section v-for="g in byRegion" :key="g.region">
          <h3 class="small muted">{{ REGION_NAMES[g.region] }} ({{ g.region }})</h3>
          <button v-for="r in g.items" :key="r.reg_id" class="reg"
                  :class="{ on: !search && selected?.reg_id === r.reg_id }" @click="openReg(r.reg_id)">
            <span class="law small muted">{{ r.law }}</span>
            <span>{{ r.list_name }}</span>
            <span class="small muted">
              {{ r.listing_count ? `등재 ${r.listing_count.toLocaleString('ko-KR')}` : (r.listing_note ? '지정 물질 없음·목록화 제외' : '등재 데이터 없음') }}
              <template v-if="r.unverified"> · 확인 전 {{ r.unverified }}</template>
            </span>
          </button>
        </section>
      </div>
    </aside>

    <section class="detail">
      <!-- 물질 검색 결과 -->
      <article v-if="search" class="panel box">
        <header class="row">
          <h2>“{{ search.query }}” 검색 결과</h2>
          <span class="spacer"></span>
          <button class="ghost small" @click="search = null">닫기</button>
        </header>
        <p v-if="!search.substances.length" class="muted">규제 DB에 등재된 물질 중 일치하는 것이 없습니다.</p>
        <template v-else>
          <p class="small">
            <span v-for="s in search.substances" :key="s.cas" class="chip">
              <span class="mono">{{ s.cas }}</span> {{ s.name_ko }} · {{ s.name_en }}
            </span>
          </p>
          <h3>등재 규제 {{ search.listings.length }}건</h3>
          <div class="scroll">
            <table class="small">
              <thead><tr><th>규제</th><th>물질</th><th>항목</th><th>기준</th><th>조건</th><th>상태</th></tr></thead>
              <tbody>
                <tr v-for="l in search.listings" :key="`${l.reg_id}-${l.cas}-${l.entry_ref}`">
                  <td><button type="button" class="link" @click="openReg(l.reg_id)">{{ regName(l.reg_id)?.region }} {{ regName(l.reg_id)?.list_name ?? l.reg_id }}</button></td>
                  <td>{{ l.name_ko }} <span class="mono muted">{{ l.cas }}</span></td>
                  <td class="nowrap">{{ l.entry_ref || '—' }}</td>
                  <td class="nowrap">{{ l.threshold_wt_pct != null ? `${l.threshold_wt_pct} wt%` : '—' }}</td>
                  <td>{{ l.condition_ko }}</td>
                  <td><span class="badge" :class="l.status">{{ l.status === 'official' ? '공식' : '확인 전' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <h3>함유 제품 {{ search.productList.length }}개</h3>
          <p v-if="!search.productList.length" class="muted small">이 물질이 든 제품이 없습니다.</p>
          <ul class="prods">
            <li v-for="p in search.productList" :key="p.product_id">
              <button type="button" class="link" @click="openProduct(p.product_id)"><strong class="mono">{{ p.product_id }}</strong> {{ p.product_name }}</button>
              <span class="small muted"> · 수출 {{ p.export_regions.split(';').join(', ') }} · {{ p.hits.join(', ') }}</span>
            </li>
          </ul>
        </template>
      </article>

      <!-- 규제 상세 -->
      <article v-else-if="selected" class="panel box">
        <header>
          <p class="small muted">{{ REGION_NAMES[selected.region] }} · {{ selected.law }} · {{ selected.authority }} · {{ PRIORITY[selected.priority] }}</p>
          <h2>{{ selected.list_name }} <span class="mono small muted">{{ selected.reg_id }}</span></h2>
        </header>
        <dl class="small">
          <dt>적용 대상</dt><dd>{{ selected.applies_when }}</dd>
          <dt>판정 방식</dt><dd>{{ RULE_TYPES[selected.rule_type] ?? selected.rule_type }}
            <template v-if="selected.default_threshold_wt_pct != null"> · 기본 기준 {{ selected.default_threshold_wt_pct }} wt%</template></dd>
          <dt>의무</dt><dd>{{ selected.obligation_ko }}</dd>
          <dt>출처</dt><dd><a :href="selected.source_url" target="_blank" rel="noopener noreferrer">{{ selected.source_url }} ↗</a></dd>
        </dl>

        <h3>등재 물질 {{ selected.listings.length }}개</h3>
        <p v-if="selected.listing_note" class="small note">ℹ️ {{ selected.listing_note }}</p>
        <p v-if="!selected.listings.length && !selected.listing_note" class="muted small">
          아직 등재 데이터를 넣지 않은 규제입니다. 판정에서 빠지므로 "해당 없음"으로 오해하지 않도록 주의하세요.
        </p>
        <div v-else class="scroll">
          <table class="small">
            <thead><tr><th>CAS</th><th>물질</th><th>항목</th><th>기준</th><th>조건</th><th>상태</th></tr></thead>
            <tbody>
              <tr v-for="l in selected.listings" :key="`${l.cas}-${l.entry_ref}`">
                <td><button type="button" class="link mono" title="이 물질 검색" @click="runSearch(l.cas)">{{ l.cas }}</button></td>
                <td>{{ l.name_ko }}<div class="muted">{{ l.name_en }}</div></td>
                <td class="nowrap">{{ l.entry_ref || '—' }}</td>
                <td class="nowrap">{{ l.threshold_wt_pct != null ? `${l.threshold_wt_pct} wt%` : '—' }}</td>
                <td>{{ l.condition_ko }}</td>
                <td><span class="badge" :class="l.status">{{ l.status === 'official' ? '공식' : '확인 전' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="small muted">“확인 전”은 공식 원본과 대조하기 전인 데이터입니다. 판정 결과에도 같은 표시가 붙습니다.</p>
      </article>
    </section>
  </div>
</template>

<style scoped>
.regs { display: grid; grid-template-columns: 320px 1fr; gap: 16px; height: 100%; padding: 16px 20px; }
.side { display: flex; flex-direction: column; gap: 10px; padding: 12px; min-height: 0; }
.side input { font-size: 13px; }
.side form button { white-space: nowrap; flex: none; }
.groups { overflow-y: auto; }
h2 { font-size: 15px; margin: 0; }
h3 { font-size: 13px; margin: 14px 0 6px; }
.side h3 { margin: 10px 0 4px; }
.reg {
  display: flex; flex-direction: column; align-items: flex-start; gap: 0;
  width: 100%; text-align: left; margin-bottom: 4px; border-color: transparent; line-height: 1.4;
}
.reg:hover { background: var(--panel-2); }
.reg.on { background: var(--accent-soft); border-color: var(--accent); }
.detail { overflow-y: auto; min-width: 0; }
.box { padding: 14px 16px; }
.box header p { margin: 0; }
dl { display: grid; grid-template-columns: 80px 1fr; gap: 4px 12px; margin: 12px 0; }
dt { color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; }
dd a, .link { color: var(--accent); text-decoration: none; cursor: pointer; }
button.link { background: none; border: none; padding: 0; font: inherit; text-align: left; }
.link:hover { text-decoration: underline; }
.scroll { overflow-x: auto; }
.scroll table { min-width: 680px; }
.chip { display: inline-block; background: var(--panel-2); border-radius: 6px; padding: 2px 8px; margin: 0 6px 4px 0; }
.prods { padding-left: 18px; margin: 0; }
.note { background: var(--panel-2); border-radius: 6px; padding: 6px 10px; }
@media (max-width: 760px) {
  .regs { grid-template-columns: 1fr; grid-template-rows: 280px 1fr; padding: 12px; }
}
</style>
