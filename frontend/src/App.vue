<script setup>
// 앱 셸 — 상단 바(백엔드 상태)와 탭. 화면 전환은 탭 상태로만 한다 (화면 3개라 라우터 없이)
import { onMounted, ref } from 'vue'
import { api } from './api/client.js'
import ChatView from './views/ChatView.vue'

const tabs = [
  { id: 'chat', label: '질의응답·브리핑', component: ChatView },
]
const active = ref(tabs[0].id)
const health = ref(null)
const healthError = ref('')

async function loadHealth() {
  try {
    health.value = await api.health()
    healthError.value = ''
  } catch (e) {
    health.value = null
    healthError.value = e.message
  }
}
onMounted(loadHealth)
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <h1>국내외 화학물질 규제 브리핑</h1>
        <span class="muted small">법률 자문이 아니며 최종 판단은 담당자가 합니다</span>
      </div>
      <nav class="tabs">
        <button v-for="t in tabs" :key="t.id" :class="{ on: active === t.id }" @click="active = t.id">
          {{ t.label }}
        </button>
      </nav>
      <button class="status" :class="health ? 'up' : 'down'" :title="healthError || '다시 확인'" @click="loadHealth">
        <span class="dot"></span>
        <template v-if="health">{{ health.pipeline }} · {{ health.quality_model }} · 도구 {{ health.tools.length }}</template>
        <template v-else>백엔드 연결 안 됨</template>
      </button>
    </header>
    <main class="content">
      <!-- KeepAlive: 탭을 바꿔도 진행 중인 대화·입력값을 유지 -->
      <KeepAlive>
        <component :is="tabs.find(t => t.id === active).component" :health="health" />
      </KeepAlive>
    </main>
  </div>
</template>

<style scoped>
.shell { display: flex; flex-direction: column; height: 100%; }
.topbar {
  display: flex; align-items: center; gap: 20px;
  padding: 10px 20px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}
.brand h1 { font-size: 16px; margin: 0; }
.brand { display: flex; flex-direction: column; line-height: 1.3; }
.tabs { display: flex; gap: 4px; flex: 1; }
.tabs button { border-color: transparent; background: transparent; color: var(--muted); font-weight: 600; }
.tabs button.on { background: var(--accent-soft); color: var(--accent); }
.status { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); white-space: nowrap; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--danger); }
.status.up .dot { background: var(--ok); }
.content { flex: 1; min-height: 0; }
@media (max-width: 760px) {
  .topbar { flex-wrap: wrap; gap: 8px; padding: 10px 12px; }
  .tabs { order: 3; width: 100%; }
}
</style>
