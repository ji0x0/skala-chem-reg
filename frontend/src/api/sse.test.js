import { describe, expect, it } from 'vitest'
import { SSEParser } from './sse.js'

const encode = s => new TextEncoder().encode(s)

describe('SSEParser', () => {
  it('한 청크에 이벤트 여러 개', () => {
    const p = new SSEParser()
    const events = p.push('event: run_started\ndata: {"run_id": "r1"}\n\nevent: token\ndata: {"delta": "안녕"}\n\n')
    expect(events).toEqual([
      { event: 'run_started', data: { run_id: 'r1' } },
      { event: 'token', data: { delta: '안녕' } },
    ])
  })

  it('이벤트가 청크 경계에서 잘려도 합쳐서 읽는다', () => {
    const p = new SSEParser()
    expect(p.push('event: tok')).toEqual([])
    expect(p.push('en\ndata: {"delta"')).toEqual([])
    expect(p.push(': "a"}\n')).toEqual([])
    expect(p.push('\n')).toEqual([{ event: 'token', data: { delta: 'a' } }])
  })

  it('CRLF 줄바꿈, 주석(keep-alive), 여러 줄 data', () => {
    const p = new SSEParser()
    const events = p.push(': ping\r\n\r\nevent: final\r\ndata: line1\r\ndata: line2\r\n\r\n')
    expect(events).toEqual([{ event: 'final', data: 'line1\nline2' }])
  })

  it('한글 UTF-8 바이트가 청크 사이에서 잘려도 깨지지 않는다 (TextDecoder stream)', () => {
    const bytes = encode('event: token\ndata: {"delta": "규제"}\n\n')
    const cut = bytes.indexOf(0xea) + 1                  // '규'(EA B7 9C)의 첫 바이트 뒤에서 자름
    const decoder = new TextDecoder('utf-8')
    const p = new SSEParser()
    const events = [
      ...p.push(decoder.decode(bytes.slice(0, cut), { stream: true })),
      ...p.push(decoder.decode(bytes.slice(cut), { stream: true })),
    ]
    expect(events).toEqual([{ event: 'token', data: { delta: '규제' } }])
  })
})
