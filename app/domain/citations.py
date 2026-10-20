"""근거(citation) — 답변에 쓴 근거의 원문 문장과 출처.

원칙: 원문 문장은 LLM이 쓰지 않는다. LLM이 "인용"하면 그럴듯하게 지어낼 수 있기 때문이다.
- 문서 근거: 코드가 문서 본문에서 물질·날짜·숫자가 나온 문장을 잘라 온다 (extract_quotes)
- 목록 근거: 규제 DB 등재 행 자체를 원문으로 쓴다 (from_listing)
LLM은 이 문장들을 받아 번역·요약만 하고, 화면은 원문·번역·출처·기준일을 함께 보여 준다.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# 문장 나누기: 마침표·물음표·느낌표 뒤 공백 또는 빈 줄.
# "U.S."처럼 한 글자 약어 뒤에서는 끊지 않고, "TSCA."처럼 대문자 두 글자 이상 뒤에서는 끊는다
_SENTENCE_END = re.compile(r"(?:(?<=[a-z0-9\)][.!?])|(?<=[A-Z]{2}[.!?]))\s+(?=[A-Z(\"])|\n\s*\n")


@dataclass
class Citation:
    id: int
    kind: str                  # "document"(관보 등 원문) | "listing"(규제 DB 등재)
    source_id: str             # 문서 번호 또는 규제 ID
    title: str
    quote: str                 # 원문 문장 그대로
    url: str
    as_of: str                 # 게시일 또는 데이터 기준일
    status: str = "official"   # 목록 근거는 데이터 검증 상태(to_verify/official)
    translation_ko: str = ""   # LLM 번역 (무결성 검사 통과분만)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def label(self) -> str:
        return f"[{self.id}] {self.title} — {self.quote[:200]}"


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    parts = _SENTENCE_END.split(text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p and len(p.strip()) > 20]


def extract_quotes(text: str, terms: list[str], max_quotes: int = 6, max_len: int = 500) -> list[str]:
    """terms(물질 이름·약어·CAS) 중 하나라도 들어간 문장을 원문 그대로 뽑는다.
    날짜·기한·마감이 함께 있는 문장을 먼저 고른다 (담당자에게 가장 중요한 정보)."""
    patterns = [re.compile(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![A-Za-z0-9])", re.IGNORECASE)
                for t in terms if t]
    has_date = re.compile(r"\b(19|20)\d{2}\b")
    has_duty = re.compile(r"deadline|compliance date|comment|effective|prohibit|restrict|ban|until",
                          re.IGNORECASE)
    picked = []
    for sentence in split_sentences(text):
        if any(p.search(sentence) for p in patterns):
            picked.append(sentence[:max_len])
    # 구체적인 날짜가 있는 문장 → 의무 관련 단어만 있는 문장 → 나머지 (같은 순위는 원문 순서 유지)
    picked.sort(key=lambda s: 0 if has_date.search(s) else 1 if has_duty.search(s) else 2)
    return list(dict.fromkeys(picked))[:max_quotes]


def quote_in_source(quote: str, source: str) -> bool:
    """원문 문장이 출처 본문에 실제로 있는지 (공백 차이는 무시)."""
    norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    return norm(quote) in norm(source)


def from_listing(cid: int, listing: dict) -> Citation:
    """규제 DB 등재 행 → 근거. 원문은 등재 정보 자체이고, 출처는 그 목록의 공식 URL이다."""
    parts = [f"{listing.get('law', '')} {listing.get('list_name', '')}".strip(),
             f"{listing['name_en']} (CAS {listing['cas']})"]
    if listing.get("entry_ref"):
        parts.append(listing["entry_ref"])
    if listing.get("condition_ko"):
        parts.append(listing["condition_ko"])
    return Citation(id=cid, kind="listing", source_id=listing["reg_id"],
                    title=f"{listing.get('region', '')} {listing.get('list_name', listing['reg_id'])}",
                    quote=" · ".join(parts), url=listing.get("source_url", ""),
                    as_of="규제 DB", status=listing.get("status", "to_verify"))


def from_document(cid: int, doc: dict, quote: str) -> Citation:
    return Citation(id=cid, kind="document", source_id=doc.get("document_number", ""),
                    title=doc.get("title", ""), quote=quote, url=doc.get("html_url", ""),
                    as_of=doc.get("publication_date", ""), status="official",
                    extra={"type": doc.get("type"), "comments_close_on": doc.get("comments_close_on"),
                           "source": doc.get("source")})


def official_dates(doc: dict) -> list[dict]:
    """관보 API가 주는 공식 날짜 — LLM에게 찾게 하지 않고 코드가 그대로 쓴다."""
    labels = [("publication_date", "게시일"), ("comments_close_on", "의견 제출 마감"),
              ("effective_on", "시행일")]
    return [{"label": label, "date": doc[key], "source": "관보 API"}
            for key, label in labels if doc.get(key)]
