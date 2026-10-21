// 관리자 API — 모든 요청에 관리자 토큰(Bearer)을 붙인다. 토큰은 탭을 닫으면 사라지는 sessionStorage에만 둔다
import { request } from '../api/client.js'

const KEY = 'chem-reg-admin-token'
let memoryToken = ''                       // 저장소가 막힌 브라우저(사생활 보호 모드 등)에서는 메모리에만

export function loadToken() {
  try { return sessionStorage.getItem(KEY) ?? memoryToken } catch { return memoryToken }
}

export function saveToken(token) {
  memoryToken = token
  try { token ? sessionStorage.setItem(KEY, token) : sessionStorage.removeItem(KEY) } catch { /* 메모리만 사용 */ }
}

const get = path => request(`/admin${path}`, { headers: { Authorization: `Bearer ${loadToken()}` } })

export const adminApi = {
  overview: () => get('/overview'),
  runs: (kind = '') => get(`/runs?limit=100${kind ? `&kind=${kind}` : ''}`),
  approvals: () => get('/approvals'),
  feedback: () => get('/feedback'),
  evaluations: () => get('/evaluations'),
}

// 표기 — 경로·상태 내부 값은 그대로 두고 화면에는 한글만
export const ROUTE_KO = { chat: '일반 대화', lookup: '규제 조회', briefing: '변경 브리핑' }
export const RUN_STATUS_KO = { completed: '완료', awaiting_approval: '승인 대기', failed: '실패' }

// SQLite CURRENT_TIMESTAMP(UTC, 'YYYY-MM-DD HH:MM:SS')와 ISO 시각을 모두 현지 시각으로
export function localTime(ts) {
  if (!ts) return ''
  const d = new Date(ts.includes('T') ? ts : `${ts.replace(' ', 'T')}Z`)
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' })
}
