// 판정 결과·데이터 상태의 한글 표기 — 모든 화면이 이 파일을 쓴다 (백엔드 app/domain/judge.py OUTCOME_KO와 같은 표기)
// 내부 값(exceeds 등)은 API·색상 클래스용으로 그대로 두고, 화면에는 한글만 보인다
export const OUTCOME_KO = {
  exceeds: '기준 초과',
  listed: '등재 해당',
  review: '확인 필요',
  below: '기준 이하',
  unresolved: '판정 불가',
}

export const OUTCOME_HELP = {
  exceeds: '함량이 규제 기준을 넘음 — 조치 필요',
  listed: '함량 기준 없이 등재 — 함유 자체로 해당',
  review: '불순물·기준 미확정 등 — 원문 확인 필요',
  below: '함량이 기준 이하',
  unresolved: '판정 도구 오류 — 영향 여부 미확인',
}

export const STATUS_KO = { official: '공식 확인', to_verify: '원본 확인 전' }

export const outcomeKo = o => OUTCOME_KO[o] ?? o
