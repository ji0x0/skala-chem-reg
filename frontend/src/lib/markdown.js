// 답변 Markdown → 안전한 HTML
// LLM이 만든 글을 v-html로 넣으므로 반드시 DOMPurify로 정화한다 (스크립트·이벤트 속성 제거)
import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ gfm: true, breaks: true })

// 본문의 [1], [2] 근거 번호를 클릭 가능한 링크로 바꾼다. 실제 있는 근거 번호만 (없는 번호는 그대로 둠)
export function linkCitations(text, ids) {
  const known = new Set(ids.map(String))
  return text.replace(/\[(\d{1,3})\](?!\()/g, (m, n) =>
    known.has(n) ? `<a class="cite-ref" data-cite="${n}">[${n}]</a>` : m)
}

// 모델이 답 전체를 ```markdown … ``` 으로 감싸 보내는 경우 — 스트리밍 중(닫는 ``` 전)에도 벗긴다
export function stripFence(text) {
  const m = text.match(/^\s*```[a-zA-Z]*\n/)
  if (!m) return text
  return text.slice(m[0].length).replace(/\n?```\s*$/, '')
}

export function renderMarkdown(text, citationIds = []) {
  const html = marked.parse(linkCitations(stripFence(text ?? ''), citationIds))
  return DOMPurify.sanitize(html, { ADD_ATTR: ['data-cite'] })
}
