<script setup>
// 제품 판정표 — 코드가 제품 배합 × 규제 DB를 대조한 결과 (LLM 없음)
// 심각한 것부터: exceeds → listed → review. below(기준 이하)와 적용 제외는 접어 둔다
import { computed, ref } from 'vue'

const props = defineProps({ judgement: { type: Object, required: true } })
const ORDER = { exceeds: 0, listed: 1, review: 2, below: 3 }
const showBelow = ref(false)
const showSkipped = ref(false)

const sorted = computed(() => [...props.judgement.findings].sort((a, b) => ORDER[a.outcome] - ORDER[b.outcome]))
const main = computed(() => sorted.value.filter(f => f.outcome !== 'below'))
const below = computed(() => sorted.value.filter(f => f.outcome === 'below'))
const pct = v => v == null ? '—' : `${v}%`
</script>

<template>
  <div class="judgement">
    <div class="row summary">
      <template v-for="(n, o) in judgement.summary" :key="o">
        <span v-if="n" class="badge" :class="o">{{ o }} {{ n }}</span>
      </template>
      <span class="spacer"></span>
      <span v-if="judgement.unverified_data" class="small muted">⚠ 원본 확인 전 규제 데이터 포함</span>
    </div>

    <p v-if="!judgement.findings.length" class="muted small">해당하는 규제 등재가 없습니다 (수출 지역 기준).</p>

    <div class="scroll" v-else>
      <table class="small">
        <thead>
          <tr><th>결과</th><th>규제</th><th>물질 (역할)</th><th>함량 / 기준</th><th>이유 · 의무</th></tr>
        </thead>
        <tbody>
          <template v-for="list in [main, showBelow ? below : []]">
            <tr v-for="f in list" :key="`${f.reg_id}-${f.cas}`">
              <td><span class="badge" :class="f.outcome">{{ f.outcome }}</span></td>
              <td>
                <strong>{{ f.region }}</strong> {{ f.list_name }}
                <div class="muted" v-if="f.entry_ref">{{ f.entry_ref }}</div>
              </td>
              <td>
                {{ f.substance }} <span class="muted">({{ f.role }})</span>
                <div class="mono muted">{{ f.cas }}</div>
              </td>
              <td class="nowrap">{{ pct(f.wt_pct) }} / {{ pct(f.threshold_wt_pct) }}</td>
              <td>
                {{ f.reason }}
                <div class="muted" v-if="f.obligation">→ {{ f.obligation }}</div>
                <div class="muted">
                  <a v-if="f.source_url" :href="f.source_url" target="_blank" rel="noopener noreferrer">출처 ↗</a>
                  <span v-if="f.data_status !== 'official'" class="badge to_verify">원본 확인 전</span>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <div class="row toggles small">
      <button v-if="below.length" class="ghost" @click="showBelow = !showBelow">
        {{ showBelow ? '기준 이하 숨기기' : `기준 이하 ${below.length}건 보기` }}
      </button>
      <button v-if="judgement.skipped?.length" class="ghost" @click="showSkipped = !showSkipped">
        {{ showSkipped ? '적용 제외 숨기기' : `적용 제외 ${judgement.skipped.length}건 보기` }}
      </button>
    </div>
    <ul v-if="showSkipped" class="skipped small muted">
      <li v-for="s in judgement.skipped" :key="`${s.reg_id}-${s.cas}`">
        {{ s.region }} {{ s.list_name }} · {{ s.substance }} — {{ s.reason }}
      </li>
    </ul>
  </div>
</template>

<style scoped>
.summary { margin-bottom: 8px; flex-wrap: wrap; }
.scroll { overflow-x: auto; }
.mono { white-space: nowrap; }
th:last-child { width: 38%; }
.nowrap { white-space: nowrap; }
td a { color: var(--accent); text-decoration: none; margin-right: 6px; }
.toggles { margin-top: 4px; }
.toggles button { padding: 2px 6px; color: var(--accent); }
.skipped { margin: 4px 0 0; padding-left: 18px; }
</style>
