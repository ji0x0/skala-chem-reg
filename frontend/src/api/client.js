// REST 호출 공통 처리 — 화면은 fetch를 직접 부르지 않고 이 함수들을 쓴다 (AJAX, R50)
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000/api/v1'

// 서버가 돌려준 오류를 화면에 보여 줄 수 있는 형태로 바꾼다
export class ApiError extends Error {
  constructor(status, message, errors = []) {
    super(message)
    this.status = status
    this.errors = errors          // 422 업무 규칙 오류 목록 (어느 성분이 왜 틀렸는지)
  }
}

function toApiError(status, body) {
  const detail = body?.detail
  if (typeof detail === 'string') return new ApiError(status, detail)
  if (detail?.message) return new ApiError(status, detail.message, detail.errors ?? [])
  if (Array.isArray(detail)) {    // Pydantic 형식 오류: [{loc, msg}]
    return new ApiError(status, '입력 형식이 맞지 않습니다.',
      detail.map(d => `${d.loc.slice(1).join('.')}: ${d.msg}`))
  }
  return new ApiError(status, `요청 실패 (HTTP ${status})`)
}

export async function request(path, { method = 'GET', body, signal, headers = {} } = {}) {
  let res
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method, signal,
      headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...headers },   // headers: 관리자 토큰 등
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new ApiError(0, `백엔드에 연결할 수 없습니다 (${API_BASE})`)
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) throw toApiError(res.status, data)
  return data
}

export const api = {
  health: () => request('/health'),
  thread: id => request(`/threads/${encodeURIComponent(id)}`),
  threads: () => request('/threads'),
  createThread: () => request('/threads', { method: 'POST' }),
  renameThread: (id, title) => request(`/threads/${encodeURIComponent(id)}`, { method: 'PATCH', body: { title } }),
  deleteThread: id => request(`/threads/${encodeURIComponent(id)}`, { method: 'DELETE' }),   // 목록에서 숨김 (기록은 남음)
  feedback: (runId, score, comment = '') =>
    request('/feedback', { method: 'POST', body: { run_id: runId, score, comment } }),
  products: () => request('/products'),
  product: id => request(`/products/${encodeURIComponent(id)}`),
  createProduct: p => request('/products', { method: 'POST', body: p }),
  updateProduct: (id, p) => request(`/products/${encodeURIComponent(id)}`, { method: 'PUT', body: p }),
  weekly: () => request('/weekly'),
  weeklyOne: id => request(`/weekly/${encodeURIComponent(id)}`),
  reviewWeekly: (id, reviewer, comment) =>
    request(`/weekly/${encodeURIComponent(id)}/review`, { method: 'POST', body: { reviewer, comment } }),
  regulations: () => request('/regulations'),
  regulation: id => request(`/regulations/${encodeURIComponent(id)}`),
  substances: q => request(`/substances?q=${encodeURIComponent(q)}`),
}
