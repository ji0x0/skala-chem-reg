"""Step 2 — 번역·요약 무결성 검사 (실제 관보 문장 기준)."""
from app.domain.integrity import check, extract_facts

SOURCE = ("EPA is proposing to extend certain compliance dates applicable to entities subject to the "
          "regulation of trichloroethylene (TCE, CAS 79-01-6) under TSCA until December 31, 2027. "
          "Comments must be received on or before November 13, 2026. "
          "The rule applies to products containing more than 0.1 percent TCE.")


def test_extract_facts_normalises_dates():
    facts = extract_facts(SOURCE)
    assert facts["cas"] == {"79-01-6"}
    assert facts["dates"] == {"2027-12-31", "2026-11-13"}
    assert "0.1" in facts["numbers"]
    assert "79" not in facts["numbers"]          # CAS·날짜의 숫자는 일반 숫자로 중복 집계하지 않는다


def test_correct_korean_translation_passes():
    ko = ("EPA는 TSCA에 따른 트리클로로에틸렌(TCE, CAS 79-01-6) 규제의 일부 준수 기한을 "
          "2027년 12월 31일까지 연장하는 안을 제안했다. 의견은 2026년 11월 13일까지 제출해야 한다. "
          "TCE를 0.1% 넘게 함유한 제품에 적용된다.")
    assert check(SOURCE, ko).ok


def test_changed_date_and_invented_cas_fail():
    bad = ("EPA는 TCE(CAS 79-01-6, 127-18-4) 준수 기한을 2028년 12월 31일까지 연장한다. "
           "의견 마감은 2026년 11월 13일. 0.1% 초과 제품에 적용.")
    report = check(SOURCE, bad)
    assert not report.ok
    assert report.extra_cas == ["127-18-4"]       # 원문에 없는 CAS를 지어냄
    assert report.missing_dates == ["2027-12-31"] and report.extra_dates == ["2028-12-31"]


def test_summary_may_omit_numbers_but_not_invent_them():
    short = "EPA는 TCE(CAS 79-01-6) 준수 기한을 2027년 12월 31일까지 연장 제안, 의견 마감 2026년 11월 13일."
    report = check(SOURCE, short)
    assert report.ok and report.missing_numbers == ["0.1"]     # 생략은 경고만
    invented = short + " 위반 시 벌금 50,000달러."
    assert check(SOURCE, invented).extra_numbers == ["50000"]  # 지어낸 숫자는 오류
