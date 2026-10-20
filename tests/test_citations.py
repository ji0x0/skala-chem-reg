"""Step 3a — 근거 원문 추출: 원문은 코드가 자르고, 실제 출처에 있는 문장만 쓴다."""
from app.domain.citations import (extract_quotes, from_document, from_listing, official_dates,
                                  quote_in_source, split_sentences)

TEXT = """SUMMARY: The Environmental Protection Agency (EPA) is proposing to extend certain compliance
dates for trichloroethylene (TCE) under TSCA. You may be potentially affected by this rule.
Specifically, EPA is proposing to extend the compliance deadline from June 7, 2027, to December 31, 2027,
for processing TCE as an intermediate. Other text about HFC-134a production volumes follows here."""


def test_quotes_are_verbatim_and_prioritise_dates():
    quotes = extract_quotes(TEXT, ["Trichloroethylene", "TCE"])
    assert quotes[0].startswith("Specifically, EPA is proposing to extend the compliance deadline")
    assert all(quote_in_source(q, TEXT) for q in quotes)
    assert not any("HFC-134a production" in q for q in quotes)      # 물질이 없는 문장은 제외


def test_quote_not_in_source_is_detected():
    assert not quote_in_source("EPA bans TCE immediately.", TEXT)


def test_sentence_split_keeps_abbreviations():
    assert any("U.S. EPA" in s for s in split_sentences("The U.S. EPA proposed a rule today for TCE uses. Next."))


def test_citation_objects():
    listing = {"reg_id": "EU_REACH_XVII", "region": "EU", "law": "REACH", "list_name": "부속서 XVII 제한 물질",
               "cas": "117-81-7", "name_en": "DEHP", "entry_ref": "Entry 51",
               "condition_ko": "4종 합계 0.1 wt% 이하", "source_url": "https://echa.europa.eu", "status": "to_verify"}
    c = from_listing(1, listing)
    assert c.kind == "listing" and "Entry 51" in c.quote and c.status == "to_verify"
    doc = {"document_number": "2026-20964", "title": "TCE rule", "html_url": "https://x",
           "publication_date": "2026-10-14", "comments_close_on": "2026-11-13", "type": "Proposed Rule"}
    d = from_document(2, doc, "Specifically, EPA is proposing ...")
    assert d.as_of == "2026-10-14" and d.extra["comments_close_on"] == "2026-11-13"
    assert [x["label"] for x in official_dates(doc)] == ["게시일", "의견 제출 마감"]
