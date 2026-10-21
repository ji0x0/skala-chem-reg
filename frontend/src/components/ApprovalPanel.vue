<script setup>
// 담당자 승인 (Human-in-the-loop) — 영향 제품을 다른 부서에 공유하기 전에 승인·반려
import { ref } from 'vue'
import { outcomeKo } from '../lib/labels.js'

const props = defineProps({
  request: { type: Object, required: true },     // {impacted_products, message}
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['decide'])
const comment = ref('')
const approver = ref('규제 담당자')

function decide(approved) {
  emit('decide', { approved, comment: comment.value.trim(), approver: approver.value.trim() || '규제 담당자' })
}
</script>

<template>
  <div class="approval">
    <p class="msg">⏸ {{ props.request.message || '담당자 승인이 필요합니다.' }}</p>
    <table class="small">
      <thead><tr><th>제품</th><th>근거 문서</th><th>판정</th></tr></thead>
      <tbody>
        <tr v-for="p in props.request.impacted_products" :key="`${p.product_id}-${p.document_number}`">
          <td><strong>{{ p.product_id }}</strong> {{ p.product_name }}</td>
          <td class="mono">{{ p.document_number ?? '규제 DB 대조' }}</td>
          <td><span v-for="o in p.outcomes" :key="o" class="badge" :class="o">{{ outcomeKo(o) }}</span></td>
        </tr>
      </tbody>
    </table>
    <div class="form">
      <input v-model="approver" placeholder="승인자" maxlength="50" class="who" />
      <input v-model="comment" placeholder="의견 (예: P003 고객 공지 진행)" maxlength="500" @keydown.enter="decide(true)" />
    </div>
    <div class="row">
      <button class="primary" :disabled="busy" @click="decide(true)">승인 — 관련 부서에 공유</button>
      <button class="danger" :disabled="busy" @click="decide(false)">반려</button>
    </div>
  </div>
</template>

<style scoped>
.approval {
  margin-top: 12px; padding: 12px;
  border: 1px solid var(--warn); background: var(--warn-soft); border-radius: 8px;
}
.msg { margin: 0 0 8px; font-weight: 600; color: var(--warn); }
table { background: var(--panel); border-radius: 6px; margin-bottom: 8px; }
td .badge { margin-right: 4px; }
.form { display: flex; gap: 8px; margin-bottom: 8px; }
.who { width: 140px; flex: none; }
</style>
