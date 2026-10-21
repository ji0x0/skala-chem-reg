"""규제 문서 본문에서 물질 언급 찾기 (이름 → CAS).

실제 규제 문서는 CAS 없이 물질 이름·약어만 쓰는 경우가 많다.
    예: 2026-10-14 EPA TCE 규칙 제안 — 본문에 "Trichloroethylene"·"TCE"는 있지만 79-01-6은 없다
그래서 CAS 추출과 함께, 규제 DB에 있는 물질의 영문 이름과 괄호 속 약어를 본문에서 찾아 CAS로 바꾼다.
"""
from __future__ import annotations

import re

from .cas import find_cas_numbers


def name_variants(name_en: str) -> list[str]:
    """'Bis(2-ethylhexyl) phthalate (DEHP)' → ['Bis(2-ethylhexyl) phthalate', 'DEHP']"""
    variants = []
    abbrevs = re.findall(r"\(([A-Z0-9][A-Za-z0-9-]{1,9})\)\s*$", name_en)
    base = re.sub(r"\s*\([A-Z0-9][A-Za-z0-9-]{1,9}\)\s*$", "", name_en).strip()
    if base:
        variants.append(base)
    variants.extend(abbrevs)
    return variants


ABBREVIATIONS = {"79-01-6": ["TCE"], "127-18-4": ["PCE", "Perchloroethylene"],
                 "75-09-2": ["DCM", "Methylene chloride"], "56-23-5": ["CTC"]}

# 일반 영단어와 겹치는 물질명 → 이름 대신 이 패턴으로만 인정 (예: 동사 "lead to"를 납으로 오인 방지)
AMBIGUOUS = {"7439-92-1": r"(?<![A-Za-z])[Ll]ead(?: \(Pb\)| compounds?| chromate| in PVC| stabili[sz]er)|\bPb\b"}


def find_substance_mentions(text: str, substances: list[dict]) -> list[dict]:
    """substances: [{"cas", "name_en", "name_ko"}] — 본문에 이름·약어·CAS로 언급된 물질과 횟수."""
    found = {}
    cas_in_text = set(find_cas_numbers(text))
    low = text.lower()                    # 수천 개 물질 이름 중 대부분은 본문에 없다 → 부분 문자열 검사로 먼저 거른다
    for s in substances:
        count, hits = 0, []
        if s["cas"] in AMBIGUOUS:
            n = len(re.findall(AMBIGUOUS[s["cas"]], text))
            if n:
                count, hits = n, ["(엄격 패턴)"]
            terms = []
        else:
            terms = name_variants(s["name_en"]) + ABBREVIATIONS.get(s["cas"], [])
        for term in terms:
            if term.lower() not in low:
                continue
            # 약어(대문자 2~5자)는 단어 경계와 대소문자를 엄격히, 이름은 대소문자 무시
            flags = 0 if re.fullmatch(r"[A-Z0-9-]{2,5}", term) else re.IGNORECASE
            n = len(re.findall(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, flags))
            if n:
                count += n
                hits.append(term)
        if s["cas"] in cas_in_text:
            count += 1
            hits.append(s["cas"])
        if count:
            found[s["cas"]] = {"cas": s["cas"], "name_en": s["name_en"], "name_ko": s["name_ko"],
                               "mentions": count, "matched_terms": hits}
    return sorted(found.values(), key=lambda m: -m["mentions"])


# ── 국내 문서: 한글 물질명 ─────────────────────────────────────────────────
# 한글 물질명 중 일상어와 겹치는 것 (예: 납 ↔ 납품·납기) → 한글 이름으로는 인정하지 않음 (CAS·고유번호로만)
KO_AMBIGUOUS = {"7439-92-1"}
# 이름 뒤에 붙어도 같은 물질로 보는 조사 ("트리클로로에틸렌을") — 그 밖의 한글이 이어지면 다른 물질
# (예: "톨루엔디이소시아네이트"의 "톨루엔"은 톨루엔이 아니다)
_KO_PARTICLES = "에서|으로|의|은|는|이|가|을|를|과|와|에|로|및|등|만|도"


def korean_names(name_ko: str) -> list[str]:
    """'디이소프로필아민; 디아이피에이(DIPA)' → ['디이소프로필아민', '디아이피에이']
    끝의 괄호 별칭만 떼고, 한글이 없는 조각은 버린다 ('N-(1,3-디메틸부틸…)'을 'N-'로 자르지 않게)."""
    names = []
    for alias in (name_ko or "").split(";"):
        alias = alias.strip()
        short = re.sub(r"\s*\([^()]*\)\s*$", "", alias).strip()
        for candidate in (short, alias):
            if len(candidate) >= 2 and re.search(r"[가-힣]", candidate):
                names.append(candidate)
                break
    return list(dict.fromkeys(names))


def find_korean_mentions(text: str, substances: list[dict]) -> list[dict]:
    """substances: [{"cas", "name_en", "name_ko"}] — 국내 문서 본문에 한글 이름으로 언급된 물질과 횟수."""
    found = []
    for s in substances:
        if s["cas"] in KO_AMBIGUOUS:
            continue
        count, hits = 0, []
        for name in korean_names(s.get("name_ko", "")):
            if name not in text:
                continue
            pattern = rf"(?<![가-힣A-Za-z0-9]){re.escape(name)}(?=$|[^가-힣A-Za-z0-9]|(?:{_KO_PARTICLES})(?![가-힣]))"
            n = len(re.findall(pattern, text))
            if n:
                count += n
                hits.append(name)
        if count:
            found.append({"cas": s["cas"], "name_en": s["name_en"], "name_ko": s["name_ko"],
                          "mentions": count, "matched_terms": hits})
    return found
