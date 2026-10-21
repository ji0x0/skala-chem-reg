"""코드 채점기 — 답변 텍스트·근거·정답표만 보고 점수를 낸다 (LLM 없음, 결정론).

같은 함수로 Before·After를 채점한다. 파이프라인 내부 상태(판정 결과 등)는 보지 않는다
→ 사용자가 실제로 받는 답변만으로 공정하게 비교.

한계 (발표·보고서에 명시):
- 영향 제품은 "제품 ID가 나온 줄 중 부정 표현이 없는 줄"로 센다. 문장 구조가 특이하면 틀릴 수 있다
- 키워드 점수는 표현만 본다. 맞는 단어를 틀린 맥락에 써도 점수를 받는다 → LLM-as-Judge와 함께 본다
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.domain.citations import quote_in_source
from app.domain.integrity import check, extract_facts

PRODUCT_ID = re.compile(r"\bP\d{3}\b")
# 제품 ID가 나와도 "영향 없음·해당 없음·없는 제품"이면 지목한 것이 아니다
NEGATION = re.compile(r"영향\s*(이|은)?\s*없|해당\s*(사항)?\s*없|해당하지\s*않|무관|영향을\s*(주지|받지)\s*않|"
                      r"등록되지\s*않|없는\s*제품|찾을\s*수\s*없|존재하지\s*않|확인되지\s*않")
CITE_REF = re.compile(r"\[(\d{1,3})\](?!\()")
# 예시로 든 ID는 지목이 아니다: "(예: P003)", "P001 형식"
EXAMPLE_ID = re.compile(r"예(시)?\s*[:：]?\s*P\d{3}|P\d{3}\s*형식")


def flagged_products(text: str) -> set[str]:
    """답변이 '영향 있음'으로 지목한 제품 ID."""
    found = set()
    for line in text.splitlines():
        ids = PRODUCT_ID.findall(EXAMPLE_ID.sub(" ", line))
        if ids and not NEGATION.search(line):
            found.update(ids)
    return found


def prf(flagged: set[str], expected: set[str]) -> dict:
    tp, fp, fn = flagged & expected, flagged - expected, expected - flagged
    precision = len(tp) / len(flagged) if flagged else (1.0 if not expected else 0.0)
    recall = len(tp) / len(expected) if expected else 1.0
    return {"precision": round(precision, 3), "recall": round(recall, 3),
            "false_positives": sorted(fp), "missed": sorted(fn)}


def keyword_score(text: str, keywords: list[str]) -> float:
    """키워드 묶음마다 대안(|) 중 하나라도 있으면 1. 평균."""
    if not keywords:
        return 1.0
    low = text.lower()
    hits = sum(any(alt.lower() in low for alt in group.split("|")) for group in keywords)
    return round(hits / len(keywords), 3)


def forbidden_hits(text: str, forbidden: list[str]) -> list[str]:
    low = text.lower()
    return [w for w in forbidden if w.lower() in low]


def date_recall(text: str, required: list[str]) -> float:
    if not required:
        return 1.0
    found = extract_facts(text)["dates"]
    return round(len(set(required) & found) / len(required), 3)


def invented_facts(text: str, corpus: str, reference: str = "") -> dict:
    """답변의 CAS·날짜 중 입력 자료(관보 본문·규제 DB·제품 배합) 어디에도 없는 것 = 지어낸 사실."""
    r = check(corpus, text, reference)
    return {"cas": r.extra_cas, "dates": r.extra_dates}


def citation_check(answer: str, citations: list[dict], documents: dict[str, str],
                   listings: set[tuple[str, str]]) -> dict:
    """근거 검증을 세 가지로 나눈다.
    ① verified: 근거 원문이 실제 출처에 있는가 (문서 근거는 본문 문자열, 목록 근거는 실제 등재 행)
    ② used: 답변 본문이 유효한 근거 번호 [n]을 실제로 쓰는가 (근거 목록만 붙이고 본문에서 안 쓰면 0)
    ③ 그 근거가 연결된 주장을 뒷받침하는가 — 코드로 판단할 수 없어 대표 문항을 사람이 검토한다"""
    verified = 0
    for c in citations:
        if c.get("kind") == "document":
            verified += quote_in_source(c.get("quote", ""), documents.get(c.get("source_id"), ""))
        elif c.get("kind") == "listing":
            cas = re.findall(r"\b\d{2,7}-\d{2}-\d\b", c.get("quote", ""))
            verified += any((c.get("source_id"), x) in listings for x in cas)
    ids = {str(c.get("id")) for c in citations}
    refs = set(CITE_REF.findall(answer))
    return {"count": len(citations), "verified": verified,
            "verified_rate": round(verified / len(citations), 3) if citations else None,
            "used": len(refs & ids), "unknown_refs": sorted(refs - ids, key=int)}


@dataclass
class Score:
    id: str
    category: str
    route_ok: bool | None
    products: dict
    keyword: float
    dates: float
    invented: dict
    forbidden: list[str]
    citations: dict
    cite_ok: bool
    judge: dict = field(default_factory=dict)        # LLM-as-Judge (선택)

    def to_dict(self) -> dict:
        return asdict(self)


def score_answer(item: dict, answer: str, citations: list[dict], route: str | None,
                 corpus: dict) -> Score:
    """item: questions.json의 질문 하나. corpus: load_corpus() 결과."""
    exp = item["expect"]
    cites = citation_check(answer, citations, corpus["documents"], corpus["listings"])
    must = exp.get("must_cite", False)
    return Score(
        id=item["id"], category=item["category"],
        route_ok=(route == exp["route"]) if route is not None else None,
        products=prf(flagged_products(answer), set(exp.get("impacted_products", []))),
        keyword=keyword_score(answer, exp.get("keywords", [])),
        dates=date_recall(answer, exp.get("required_dates", [])),
        invented=invented_facts(answer, corpus["text"], corpus["reference"]),
        forbidden=forbidden_hits(answer, exp.get("forbidden", [])),
        citations=cites,
        # 근거 필수 문항: 근거가 있고 전부 원문 대조 통과 + 본문이 그 근거 번호를 실제로 씀 + 없는 번호를 쓰지 않음
        cite_ok=(not must or (cites["count"] > 0 and cites["verified"] == cites["count"] and cites["used"] > 0))
                and not cites["unknown_refs"],
    )
