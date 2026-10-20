// 제품 입력 즉시 검사 — 서버 규칙(app/domain/cas.py, products.py)과 같은 규칙을 화면에서도 돌려
// 저장 전에 틀린 행을 바로 보여 준다. 최종 판단은 언제나 서버 (화면 검사는 편의 기능)
export const SUM_TOLERANCE = 0.5
const CAS_PATTERN = /^(\d{2,7})-(\d{2})-(\d)$/

// 71-43-2: 앞 숫자 7143을 오른쪽부터 1, 2, 3, 4를 곱해 더한 값의 끝자리 = 2
export function isValidCas(cas) {
  const m = CAS_PATTERN.exec((cas ?? '').trim())
  if (!m) return false
  const body = m[1] + m[2]
  const sum = [...body].reverse().reduce((acc, d, i) => acc + Number(d) * (i + 1), 0)
  return sum % 10 === Number(m[3])
}

// 성분 행 목록 → { rows: [행별 오류 문자열], total, sumOk, errors: [전체 오류] }
export function checkIngredients(ingredients) {
  const seen = new Set()
  const rows = ingredients.map(ing => {
    const cas = (ing.cas ?? '').trim()
    if (!cas) return 'CAS를 입력하세요'
    if (!isValidCas(cas)) return 'CAS 형식 또는 체크 디지트 오류'
    if (seen.has(cas)) return '같은 CAS가 이미 있음'
    seen.add(cas)
    if (!(ing.ingredient_name ?? '').trim()) return '성분명을 입력하세요'
    if (!(ing.role ?? '').trim()) return '역할을 입력하세요'
    const w = Number(ing.wt_pct)
    if (!(w > 0 && w <= 100)) return '함량은 0 초과 100 이하'
    return ''
  })
  const total = Math.round(ingredients.reduce((s, i) => s + (Number(i.wt_pct) || 0), 0) * 10000) / 10000
  const sumOk = Math.abs(total - 100) <= SUM_TOLERANCE
  const errors = sumOk ? [] : [`함량 합계 ${total} wt% — 100 ± ${SUM_TOLERANCE} wt%여야 함`]
  return { rows, total, sumOk, errors, ok: sumOk && rows.every(r => !r) }
}
