"""MCP 서버 ③ reg-feed — 국내외 규제 변경 원문 조회 (Tool).

- 미국: 연방 관보(Federal Register) API — 공개, 키 불필요
- 국내: 법제처 국가법령정보 Open API(행정규칙) — LAW_API_OC 설정 시에만 동작

실시간 호출이 실패하면 data/feeds/ 스냅샷으로 대신 답하고, 결과에 source(live/snapshot)를 표시한다.
규제 판단에서는 "언제, 어디서 받은 데이터인지"가 중요하기 때문이다.
"""
try:
    from ._common import open_db
except ImportError:
    from _common import open_db

import html
import json
import re
from datetime import date, timedelta

import httpx
from fastmcp import FastMCP

from app.core.config import get_settings
from app.domain.cas import find_cas_numbers
from app.domain.mentions import find_substance_mentions

mcp = FastMCP(name="reg-feed")
settings = get_settings()
db = open_db()
SNAPSHOT = settings.feeds_dir / "federal_register_tsca.json"
FIELDS = ["document_number", "title", "type", "abstract", "publication_date", "html_url",
          "raw_text_url", "effective_on", "comments_close_on"]


def _plain_text(raw: str) -> str:
    """관보 텍스트 본문은 <html><pre>로 감싸져 온다 → 태그를 벗기고 HTML 엔티티를 푼다."""
    return html.unescape(re.sub(r"<[^>]+>", "", raw))


def _snapshot_documents() -> list[dict]:
    if not SNAPSHOT.exists():
        return []
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))["documents"]


@mcp.tool()
def search_federal_register(term: str = "TSCA", days: int = 30, agency: str = "environmental-protection-agency",
                            limit: int = 20) -> dict:
    """미국 연방 관보에서 최근 문서를 검색합니다 (기본: 최근 30일 EPA TSCA).
    결과마다 문서 번호·제목·종류(Rule/Proposed Rule/Notice)·게시일·요약·원문 링크·의견 마감일을 줍니다."""
    params = [("conditions[agencies][]", agency), ("conditions[term]", term),
              ("conditions[publication_date][gte]", (date.today() - timedelta(days=days)).isoformat()),
              ("order", "newest"), ("per_page", str(limit))] + [("fields[]", f) for f in FIELDS]
    try:
        resp = httpx.get(f"{settings.federal_register_api}/documents.json", params=params,
                         timeout=settings.http_timeout_s)
        resp.raise_for_status()
        return {"source": "live", "query": {"term": term, "days": days, "agency": agency},
                "documents": resp.json().get("results", [])}
    except httpx.HTTPError as exc:
        return {"source": "snapshot", "warning": f"실시간 조회 실패({type(exc).__name__}) — 저장된 스냅샷 사용",
                "documents": _snapshot_documents()[:limit]}


@mcp.tool()
def get_federal_register_document(document_number: str, max_chars: int = 12000) -> dict:
    """관보 문서 하나의 상세 정보와 본문(앞부분)을 가져오고, 본문에 언급된 물질을 찾습니다.
    - cas_numbers: 본문에 CAS 번호로 적힌 물질
    - substance_mentions: 규제 DB 물질의 이름·약어로 언급된 물질 (CAS가 없는 문서가 많아서 필요)
    document_number 예: 2026-20964"""
    try:
        meta = httpx.get(f"{settings.federal_register_api}/documents/{document_number}.json",
                         params=[("fields[]", f) for f in FIELDS], timeout=settings.http_timeout_s)
        meta.raise_for_status()
        doc, source = meta.json(), "live"
    except httpx.HTTPError:
        doc = next((d for d in _snapshot_documents() if d["document_number"] == document_number), None)
        if doc is None:
            raise ValueError(f"문서를 찾을 수 없습니다: {document_number}")
        source = "snapshot"

    text, text_source = f"{doc.get('title', '')}\n{doc.get('abstract') or ''}", "abstract"
    if source == "live" and doc.get("raw_text_url"):
        try:
            raw = httpx.get(doc["raw_text_url"], timeout=settings.http_timeout_s)
            raw.raise_for_status()
            text, text_source = _plain_text(raw.text), "full_text"
        except httpx.HTTPError:
            pass                      # 본문을 못 받으면 제목·요약만 쓴다
    substances = db.search_substance("")       # 규제 DB의 전체 물질
    return {"source": source, "text_source": text_source, **{k: doc.get(k) for k in FIELDS},
            "text": text[:max_chars], "text_truncated": len(text) > max_chars,
            "cas_numbers": find_cas_numbers(text),
            "substance_mentions": find_substance_mentions(text, substances)}


@mcp.tool()
def search_kr_admin_rules(query: str, limit: int = 10) -> dict:
    """법제처 국가법령정보 Open API로 국내 행정규칙(고시 등)을 검색합니다. 예: '유해화학물질', '유독물질'.
    LAW_API_OC가 설정되지 않았으면 비활성 상태임을 알려 줍니다."""
    if not settings.law_api_oc:
        return {"source": "disabled", "documents": [],
                "message": "LAW_API_OC 미설정 — open.law.go.kr에서 Open API를 신청하고 호출 서버 IP를 등록한 뒤 .env에 넣으세요."}
    # 엔드포인트·파라미터는 법제처 Open API 가이드 기준 (키 발급 후 실제 응답으로 검증 필요)
    resp = httpx.get("https://www.law.go.kr/DRF/lawSearch.do",
                     params={"OC": settings.law_api_oc, "target": "admrul", "type": "JSON",
                             "query": query, "display": limit},
                     timeout=settings.http_timeout_s)
    resp.raise_for_status()
    return {"source": "live", "query": query, "raw": resp.json()}


if __name__ == "__main__":
    mcp.run(show_banner=False)
