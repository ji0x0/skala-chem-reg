"""번역·요약 무결성 검사 — 원문과 결과문의 핵심 사실(CAS·날짜·숫자)이 같은지 코드로 대조한다.

규제 문서에서 틀리면 안 되는 것은 문장의 자연스러움이 아니라 사실이다.
    원문:  "... compliance dates ... until December 31, 2027"
    번역:  "... 준수 기한을 2028년 12월 31일까지 연장"      ← 날짜가 바뀜 → 실패

판정 기준
- 번역문에만 있는 CAS·날짜·숫자 (지어냄)         → 오류
- 원문의 CAS·날짜가 번역문에 없음 (누락)           → 오류
- 원문의 일반 숫자가 번역문에 없음                 → 경고 (요약에서는 생략될 수 있음)
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from .cas import find_cas_numbers

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], start=1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})

DATE_PATTERNS = [
    # 2026-10-14, 2026.10.14, 2026/10/14
    (re.compile(r"(?<!\d)(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?!\d)"), ("y", "m", "d")),
    # 2027년 12월 31일
    (re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"), ("y", "m", "d")),
    # December 31, 2027 / Dec. 31, 2027
    (re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})"), ("mon", "d", "y")),
    # 31 December 2027
    (re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})"), ("d", "mon", "y")),
]
NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")


@dataclass
class IntegrityReport:
    missing_cas: list[str] = field(default_factory=list)
    extra_cas: list[str] = field(default_factory=list)
    missing_dates: list[str] = field(default_factory=list)
    extra_dates: list[str] = field(default_factory=list)
    missing_numbers: list[str] = field(default_factory=list)
    extra_numbers: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing_cas or self.extra_cas or self.missing_dates or self.extra_dates
                    or self.extra_numbers)

    def to_dict(self) -> dict:
        return {**asdict(self), "ok": self.ok}


def _dates(text: str) -> tuple[set[str], str]:
    """날짜를 ISO 형식으로 뽑고, 날짜 부분을 지운 텍스트도 돌려준다 (숫자 검사에서 중복 방지)."""
    found: set[str] = set()
    for pattern, order in DATE_PATTERNS:
        def repl(m: re.Match) -> str:
            parts = dict(zip(order, m.groups()))
            month = MONTHS.get(parts["mon"].lower()) if "mon" in parts else int(parts["m"])
            try:
                found.add(date(int(parts["y"]), month, int(parts["d"])).isoformat())
            except (TypeError, ValueError):
                return m.group(0)       # 날짜가 아니면 그대로 둔다
            return " "
        text = pattern.sub(repl, text)
    return found, text


def _numbers(text: str) -> set[str]:
    out = set()
    for n in NUMBER.findall(text):
        value = float(n.replace(",", ""))
        out.add(f"{value:g}")
    return out


def extract_facts(text: str) -> dict[str, set[str]]:
    cas = set(find_cas_numbers(text))
    rest = text
    for c in cas:
        rest = rest.replace(c, " ")
    dates, rest = _dates(rest)
    return {"cas": cas, "dates": dates, "numbers": _numbers(rest)}


def check(source: str, result: str) -> IntegrityReport:
    src, out = extract_facts(source), extract_facts(result)
    return IntegrityReport(
        missing_cas=sorted(src["cas"] - out["cas"]),
        extra_cas=sorted(out["cas"] - src["cas"]),
        missing_dates=sorted(src["dates"] - out["dates"]),
        extra_dates=sorted(out["dates"] - src["dates"]),
        missing_numbers=sorted(src["numbers"] - out["numbers"], key=float),
        extra_numbers=sorted(out["numbers"] - src["numbers"], key=float),
    )
