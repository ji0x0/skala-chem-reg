import { describe, expect, it } from 'vitest'
import { linkCitations, stripFence } from './markdown.js'
import { describe as describeEvent } from './progress.js'

describe('linkCitations', () => {
  it('있는 근거 번호만 링크로 바꾸고 Markdown 링크는 건드리지 않는다', () => {
    const out = linkCitations('기한 연장 [1][2], 없는 번호 [9], 링크 [3](http://x)', [1, 2, 3])
    expect(out).toContain('data-cite="1"')
    expect(out).toContain('data-cite="2"')
    expect(out).toContain('[9]')
    expect(out).not.toContain('data-cite="9"')
    expect(out).toContain('[3](http://x)')
  })
})

describe('stripFence', () => {
  it('스트리밍 중(닫는 ``` 전)과 완료 후 모두 코드 블록 감싸기를 벗긴다', () => {
    expect(stripFence('```markdown\n## 요약\n본문')).toBe('## 요약\n본문')
    expect(stripFence('```markdown\n## 요약\n본문\n```')).toBe('## 요약\n본문')
    expect(stripFence('## 요약\n```py\nx\n```')).toBe('## 요약\n```py\nx\n```')   // 본문 중간 코드는 유지
  })
})

describe('진행 이벤트 문구', () => {
  it('도구 호출 결과와 걸린 시간', () => {
    const r = describeEvent('tool_call_end', { tool: 'judge_product_compliance', ok: true, summary: 'exceeds 2', latency_ms: 1530 })
    expect(r).toEqual({ text: '🔧 judge_product_compliance 완료 — exceeds 2 · 1.5초', tone: 'ok', tool: 'judge_product_compliance' })
  })

  it('품질 검토 불합격은 경고', () => {
    const r = describeEvent('progress', { kind: 'validation', data: { attempt: 1, passed: false, scores: { relevance: 3 } } })
    expect(r.tone).toBe('warn')
    expect(r.text).toContain('보완 필요')
  })

  it('토큰 같은 진행 외 이벤트는 표시하지 않음', () => {
    expect(describeEvent('token', { delta: 'a' })).toBeNull()
  })
})
