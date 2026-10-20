// SSE 진행 이벤트 → 화면에 한 줄로 보여 줄 문구 (R12 진행 상황 UI)
// 돌려주는 값: { text, tone } — tone: 'run'(진행) | 'ok' | 'warn' | 'fail' / null이면 표시하지 않음

const ROUTES = { chat: '일반 대화', lookup: '규제 조회·판정', briefing: '규제 변경 브리핑' }

export function describe(event, data) {
  if (event === 'tool_call_start') return { text: `🔧 ${data.tool} 호출`, tone: 'run', tool: data.tool }
  if (event === 'tool_call_end') {
    const ms = data.latency_ms != null ? ` · ${(data.latency_ms / 1000).toFixed(1)}초` : ''
    return { text: `🔧 ${data.tool} ${data.ok ? '완료' : '실패'}${data.summary ? ` — ${data.summary}` : ''}${ms}`,
      tone: data.ok ? 'ok' : 'fail', tool: data.tool }
  }
  if (event !== 'progress') return null
  const d = data.data ?? {}
  switch (data.kind) {
    case 'node_start':
      return { text: d.label ?? d.node, tone: 'run', step: true }
    case 'route':
      return { text: `질문 유형: ${ROUTES[d.route] ?? d.route}`, tone: 'ok' }
    case 'plan':
      if (d.mode === 'baseline') return { text: `LLM 단독 모드 — 문서 ${d.documents}건`, tone: 'ok' }
      if (d.days != null) {
        return { text: `계획: 최근 ${d.days}일 · 지역 ${(d.regions ?? []).join(', ') || '-'}` +
          (d.products?.length ? ` · 제품 ${d.products.join(', ')}` : ''), tone: 'ok' }
      }
      return { text: `대상: 물질 ${d.substances?.length ?? 0}개 · 제품 ${(d.products ?? []).join(', ') || '-'}`, tone: 'ok' }
    case 'agent_start':
      return { text: `▶ ${d.label}${d.purpose ? ` — ${d.purpose}` : ''}`, tone: 'run' }
    case 'agent_end':
      return { text: `■ ${d.agent}: ${d.summary || (d.ok ? '완료' : '실패')}`, tone: d.ok ? 'ok' : 'warn' }
    case 'review':
      return { text: d.sufficient ? `수집 충분 — 문서 ${d.documents}건` : `재조사: ${(d.reasons ?? []).join(' / ')}`,
        tone: d.sufficient ? 'ok' : 'warn' }
    case 'summary': {
      const invented = Object.keys(d.invented ?? {}).length
      return { text: `요약: ${d.title_ko} · 근거 ${d.citations}개 (번역 ${d.translations_kept}개)` +
        (invented ? ' · ⚠ 지어낸 사실 감지' : ''), tone: invented ? 'warn' : 'ok' }
    }
    case 'impact':
      return { text: `영향 제품: ${(d.products ?? []).join(', ') || '없음'} · 판정 ${d.findings}건`, tone: 'ok' }
    case 'draft_start':
      return { text: d.attempt > 1 ? `브리핑 다시 작성 (${d.attempt}회차)` : '브리핑 작성 시작', tone: 'run' }
    case 'guard': {
      const problems = Object.keys(d.invented ?? {}).length + (d.unknown_citations?.length ?? 0) +
        (d.missing_sections?.length ?? 0) + (d.uncited ? 1 : 0)
      return { text: problems ? `사실·근거 검사: 문제 ${problems}건` : '사실·근거 검사 통과', tone: problems ? 'warn' : 'ok' }
    }
    case 'validation': {
      const s = d.scores ?? {}
      const scores = Object.keys(s).length ? ` (${Object.values(s).join('/')})` : ''
      return { text: `품질 검토 ${d.attempt}회차: ${d.passed ? '합격' : '보완 필요'}${scores}`, tone: d.passed ? 'ok' : 'warn' }
    }
    default:
      return { text: data.kind, tone: 'run' }
  }
}
