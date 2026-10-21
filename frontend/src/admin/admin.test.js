import { describe, expect, it } from 'vitest'
import { localTime, versionDate } from './api.js'

describe('localTime', () => {
  it('SQLite UTC 시각과 ISO 시각을 같은 순간으로 읽는다', () => {
    expect(localTime('2026-10-20 12:00:00')).toBe(localTime('2026-10-20T12:00:00+00:00'))
  })
  it('비어 있거나 읽을 수 없는 값은 그대로', () => {
    expect(localTime('')).toBe('')
    expect(localTime('어제')).toBe('어제')
  })
})

describe('versionDate', () => {
  it('통합본 CELEX의 기준일', () => {
    expect(versionDate('02008R1272-20270101')).toBe('2027-01-01')
    expect(versionDate(null)).toBe('')
  })
})
