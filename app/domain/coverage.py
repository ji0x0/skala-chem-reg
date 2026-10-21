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


# ── Step 9: 제도·분야·시간 — 범위 판정 6축 중 지역 외의 축 ──────────────────────
# 다루는 제도: 질문 속 이름 → 규제 ID (설명·목록 조회의 대상)
REGIMES: dict[str, list[str]] = {
    "SVHC|고위험 우려물질|후보 목록|Candidate List": ["EU_REACH_SVHC"],
    "부속서 XVII|Annex XVII|XVII": ["EU_REACH_XVII"],
    "REACH|리치": ["EU_REACH_SVHC", "EU_REACH_XVII"],
    "CLP|조화된 분류|부속서 VI|Annex VI": ["EU_CLP_ANNEX_VI"],
    "TSCA|독성물질관리법|제6조": ["US_TSCA_S6"],
    "유해화학물질": ["KR_CCA_HAZ"],
    "제한물질": ["KR_CCA_RESTRICTED"],
    "금지물질": ["KR_CCA_PROHIBITED"],
    "화관법|화학물질관리법": ["KR_CCA_HAZ", "KR_CCA_RESTRICTED", "KR_CCA_PROHIBITED"],
    "관리대상\\s*유해물질|관리대상": ["KR_OSHA_MANAGED"],
    "특별관리물질": ["KR_OSHA_SPECIAL"],
    "산안법|산업안전보건": ["KR_OSHA_MANAGED", "KR_OSHA_SPECIAL"],
    "우선관리|우선 관리": ["CN_PRIORITY"],
    "화심법|화학물질심사규제법|제1종 특정화학물질|특정화학물질": ["JP_CSCL_C1"],
}
# 화학물질 규제지만 이 서비스의 목록에 없는 제도 (이름 → 질문 표현)
OUT_REGIMES: dict[str, str] = {
    "RoHS": r"RoHS|로스|전기전자 유해물질",
    "화장품 규제": r"화장품",
    "식품 접촉 재질 규제": r"식품 ?접촉|식품용 기구|기구 및 용기|FCM",
    "의약품·의료기기 규제": r"의약품|의료기기",
    "농약·비료 규제": r"농약|비료",
    "위험물 운송 규제": r"UN ?번호|위험물 운송|IMDG|ADR\b|운송 분류",
    "POPs(잔류성 유기오염물질 협약)": r"POPs|잔류성 유기오염물질|스톡홀름",
    "오존층 보호(몬트리올 의정서)": r"몬트리올|오존층",
    "미국 캘리포니아 Prop 65": r"Prop ?65|Proposition 65|캘리포니아",
    "화평법 등록": r"화평법 등록|K-?REACH 등록|등록 대상|등록 의무",
    "TSCA 인벤토리·신규물질 신고(PMN)": r"인벤토리|Inventory|PMN|신규물질 신고|신규 화학물질 신고",
    "미국 SNUR": r"SNUR|중요 신규 사용",
    "생활화학제품 안전기준": r"생활화학제품|안전확인대상",
}
# 분야 밖 요청 (O5 화학 일반 지식·안전 판단, O6 법률 판단, O9 보안·시스템)
GENERAL_KNOWLEDGE = r"끓는점|녹는점|인화점|증기압|물성|LD50|독성 수치|MSDS 써|SDS 써|MSDS 작성|SDS 작성|대체 ?물질|대체재|안전한가|안전해\?|안전할까"
LEGAL_ADVICE = r"벌금|과태료|처벌|법적 책임|소송|변호사|위반하면|법적으로 괜찮"
SECURITY = r"시스템 프롬프트|프롬프트 (?:보여|알려)|관리자 토큰|토큰 (?:알려|보여)|API ?키|비밀번호|인증키|다른 (?:사람|사용자)(?:의)? 대화"
# 규제 질문의 신호어 — 대상(제품·물질·제도)이 없는데 이것만 있으면 되묻기 (O10)
DOMAIN_WORDS = r"수출|규제|문제|해당|등재|변경|물질|제품|기준|허가|판정"

FEED_REGIONS = {"US", "KR"}                       # 변경 자동 수집 (미국 연방 관보, 국내 법제처 고시)
FEED_WINDOW = {"US": 30, "KR": 365}              # 변경 수집이 볼 수 있는 최대 기간 (일)


def regimes_in(text: str) -> tuple[list[str], list[str]]:
    """(다루는 규제 ID, 다루지 않는 제도 이름). 국내 '제한물질'은 EU 문맥('REACH 제한 물질')과 구분한다."""
    ids: list[str] = []
    for pattern, reg_ids in REGIMES.items():
        if re.search(pattern, text, re.IGNORECASE):
            ids += reg_ids
    if "EU_REACH_SVHC" in ids or "EU_REACH_XVII" in ids:      # "REACH 제한물질" → 국내 제한물질 아님
        ids = [i for i in ids if i != "KR_CCA_RESTRICTED"] if not re.search(r"화관법|국내", text) else ids
    out = [name for name, pattern in OUT_REGIMES.items() if re.search(pattern, text, re.IGNORECASE)]
    return list(dict.fromkeys(ids)), out


def years_in(text: str) -> list[int]:
    """질문 속 연도 (예: '2020년에 바뀐 규제')."""
    return [int(y) for y in re.findall(r"(?<!\d)(19\d{2}|20\d{2})\s*년", text)]
