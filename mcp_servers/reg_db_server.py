"""MCP 서버 ② reg-db — 규제 목록 조회·판정·용어집.

- Tool: lookup_substance, judge_product, judge_all_products, glossary_lookup, list_regulations, regulation_overview
- Resource: regulation://{reg_id} — 규제 하나의 설명과 등재 물질 (문서처럼 읽는 정보)
- Prompt: briefing_procedure — 규제 브리핑 작성 표준 절차

판정은 app/domain/judge.py(코드)가 한다. 이 서버는 그 결과를 MCP로 노출할 뿐이다.
"""
try:
    from ._common import open_db
except ImportError:
    from _common import open_db

import re

from fastmcp import FastMCP

from app.domain.judge import judge_portfolio, judge_product

mcp = FastMCP(name="reg-db")
db = open_db()


@mcp.tool()
def list_regulations() -> list[dict]:
    """다루는 국내외 규제 목록(지역, 법, 목록명, 판정 방식, 기본 기준 함량, 의무, 출처)을 조회합니다."""
    return db.regulations()


@mcp.tool()
def regulation_overview(reg_id: str, recent: int = 2) -> dict:
    """규제 목록 하나의 개요: 법·목록명·의무·출처·확인일, 등재 물질 수, 최근 등재일별 물질 (등재일이 기록된 목록만).
    규제 설명("SVHC가 뭐야?")과 목록 조회("최근 추가된 물질은?")의 근거로 씁니다. reg_id 예: EU_REACH_SVHC"""
    reg = db.regulation(reg_id)
    if reg is None:
        raise ValueError(f"다루지 않는 규제입니다: {reg_id}")
    listings = db.listings_for_reg(reg_id)
    by_date: dict[str, list[dict]] = {}
    for lst in listings:                              # 근거 기록의 "2026-02-04 등재" (ECHA 후보 목록 등)
        for day in re.findall(r"(\d{4}-\d{2}-\d{2}) 등재", lst.get("evidence") or ""):
            by_date.setdefault(day, []).append({"cas": lst["cas"], "name": lst.get("name_ko") or lst["name_en"]})
    latest = sorted(by_date, reverse=True)[:recent]
    return {**reg, "listing_count": len(listings), "substance_count": len({x["cas"] for x in listings}),
            "verified_on": max((x.get("verified_on") or "" for x in listings), default="") or None,
            "recent_additions": [{"date": d, "substances": by_date[d][:12], "count": len(by_date[d])} for d in latest]}


@mcp.tool()
def lookup_substance(keyword: str) -> dict:
    """CAS 번호나 물질 이름(영문·한글 일부)으로 어떤 규제에 등재됐는지 조회합니다.
    keyword가 비어 있으면 물질 목록만 돌려줍니다 (이름 매칭용 — 수천 행의 등재 정보는 싣지 않음)."""
    substances = db.search_substance(keyword)
    if not keyword.strip():
        return {"keyword": keyword, "substances": substances, "listings": []}
    listings = db.listings_for_cas([s["cas"] for s in substances[:50]])
    return {"keyword": keyword, "substances": substances, "listings": listings}


@mcp.tool()
def judge_product_compliance(product_id: str) -> dict:
    """제품 하나를 규제 목록과 대조해 판정합니다 (코드 규칙: 수출 지역, 제품 형태, 함량 기준,
    합산 규칙, 불순물). 결과: exceeds(초과) / listed(등재) / review(확인 필요) / below(기준 이하),
    적용 제외 항목과 그 이유(skipped)도 함께 돌려줍니다."""
    return judge_product(db, product_id).to_dict()


@mcp.tool()
def judge_all_products() -> list[dict]:
    """전체 제품의 판정 요약(결과별 개수)을 조회합니다."""
    return [{"product_id": j.product_id, "product_name": j.product_name, **j.summary()}
            for j in judge_portfolio(db)]


@mcp.tool()
def glossary_lookup(text: str) -> list[dict]:
    """문장에 나오는 규제 용어(영어·중국어·일본어·한국어)를 찾아 정해진 한국어 표기와 설명을 돌려줍니다.
    번역할 때 용어를 통일하는 데 씁니다."""
    lowered = text.lower()
    return [g for g in db.glossary() if g["term"].lower() in lowered]


@mcp.resource("regulation://{reg_id}")
def regulation_card(reg_id: str) -> str:
    """규제 하나의 설명과 등재 물질 목록."""
    reg = db.regulation(reg_id)
    if reg is None:
        raise ValueError(f"등록되지 않은 규제입니다: {reg_id}")
    lines = [f"# {reg['law']} — {reg['list_name']} ({reg['region']})",
             f"- 관할: {reg['authority']}", f"- 적용 조건: {reg['applies_when']}",
             f"- 의무: {reg['obligation_ko']}", f"- 출처: {reg['source_url']}", "", "## 등재 물질"]
    for row in db.listings_for_reg(reg_id):
        lines.append(f"- {row['name_ko']} ({row['cas']}) {row['entry_ref'] or ''} "
                     f"{row['condition_ko'] or ''} [{row['status']}]".rstrip())
    return "\n".join(lines)


@mcp.prompt()
def briefing_procedure(period: str, focus: str = "") -> str:
    """국내외 규제 브리핑 작성 표준 절차."""
    return f"""다음 기간의 국내외 화학물질 규제 변화를 브리핑하세요.

## 대상
- 기간: {period}
- 관심 사항: {focus or "전체"}

## 절차 (순서대로)
1. 국내(법제처 행정규칙)·해외(미국 연방 관보) 변경 문서를 수집한다.
2. 문서에서 물질명과 CAS 번호를 뽑는다.
3. 회사 제품 배합과 CAS로 대조해 영향받는 제품을 찾는다.
4. 영향 제품은 judge_product_compliance로 판정한다. 판정은 코드 결과를 그대로 쓰고 바꾸지 않는다.
5. 외국어 원문은 용어집 표기로 한국어 요약하고, 숫자·CAS·날짜는 원문과 같아야 한다.
6. 할 일·기한·근거 원문 링크를 정리한다. 원문에 없는 의무를 만들지 않는다.
"""


if __name__ == "__main__":
    mcp.run(show_banner=False)
