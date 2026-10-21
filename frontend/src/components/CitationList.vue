<script setup>
// 답변 근거 (R56) — 원문 문장(코드가 추출) · 한국어 번역(무결성 통과분만) · 출처 · 기준일 · 검증 상태
// 원문은 LLM이 쓰지 않는다. 번역이 없으면 무결성 검사에서 버려진 것 → 원문만 보여 준다
import { ref } from 'vue'
import { STATUS_KO as STATUS, outcomeKo } from '../lib/labels.js'

defineProps({
  citations: { type: Array, required: true },
  prefix: { type: String, default: 'cite' },      // 답변이 여러 개여도 id가 겹치지 않게
  highlight: { type: Number, default: null },     // 본문에서 [n]을 누르면 해당 근거 강조
})
const showOriginal = ref({})                      // 번역이 있는 근거도 원문 펼쳐 보기

const host = url => { try { return new URL(url).host } catch { return url } }
</script>

<template>
  <section class="citations" v-if="citations.length">
    <h3 class="small muted">근거 {{ citations.length }}개 — 문서 근거는 출처 본문의 문장 그대로, 목록 근거는 규제 DB 등재 내용</h3>
    <article v-for="c in citations" :key="c.id" :id="`${prefix}-${c.id}`" class="cite"
             :class="{ hl: highlight === c.id }">
      <header class="row">
        <span class="num">[{{ c.id }}]</span>
        <span class="badge" :class="c.kind === 'document' ? 'official' : ''">{{ c.kind === 'document' ? '규제 문서' : '규제 목록' }}</span>
        <span v-if="c.extra?.outcome" class="badge" :class="c.extra.outcome">{{ outcomeKo(c.extra.outcome) }}</span>
        <strong class="title">{{ c.title }}</strong>
      </header>

      <p v-if="c.extra?.reason" class="small reason">판정 이유: {{ c.extra.reason }}</p>

      <template v-if="c.translation_ko">
        <blockquote class="ko">{{ c.translation_ko }}</blockquote>
        <button class="ghost small link" @click="showOriginal[c.id] = !showOriginal[c.id]">
          {{ showOriginal[c.id] ? '원문 접기' : '원문 보기' }}
        </button>
        <blockquote v-if="showOriginal[c.id]" class="orig" lang="en">{{ c.quote }}</blockquote>
      </template>
      <blockquote v-else class="orig">{{ c.quote }}</blockquote>

      <footer class="row small muted">
        <a v-if="c.url" :href="c.url" target="_blank" rel="noopener noreferrer">{{ c.source_id }} · {{ host(c.url) }} ↗</a>
        <span v-else>{{ c.source_id }}</span>
        <span>기준 {{ c.as_of }}</span>
        <span class="badge" :class="c.status">{{ STATUS[c.status] ?? c.status }}</span>
      </footer>
    </article>
  </section>
</template>

<style scoped>
.citations { margin-top: 14px; border-top: 1px dashed var(--border); padding-top: 10px; }
h3 { margin: 0 0 8px; font-weight: 600; }
.cite {
  padding: 10px 12px; margin-bottom: 8px;
  background: var(--panel-2); border-radius: 8px; border: 1px solid transparent;
  transition: border-color .3s, background .3s;
}
.cite.hl { border-color: var(--accent); background: var(--accent-soft); }
.num { font-weight: 700; color: var(--accent); }
.title { font-size: 13px; overflow-wrap: anywhere; }
header { flex-wrap: wrap; }
.reason { margin: 4px 0 0; }
blockquote { margin: 6px 0; padding: 4px 10px; border-left: 3px solid var(--border); overflow-wrap: anywhere; }
.ko { border-left-color: var(--accent); }
.orig { font-family: Georgia, "Times New Roman", serif; font-size: 13px; color: var(--muted); }
.link { padding: 0 2px; color: var(--accent); }
footer { flex-wrap: wrap; gap: 12px; margin-top: 4px; }
footer a { color: var(--accent); text-decoration: none; }
</style>
