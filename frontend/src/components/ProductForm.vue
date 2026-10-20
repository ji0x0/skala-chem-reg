<script setup>
// 제품 추가·수정 폼 (R54) — 입력 중엔 화면 검사로 틀린 행을 바로 표시하고, 저장 시 서버가 최종 검증(422 → 오류 목록)
import { computed, reactive, ref } from 'vue'
import { api } from '../api/client.js'
import { checkIngredients } from '../lib/cas.js'

const props = defineProps({ product: { type: Object, default: null } })   // null이면 새 제품
const emit = defineEmits(['saved', 'cancel'])

const REGIONS = [['KR', '국내'], ['US', '미국'], ['EU', 'EU'], ['CN', '중국'], ['JP', '일본']]
const ROLES = ['주원료', '주용제', '가소제', '안정제', '난연제', '첨가제', '안료', '잔류 단량체', '불순물(제조 공정)']

const blank = () => ({ cas: '', ingredient_name: '', role: '', wt_pct: null })
// 수정 시 원본을 깊은 복사 (props는 반응형 Proxy라 structuredClone 불가 → JSON 복사). 취소하면 원본 그대로
const form = reactive(props.product
  ? JSON.parse(JSON.stringify(props.product))
  : { product_name: '', product_form: 'mixture', export_regions: ['KR'], ingredients: [blank()] })

const touched = ref(false)              // 처음부터 빨간 줄을 띄우지 않고, 저장을 한 번 누른 뒤부터 표시
const saving = ref(false)
const serverError = ref(null)
const check = computed(() => checkIngredients(form.ingredients))
const formErrors = computed(() => [
  ...(form.product_name.trim() ? [] : ['제품명을 입력하세요']),
  ...(form.export_regions.length ? [] : ['수출 지역을 1개 이상 고르세요']),
  ...check.value.errors,
])

function addRow() { form.ingredients.push(blank()) }
function removeRow(i) { if (form.ingredients.length > 1) form.ingredients.splice(i, 1) }

async function save() {
  touched.value = true
  serverError.value = null
  if (formErrors.value.length || !check.value.ok) return
  saving.value = true
  const body = {
    product_name: form.product_name.trim(),
    product_form: form.product_form,
    export_regions: form.export_regions,
    ingredients: form.ingredients.map(i => ({
      cas: i.cas.trim(), ingredient_name: i.ingredient_name.trim(), role: i.role.trim(), wt_pct: Number(i.wt_pct),
    })),
  }
  try {
    const result = props.product
      ? await api.updateProduct(props.product.product_id, body)
      : await api.createProduct(body)
    emit('saved', result)              // {product, judgement} — 저장 직후 판정
  } catch (e) {
    serverError.value = e
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="form panel" @submit.prevent="save">
    <header class="row">
      <h2>{{ product ? `${product.product_id} 수정` : '새 제품' }}</h2>
      <span class="spacer"></span>
      <button type="button" class="ghost" @click="emit('cancel')">닫기</button>
    </header>

    <div class="grid">
      <label>제품명
        <input v-model="form.product_name" maxlength="120" placeholder="예: 수성 방청 코팅제" />
      </label>
      <label>형태
        <select v-model="form.product_form">
          <option value="mixture">혼합물 (mixture) — 액상·분말 등</option>
          <option value="article">성형품 (article) — 필름·전선·부품 등</option>
        </select>
      </label>
    </div>

    <fieldset>
      <legend>수출 지역</legend>
      <label v-for="[code, name] in REGIONS" :key="code" class="check">
        <input type="checkbox" :value="code" v-model="form.export_regions" /> {{ name }} ({{ code }})
      </label>
    </fieldset>

    <div class="scroll">
      <table class="ingredients">
        <thead>
          <tr><th>CAS</th><th>성분명</th><th>역할</th><th class="num">함량 (wt%)</th><th></th></tr>
        </thead>
        <tbody>
          <template v-for="(ing, i) in form.ingredients" :key="i">
            <tr :class="{ bad: touched && check.rows[i] }">
              <td><input v-model="ing.cas" class="mono" placeholder="79-01-6" maxlength="12" /></td>
              <td><input v-model="ing.ingredient_name" placeholder="Trichloroethylene" maxlength="120" /></td>
              <td>
                <input v-model="ing.role" list="roles" placeholder="주용제" maxlength="40" />
              </td>
              <td><input v-model="ing.wt_pct" type="number" step="any" min="0" max="100" class="num" /></td>
              <td><button type="button" class="ghost" title="행 삭제" :disabled="form.ingredients.length === 1" @click="removeRow(i)">✕</button></td>
            </tr>
            <tr v-if="touched && check.rows[i]" class="row-error">
              <td colspan="5">{{ i + 1 }}번 성분: {{ check.rows[i] }}</td>
            </tr>
          </template>
        </tbody>
        <tfoot>
          <tr>
            <td colspan="3"><button type="button" @click="addRow">+ 성분 추가</button></td>
            <td class="num" :class="check.sumOk ? 'ok' : 'warn'">합계 {{ check.total }}</td>
            <td></td>
          </tr>
        </tfoot>
      </table>
      <datalist id="roles"><option v-for="r in ROLES" :key="r" :value="r" /></datalist>
    </div>
    <p class="small muted">미량 첨가제·잔류 단량체·불순물도 넣어야 정확히 판정됩니다 (예: 0.0005 wt%).</p>

    <div v-if="touched && formErrors.length" class="error-box small">
      <ul><li v-for="e in formErrors" :key="e">{{ e }}</li></ul>
    </div>
    <div v-if="serverError" class="error-box small">
      {{ serverError.message }}
      <ul v-if="serverError.errors.length"><li v-for="e in serverError.errors" :key="e">{{ e }}</li></ul>
    </div>

    <footer class="row">
      <span class="spacer"></span>
      <button type="button" @click="emit('cancel')">취소</button>
      <button type="submit" class="primary" :disabled="saving">{{ saving ? '저장 중…' : '저장하고 판정' }}</button>
    </footer>
  </form>
</template>

<style scoped>
.form { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
h2 { font-size: 15px; margin: 0; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
label input, label select { color: var(--text); font-size: 14px; }
fieldset { border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; display: flex; flex-wrap: wrap; gap: 12px; }
legend { font-size: 12px; color: var(--muted); padding: 0 4px; }
.check { flex-direction: row; align-items: center; color: var(--text); font-size: 13px; }
.check input { width: auto; }
.scroll { overflow-x: auto; }
.ingredients td { padding: 4px; border-bottom: none; }
.ingredients input { padding: 5px 8px; }
.num { text-align: right; width: 110px; }
tr.bad input { border-color: var(--danger); }
.row-error td { color: var(--danger); font-size: 12px; padding-top: 0; }
tfoot .ok { color: var(--ok); font-weight: 600; }
tfoot .warn { color: var(--danger); font-weight: 600; }
@media (max-width: 760px) { .grid { grid-template-columns: 1fr; } }
</style>
