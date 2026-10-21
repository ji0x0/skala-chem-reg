"""MCP 서버 ③ reg-feed — 국내외 규제 변경 원문 조회 (Tool).

- 미국: 연방 관보(Federal Register) API — 공개, 키 불필요
- 국내: 법제처 국가법령정보 Open API(행정규칙) — LAW_API_OC 설정 시에만 동작

실시간 호출이 실패하면 data/feeds/ 스냅샷으로 대신 답하고, 결과에 source(live/snapshot)를 표시한다.
규제 판단에서는 "언제, 어디서 받은 데이터인지"가 중요하기 때문이다.
FEED_MODE=snapshot이면 실시간 호출 없이 스냅샷 목록과 저장된 본문(data/feeds/fulltext/)만 쓴다
→ 평가(Before/After)를 같은 입력으로 반복할 수 있다.
"""
try:
    from ._common import open_db
except ImportError:
    from _common import open_db

import html
import json
import re
import threading
import time
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
CACHE_DIR = settings.feeds_dir / "cache"          # 관보 본문 캐시 (게시 후 바뀌지 않으므로 안전)
FULLTEXT_DIR = settings.feeds_dir / "fulltext"    # 스냅샷 문서의 본문 (저장소에 포함 — 평가 입력 고정)
_fetch_lock = threading.Lock()                    # 본문은 한 번에 하나씩 받는다 (요청 과다 제한 방지)
FIELDS = ["document_number", "title", "type", "abstract", "publication_date", "html_url",
          "raw_text_url", "effective_on", "comments_close_on"]


def _plain_text(raw: str) -> str:
    """관보 텍스트 본문은 <html><pre>로 감싸져 온다 → 태그를 벗기고 HTML 엔티티를 푼다."""
    return html.unescape(re.sub(r"<[^>]+>", "", raw))


def _fetch_full_text(document_number: str, url: str) -> tuple[str | None, str | None]:
    """본문을 캐시에서 읽거나 받아 온다. (본문, 경고) — 실패하면 본문 None과 이유를 돌려준다."""
    for saved in (FULLTEXT_DIR / f"{document_number}.txt", CACHE_DIR / f"{document_number}.txt"):
        if saved.exists():
            return saved.read_text(encoding="utf-8"), None
    if settings.feed_mode == "snapshot":
        return None, "스냅샷 모드 — 저장된 본문 없음, 제목·요약만 사용"
    with _fetch_lock:
        for attempt in (1, 2):
            try:
                resp = httpx.get(url, timeout=settings.http_timeout_s)
            except httpx.HTTPError as exc:
                return None, f"본문 조회 실패({type(exc).__name__}) — 제목·요약만 사용"
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", "0") or 0)
                if attempt == 1 and 0 < wait <= 5:
                    time.sleep(wait)
                    continue
                return None, "본문 조회 제한(429 Too Many Requests) — 제목·요약만 사용"
            if resp.status_code != 200:
                return None, f"본문 조회 실패(HTTP {resp.status_code}) — 제목·요약만 사용"
            text = _plain_text(resp.text)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            (CACHE_DIR / f"{document_number}.txt").write_text(text, encoding="utf-8")
            return text, None
    return None, "본문 조회 실패 — 제목·요약만 사용"


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
    if settings.feed_mode == "snapshot":
        return {"source": "snapshot", "warning": "스냅샷 모드 — 저장된 관보 목록 사용 (기간 조건 무시)",
                "documents": _snapshot_documents()[:limit]}
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
        if settings.feed_mode == "snapshot":
            raise httpx.TransportError("snapshot mode")
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
    warning = None
    if doc.get("raw_text_url"):
        full, warning = _fetch_full_text(document_number, doc["raw_text_url"])
        if full:
            text, text_source = full, "full_text"
    substances = db.company_substances()       # 회사 제품에 든 규제 물질만 (전체 수천 종으로 찾으면 무관한 물질이 잡힘)
    return {"source": source, "text_source": text_source, "text_warning": warning,
            **{k: doc.get(k) for k in FIELDS},
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
