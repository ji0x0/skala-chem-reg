// POST 응답의 SSE 스트림 읽기 (R50)
// EventSource는 GET만 되므로 fetch + ReadableStream으로 직접 파싱한다.
// 네트워크 청크는 이벤트 경계와 무관하게 잘려 온다 → 빈 줄(이벤트 끝)이 올 때까지 버퍼에 모은다.
import { API_BASE, ApiError } from './client.js'

export class SSEParser {
  constructor() {
    this.buffer = ''
  }

  // 텍스트 조각을 넣으면 완성된 이벤트 [{event, data}]를 돌려준다
  push(chunk) {
    this.buffer += chunk.replace(/\r\n?/g, '\n')
    const events = []
    let end
    while ((end = this.buffer.indexOf('\n\n')) >= 0) {
      const block = this.buffer.slice(0, end)
      this.buffer = this.buffer.slice(end + 2)
      const parsed = parseBlock(block)
      if (parsed) events.push(parsed)
    }
    return events
  }
}

function parseBlock(block) {
  let event = 'message'
  const data = []
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue            // 빈 줄·주석(keep-alive)
    const i = line.indexOf(':')
    const field = i < 0 ? line : line.slice(0, i)
    const value = i < 0 ? '' : line.slice(i + 1).replace(/^ /, '')
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
  }
  if (!data.length) return null
  const raw = data.join('\n')
  try {
    return { event, data: JSON.parse(raw) }
  } catch {
    return { event, data: raw }
  }
}

// path로 POST하고 이벤트가 올 때마다 onEvent(event, data)를 부른다. 스트림이 끝나면 resolve
export async function streamSSE(path, body, { onEvent, signal } = {}) {
  let res
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: 'POST', signal,
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
    })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new ApiError(0, `백엔드에 연결할 수 없습니다 (${API_BASE})`)
  }
  if (!res.ok) {                                           // 409 등은 스트림이 아니라 JSON 오류
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, typeof data?.detail === 'string' ? data.detail : `요청 실패 (HTTP ${res.status})`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')                 // stream: true → 청크 경계에서 잘린 한글 바이트 보존
  const parser = new SSEParser()
  for (;;) {
    const { value, done } = await reader.read()
    const text = done ? decoder.decode() : decoder.decode(value, { stream: true })
    for (const e of parser.push(text)) onEvent?.(e.event, e.data)
    if (done) break
  }
}

export const chatStream = (message, threadId, opts) =>
  streamSSE('/chat/stream', { message, thread_id: threadId }, opts)
