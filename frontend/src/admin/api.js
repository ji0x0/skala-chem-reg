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

const call = (path, options = {}) => request(`/admin${path}`, { ...options, headers: { Authorization: `Bearer ${loadToken()}` } })
const get = path => call(path)

export const adminApi = {
  overview: () => get('/overview'),
  runs: (kind = '') => get(`/runs?limit=100${kind ? `&kind=${kind}` : ''}`),
  feedback: () => get('/feedback'),
  evaluations: () => get('/evaluations'),
  // Step 12: 규제 DB 갱신 후보 — 확인(새 버전 감지)·상세·승인/반려
  updates: () => get('/updates'),
  update: id => get(`/updates/${id}`),
  checkUpdates: () => call('/updates/check', { method: 'POST' }),
  decideUpdate: (id, approved, approver, comment) =>
    call(`/updates/${id}/decision`, { method: 'POST', body: { approved, approver, comment } }),
}

// 표기 — 경로·상태 내부 값은 그대로 두고 화면에는 한글만
export const ROUTE_KO = { chat: '일반 대화', lookup: '규제 조회', briefing: '변경 브리핑', regupdate: 'DB 갱신' }
export const RUN_STATUS_KO = { completed: '완료', awaiting_approval: '승인 대기', failed: '실패' }
export const RUN_KIND_KO = { question: '질문', weekly: '정기 브리핑', update: '갱신 확인' }
export const UPDATE_STATUS_KO = {
  pending: ['승인 대기', 'review'], applied: ['반영', 'below'], rejected: ['반려', 'exceeds'],
  failed: ['반영 실패', 'exceeds'], no_change: ['행 변화 없음', ''],
}
export const CHANGE_KO = { added: '추가', removed: '삭제', changed: '변경' }
export const OUTCOME_KO = { exceeds: '기준 초과', listed: '등재 해당', review: '확인 필요', below: '기준 이하' }
export const CHECK_KO = {
  proposed: '갱신 후보를 올렸습니다', no_new_version: '새 버전 없음', already_proposed: '이미 올린 버전',
  no_change: '새 버전이지만 행 변화 없음', failed: '확인 실패',
}

// 통합본 CELEX → 기준일: '02008R1272-20270101' → '2027-01-01'
export function versionDate(celex) {
  const m = /-(\d{4})(\d{2})(\d{2})$/.exec(celex ?? '')
  return m ? `${m[1]}-${m[2]}-${m[3]}` : (celex ?? '')
}

// SQLite CURRENT_TIMESTAMP(UTC, 'YYYY-MM-DD HH:MM:SS')와 ISO 시각을 모두 현지 시각으로
export function localTime(ts) {
  if (!ts) return ''
  const d = new Date(ts.includes('T') ? ts : `${ts.replace(' ', 'T')}Z`)
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' })
}
