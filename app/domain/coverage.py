"""이 서비스가 다루는 지역 — 질문에 나온 국가가 규제 DB 범위 안인지 코드로 판별한다.

규제 DB에 없는 국가(예: 태국)를 물으면 판정 0건이 "문제 없음 → 수출 가능"으로 잘못 읽힌다.
판정 0건의 뜻은 "다루는 지역의 등재 목록 기준 해당 없음"뿐이다. 다루지 않는 국가는 "확인할 수 없음"으로 안내한다.
"""
from __future__ import annotations

import re

SUPPORTED = {"KR": "국내", "US": "미국", "EU": "EU", "CN": "중국", "JP": "일본"}
SUPPORTED_TEXT = "국내·미국·EU·중국·일본"

# 국가·지역 이름 → 지역 코드. EU 회원국은 EU 규제(REACH·CLP)로 확인한다.
_EU_MEMBERS = ["독일", "프랑스", "이탈리아", "스페인", "네덜란드", "벨기에", "폴란드", "오스트리아", "스웨덴",
               "덴마크", "핀란드", "아일랜드", "포르투갈", "체코", "헝가리", "그리스", "루마니아", "유럽",
               "Germany", "France", "Italy", "Spain", "Netherlands", "Poland", "Europe"]
_NAMES = {
    "KR": ["한국", "국내", "대한민국", "Korea", "화관법", "화학물질관리법", "산안법", "산업안전보건", "법제처", "화평법"],
    "US": ["미국", "USA", "U.S.", "EPA", "America", "TSCA", "관보"],
    "EU": ["EU", "유럽연합", "REACH", "ECHA", "CLP", "SVHC", *_EU_MEMBERS],
    "CN": ["중국", "China"],
    "JP": ["일본", "Japan"],
}
# 자주 묻지만 규제 DB에 없는 국가 (영국은 EU 탈퇴 후 UK REACH를 따로 운영 → EU 목록으로 대신할 수 없음)
UNSUPPORTED = ["태국", "베트남", "인도네시아", "말레이시아", "필리핀", "싱가포르", "대만", "인도", "호주", "뉴질랜드",
               "캐나다", "멕시코", "브라질", "칠레", "아르헨티나", "영국", "스위스", "노르웨이", "튀르키예", "터키",
               "러시아", "사우디", "아랍에미리트", "UAE", "이스라엘", "남아공", "이집트", "홍콩",
               "Thailand", "Vietnam", "Indonesia", "Malaysia", "Taiwan", "India", "Australia", "Canada",
               "Mexico", "Brazil", "UK", "United Kingdom", "Switzerland", "Turkey", "Russia"]


def _found(name: str, text: str) -> bool:
    if re.fullmatch(r"[A-Za-z.]+", name):            # 영문: 단어 경계 (예: "UK"가 "UKRAINE"에 걸리지 않게)
        return re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", text) is not None
    if name == "인도":                                # "인도네시아"·"인도하다"와 구분
        return re.search(r"인도(?!네시아|하|해|했|된|되)", text) is not None
    return name in text


def regions_in(text: str) -> tuple[list[str], list[str]]:
    """(다루는 지역 코드, 다루지 않는 국가 이름) — 질문에 나온 순서는 무시하고 정렬."""
    own = re.sub(r"K-REACH", "화평법", re.sub(r"UK[ -]?REACH", " ", text))   # 영국·한국 REACH는 EU REACH가 아니다
    supported = sorted({code for code, names in _NAMES.items() if any(_found(n, own) for n in names)})
    unsupported = [n for n in UNSUPPORTED if _found(n, text)]
    return supported, list(dict.fromkeys(unsupported))


def unsupported_notice(names: list[str]) -> str:
    """답변·브리핑 맨 앞에 코드가 붙이는 안내 (LLM이 빠뜨리거나 바꾸지 못하게)."""
    return (f"> ⚠️ **{', '.join(names)}** 규제는 이 서비스의 규제 DB에 없어 **확인할 수 없습니다** "
            f"(다루는 지역: {SUPPORTED_TEXT}). 아래 판정은 다루는 지역의 등재 목록 기준이며, "
            f"{', '.join(names)} 수출 가능 여부를 뜻하지 않습니다.")
