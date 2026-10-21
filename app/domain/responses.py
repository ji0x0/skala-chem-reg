"""범위 밖·확인 불가 안내 문구 — LLM이 아니라 코드가 만든다 (빠뜨리거나 바꾸지 못하게).

모든 문구는 네 부분: ① 무엇을 확인할 수 없는지 ② 왜 (다루는 범위) ③ 대신 할 수 있는 것 ④ (있으면) 공식 출처.
지어낸 기관·링크·사실은 쓰지 않는다. 설계: docs/routing-architecture.md 4절.
"""
from __future__ import annotations

from .coverage import FEED_WINDOW, SUPPORTED, SUPPORTED_TEXT

REGION_KO = {code: name for code, name in SUPPORTED.items()}


def unsupported_regimes(names: list[str], covered_lists: str) -> str:
    """O2 — 화학물질 규제지만 목록에 없는 제도."""
    return (f"> ⚠️ **{', '.join(names)}**는 이 서비스가 다루는 규제 목록에 없어 **확인할 수 없습니다**. "
            f"다루는 목록: {covered_lists}. 같은 물질이 이 목록들에 등재돼 있으면 그 정보는 알려 드릴 수 있습니다.")


def out_of_window(years: list[int], verified_on: str) -> str:
    """O3 — 수집하지 않는 기간."""
    return (f"> ⚠️ {', '.join(f'{y}년' for y in years)}의 규제 변경은 수집하지 않아 **확인할 수 없습니다** "
            f"(변경 수집: 미국 최근 {FEED_WINDOW['US']}일 · 국내 최근 {FEED_WINDOW['KR'] // 365}년, "
            f"규제 목록 확인일 {verified_on}).")


def no_feed(regions: list[str], verified_on: str) -> str:
    """O4 — 변경 자동 수집기가 없는 지역."""
    names = ", ".join(REGION_KO.get(r, r) for r in regions)
    return (f"> ⚠️ **{names}** 규제 변경은 자동 수집하지 않아 실시간 변경은 **확인할 수 없습니다** "
            f"(변경 수집: 미국 연방 관보 · 국내 법제처 고시). 아래는 규제 DB(확인일 {verified_on}) 기준 정보입니다.")


def general_knowledge() -> str:
    """O5 — 물성·독성 수치·대체 물질 추천·안전 판단."""
    return ("> ⚠️ 물성·독성 수치, MSDS 작성, 대체 물질 추천, 안전 여부 판단은 이 서비스의 범위 밖이라 **답할 수 없습니다**. "
            "규제 DB의 등재 정보와 조화된 분류(CLP)는 알려 드릴 수 있습니다.")


def legal_advice() -> str:
    """O6 — 벌금·법적 책임 같은 법률 판단."""
    return ("> ⚠️ 벌금·처벌·법적 책임 판단은 법률 자문이라 **답할 수 없습니다**. "
            "규제 목록의 의무와 공식 출처까지만 안내합니다. 최종 판단은 담당자·법무 검토로 해 주세요.")


def security() -> str:
    """O9 — 시스템 설정·인증 정보·다른 사용자 대화."""
    return "시스템 설정, 인증 정보(키·토큰), 다른 사용자의 대화는 알려 드릴 수 없습니다."


def off_topic() -> str:
    """O8 — 서비스와 무관한 요청."""
    return (f"이 서비스는 화학물질 규제({SUPPORTED_TEXT})를 다룹니다. 예를 들어 이렇게 물어보세요:\n"
            "- 트리클로로에틸렌은 어떤 규제에 해당해?\n- P002 규제 문제 있어?\n"
            "- 이번 주 미국 EPA 규제 변경 브리핑해줘\n- SVHC가 뭐야?")


def clarify(missing: list[str]) -> str:
    """O10 — 무엇을 확인할지 정보가 부족한 질문."""
    return (f"어떤 {' · '.join(missing)}을(를) 확인할까요? 예: \"P003 미국 수출 문제 있어?\", "
            "\"트리클로로에틸렌은 어떤 규제에 해당해?\", \"최근 국내 화학물질 규제 변경 브리핑해줘\"")


def not_listed(names: list[str]) -> str:
    """O7 — 목록에 등재가 없는 물질 (규제가 없다는 뜻이 아님)."""
    return (f"> ℹ️ **{', '.join(names)}**는 다루는 목록에 등재가 없습니다. "
            "다른 국가·제도의 규제가 없다는 뜻은 아닙니다.")
