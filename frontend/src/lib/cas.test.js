import { describe, expect, it } from 'vitest'
import { checkIngredients, isValidCas } from './cas.js'

describe('isValidCas — 서버(app/domain/cas.py)와 같은 결과', () => {
  it.each(['71-43-2', '79-01-6', '117-81-7', '7439-92-1', '1163-19-5'])('올바른 CAS %s', cas => {
    expect(isValidCas(cas)).toBe(true)
  })
  it.each(['71-43-3', '79-1-6', '71432', '', 'abc-de-f'])('틀린 CAS %s', cas => {
    expect(isValidCas(cas)).toBe(false)
  })
})

describe('checkIngredients', () => {
  const row = (cas, wt) => ({ cas, ingredient_name: 'x', role: '주원료', wt_pct: wt })

  it('행별 오류와 합계', () => {
    const r = checkIngredients([row('71-43-3', 50), row('79-01-6', 30), row('79-01-6', 20)])
    expect(r.rows).toEqual(['CAS 형식 또는 체크 디지트 오류', '', '같은 CAS가 이미 있음'])
    expect(r.total).toBe(100)
    expect(r.ok).toBe(false)
  })

  it('합계 100 ± 0.5만 허용 (소수 합산 오차는 반올림)', () => {
    expect(checkIngredients([row('79-01-6', 99.6), row('71-43-2', 0.1)]).sumOk).toBe(true)
    expect(checkIngredients([row('79-01-6', 70)]).errors[0]).toContain('70 wt%')
    expect(checkIngredients([row('79-01-6', 94.5), row('127-18-4', 0.8), row('56-23-5', 0.0005), row('71-43-2', 4.6995)]).ok).toBe(true)
  })
})
