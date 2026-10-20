<script setup>
// 진행 상황 (R12) — 단계(노드)마다 묶어서, 그 안의 도구 호출·결과를 들여 보여 준다
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  items: { type: Array, required: true },     // [{text, tone, step, at}]
  running: { type: Boolean, default: false },
  started: { type: Number, default: 0 },         // performance.now() 기준 시작 시각 → 실행 중엔 초를 계속 올린다
})
const open = ref(true)

// 단계(step) 줄을 머리로, 그 뒤 줄들을 하위 항목으로 묶는다
const groups = computed(() => {
  const out = []
  for (const item of props.items) {
    if (item.step || !out.length) out.push({ head: item, children: [] })
    else out.at(-1).children.push(item)
  }
  return out
})
const now = ref(performance.now())
let timer = null
watch(() => props.running, on => {
  clearInterval(timer)
  if (on) timer = setInterval(() => { now.value = performance.now() }, 200)
}, { immediate: true })
onBeforeUnmount(() => clearInterval(timer))
const elapsed = computed(() => (props.running
  ? (now.value - props.started) / 1000
  : props.items.at(-1)?.at ?? 0).toFixed(1))
</script>

<template>
  <div class="progress" v-if="items.length">
    <button class="ghost toggle small" @click="open = !open">
      <span :class="{ spin: running }">{{ running ? '◐' : '✓' }}</span>
      진행 과정 {{ groups.length }}단계 · {{ elapsed }}초 {{ open ? '▾' : '▸' }}
    </button>
    <ol v-show="open">
      <li v-for="(g, i) in groups" :key="i" :class="{ current: running && i === groups.length - 1 }">
        <div class="head" :class="g.head.tone">{{ g.head.text }}</div>
        <div v-for="(c, j) in g.children" :key="j" class="child small" :class="c.tone">{{ c.text }}</div>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.progress { margin-bottom: 10px; }
.toggle { padding: 2px 4px; color: var(--muted); }
.spin { display: inline-block; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
ol { list-style: none; margin: 4px 0 0; padding: 0 0 0 6px; border-left: 2px solid var(--border); }
li { padding: 2px 0 2px 12px; position: relative; }
li::before {
  content: ''; position: absolute; left: -6px; top: 10px;
  width: 8px; height: 8px; border-radius: 50%; background: var(--border);
}
li.current::before { background: var(--accent); }
.head { font-weight: 600; font-size: 13px; }
.child { color: var(--muted); padding-left: 4px; overflow-wrap: anywhere; }
.child.fail, .head.fail { color: var(--danger); }
.child.warn, .head.warn { color: var(--warn); }
</style>
