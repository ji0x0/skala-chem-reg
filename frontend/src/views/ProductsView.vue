<script setup>
// 제품 관리 화면 (R54) — 목록(판정 요약) · 상세(배합표 + 판정) · 추가·수정
// 제품은 앱 DB가 원본. 저장하면 서버가 검증 → 저장 → 판정까지 해서 돌려준다
import { computed, inject, onMounted, ref, watch } from 'vue'
import { outcomeKo } from '../lib/labels.js'
import { api } from '../api/client.js'
import JudgementTable from '../components/JudgementTable.vue'
import ProductForm from '../components/ProductForm.vue'

const productFocus = inject('productFocus')     // 다른 탭(규제 검색)에서 고른 제품
const products = ref([])
const query = ref('')
const selected = ref(null)                      // {product, judgement}
const mode = ref('view')                        // view | create | edit
const loading = ref(false)
const error = ref('')
const notice = ref('')

const FORM = { article: '성형품', mixture: '혼합물' }
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return products.value
  return products.value.filter(p => `${p.product_id} ${p.product_name} ${p.export_regions.join(' ')}`.toLowerCase().includes(q))
})

async function loadList() {
  try {
    products.value = await api.products()
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

async function open(id) {
  mode.value = 'view'
  notice.value = ''
  loading.value = true
  try {
    selected.value = await api.product(id)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function onSaved(result) {
  const isNew = mode.value === 'create'
  selected.value = result
  mode.value = 'view'
  notice.value = `${result.product.product_id} ${isNew ? '추가' : '수정'} 완료 — 판정 결과를 확인하세요. 질의응답에서도 바로 질문할 수 있습니다.`
  await loadList()
}

watch(productFocus, id => { if (id) open(id) })
onMounted(async () => {
  await loadList()
  if (productFocus.value) open(productFocus.value)
  else if (products.value.length) open(products.value[0].product_id)
})
</script>

<template>
  <div class="products">
    <section class="list panel">
      <header class="row">
        <h2>제품 {{ products.length }}개</h2>
        <span class="spacer"></span>
        <button class="primary small" @click="mode = 'create'; notice = ''">+ 새 제품</button>
      </header>
      <input v-model="query" placeholder="ID·이름·지역 검색" class="search" />
      <div v-if="error" class="error-box small">{{ error }}</div>
      <ul>
        <li v-for="p in filtered" :key="p.product_id"
            :class="{ on: selected?.product.product_id === p.product_id && mode !== 'create' }"
            tabindex="0" role="button" @click="open(p.product_id)" @keydown.enter="open(p.product_id)">
          <div class="row">
            <strong class="mono">{{ p.product_id }}</strong>
            <span class="name">{{ p.product_name }}</span>
          </div>
          <div class="row small muted">
            <span>{{ FORM[p.product_form] }} · {{ p.export_regions.join(', ') }} · 성분 {{ p.ingredient_count }}</span>
          </div>
          <div class="row badges">
            <template v-for="o in ['exceeds', 'listed', 'review']" :key="o">
              <span v-if="p.summary[o]" class="badge" :class="o">{{ outcomeKo(o) }} {{ p.summary[o] }}</span>
            </template>
            <span v-if="!p.summary.exceeds && !p.summary.listed && !p.summary.review" class="badge below">규제 문제 없음</span>
          </div>
        </li>
      </ul>
    </section>

    <section class="detail">
      <ProductForm v-if="mode === 'create'" key="new" @saved="onSaved" @cancel="mode = 'view'" />
      <ProductForm v-else-if="mode === 'edit' && selected" :key="`edit-${selected.product.product_id}`"
                   :product="selected.product" @saved="onSaved" @cancel="mode = 'view'" />

      <template v-else-if="selected">
        <div v-if="notice" class="notice small">✓ {{ notice }}</div>
        <article class="panel box" :class="{ dim: loading }">
          <header class="row">
            <div>
              <h2><span class="mono">{{ selected.product.product_id }}</span> {{ selected.product.product_name }}</h2>
              <p class="small muted">
                {{ FORM[selected.product.product_form] }} ({{ selected.product.product_form }})
                · 수출 {{ selected.product.export_regions.join(', ') }}
                · 수정 {{ selected.product.updated_at }}
              </p>
            </div>
            <span class="spacer"></span>
            <button @click="mode = 'edit'">수정</button>
          </header>

          <h3>배합</h3>
          <div class="scroll">
            <table class="small">
              <thead><tr><th>CAS</th><th>성분</th><th>역할</th><th class="num">wt%</th></tr></thead>
              <tbody>
                <tr v-for="i in selected.product.ingredients" :key="i.cas">
                  <td class="mono">{{ i.cas }}</td>
                  <td>{{ i.ingredient_name }}</td>
                  <td :class="{ minor: /불순물|잔류/.test(i.role) }">{{ i.role }}</td>
                  <td class="num">{{ i.wt_pct }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <h3>규제 판정 <span class="small muted">— 코드가 수출 지역·형태·함량 기준으로 대조</span></h3>
          <JudgementTable :judgement="selected.judgement" />
        </article>
      </template>
      <p v-else class="muted empty">왼쪽에서 제품을 고르거나 새 제품을 추가하세요.</p>
    </section>
  </div>
</template>

<style scoped>
.products { display: grid; grid-template-columns: 320px 1fr; gap: 16px; height: 100%; padding: 16px 20px; }
.list { display: flex; flex-direction: column; min-height: 0; padding: 12px; gap: 8px; }
h2 { font-size: 15px; margin: 0; }
h3 { font-size: 13px; margin: 16px 0 6px; }
.search { font-size: 13px; }
ul { list-style: none; margin: 0; padding: 0; overflow-y: auto; }
li { padding: 8px 10px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; }
li:hover { background: var(--panel-2); }
li.on { background: var(--accent-soft); border-color: var(--accent); }
li .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badges { flex-wrap: wrap; gap: 4px; margin-top: 2px; }
.detail { overflow-y: auto; min-width: 0; }
.box { padding: 14px 16px; transition: opacity .2s; }
.box header p { margin: 2px 0 0; }
.dim { opacity: .5; }
.scroll { overflow-x: auto; }
.num { text-align: right; }
.minor { color: var(--warn); }
.notice { background: var(--ok-soft); color: var(--ok); border-radius: 8px; padding: 8px 12px; margin-bottom: 10px; }
.empty { text-align: center; margin-top: 80px; }
@media (max-width: 760px) {
  .products { grid-template-columns: 1fr; grid-template-rows: 260px 1fr; padding: 12px; }
}
</style>
