"""MCP 서버 ③ reg-feed — 국내외 규제 변경 원문 조회 (Tool).

- 미국: 연방 관보(Federal Register) API — 공개, 키 불필요
- 국내: 법제처 국가법령정보 Open API(행정규칙 = 고시·훈령·예규) — LAW_API_OC 설정 시. 스냅샷은 data/feeds/kr_*
- EU: 공식 문서 저장소 Cellar(SPARQL·XHTML) — REACH·CLP 개정 법령 (Step 11). 스냅샷은 data/feeds/eu_*

실시간 호출이 실패하면 data/feeds/ 스냅샷으로 대신 답하고, 결과에 source(live/snapshot)를 표시한다.
규제 판단에서는 "언제, 어디서 받은 데이터인지"가 중요하기 때문이다.
FEED_MODE=snapshot이면 실시간 호출 없이 스냅샷 목록과 저장된 본문(data/feeds/fulltext·kr_fulltext·eu_fulltext)만 쓴다
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
from app.domain.mentions import find_korean_mentions, find_substance_mentions

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


def _in_period(day: str | None, since: str | None, until: str | None) -> bool:
    return (not since or (day or "") >= since) and (not until or (day or "") <= until)


@mcp.tool()
def search_federal_register(term: str = "TSCA", days: int = 30, agency: str = "environmental-protection-agency",
                            limit: int = 20, since: str | None = None, until: str | None = None) -> dict:
    """미국 연방 관보에서 최근 문서를 검색합니다 (기본: 최근 30일 EPA TSCA).
    since·until(YYYY-MM-DD)을 주면 그 게시 기간으로 찾습니다 (정기 브리핑: 지난주 월~일).
    결과마다 문서 번호·제목·종류(Rule/Proposed Rule/Notice)·게시일·요약·원문 링크·의견 마감일을 줍니다."""
    params = [("conditions[agencies][]", agency), ("conditions[term]", term),
              ("conditions[publication_date][gte]", since or (date.today() - timedelta(days=days)).isoformat()),
              ("order", "newest"), ("per_page", str(limit))] + [("fields[]", f) for f in FIELDS]
    if until:
        params.append(("conditions[publication_date][lte]", until))
    if settings.feed_mode == "snapshot":
        docs = [d for d in _snapshot_documents() if _in_period(d.get("publication_date"), since, until)]
        return {"source": "snapshot", "warning": "스냅샷 모드 — 저장된 관보 목록 사용"
                + (" (기간으로 거름)" if since or until else " (최근 N일 조건 무시)"), "documents": docs[:limit]}
    try:
        resp = httpx.get(f"{settings.federal_register_api}/documents.json", params=params,
                         timeout=settings.http_timeout_s)
        resp.raise_for_status()
        return {"source": "live", "query": {"term": term, "days": days, "agency": agency},
                "documents": resp.json().get("results", [])}
    except httpx.HTTPError as exc:
        docs = [d for d in _snapshot_documents() if _in_period(d.get("publication_date"), since, until)]
        return {"source": "snapshot", "warning": f"실시간 조회 실패({type(exc).__name__}) — 저장된 스냅샷 사용",
                "documents": docs[:limit]}


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


# ── 국내: 법제처 국가법령정보 Open API (행정규칙 = 고시·훈령·예규) ─────────────────────
LAW_API = "https://www.law.go.kr/DRF"
KR_SNAPSHOT = settings.feeds_dir / "kr_admin_rules.json"     # 검색 결과 고정본 (평가·오프라인 시연)
KR_FULLTEXT_DIR = settings.feeds_dir / "kr_fulltext"         # 고정본 문서의 본문 (저장소에 포함)
KR_CACHE_DIR = CACHE_DIR / "kr"                              # 실시간으로 받은 본문 캐시 (Git 제외)
UNIQUE_ID = re.compile(r"(?<![\d-])(\d{2,4}-\d-\d{1,4})(?![\d-])")   # 화관법 고유번호 (예: 97-1-309, 2010-1-609)


def _ymd(value: str | None) -> str | None:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if value and len(value) == 8 else value


def _kr_meta(row: dict) -> dict:
    """검색 결과·본문 기본정보 → 공통 형식. 응답의 상세 링크에는 인증키(OC)가 들어 있어 쓰지 않는다."""
    serial = row["행정규칙일련번호"]
    return {"serial": serial, "title": row["행정규칙명"], "kind": row.get("행정규칙종류"),
            "agency": row.get("소관부처명"), "revision": row.get("제개정구분명"), "number": row.get("발령번호"),
            "issued_on": _ymd(row.get("발령일자")), "effective_on": _ymd(row.get("시행일자")),
            "html_url": f"https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq={serial}"}


def _lines(value) -> list[str]:
    """본문 응답은 문자열·목록이 여러 겹으로 섞여 온다 → 줄 목록으로 편다."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [line for v in value for line in _lines(v)]
    return []


def kr_search_live(query: str, days: int, body: bool, limit: int,
                   since: str | None = None, until: str | None = None) -> list[dict]:
    """법제처 행정규칙 목록 — 발령일 기간(prmlYd)·최신순(ddes). body=True면 본문 검색(search=2)."""
    start = date.fromisoformat(since) if since else date.today() - timedelta(days=days)
    end = date.fromisoformat(until) if until else date.today()
    resp = httpx.get(f"{LAW_API}/lawSearch.do", timeout=settings.http_timeout_s, params={
        "OC": settings.law_api_oc, "target": "admrul", "type": "JSON", "query": query, "display": limit,
        "sort": "ddes", "search": 2 if body else 1, "prmlYd": f"{start:%Y%m%d}~{end:%Y%m%d}"})
    resp.raise_for_status()
    rows = resp.json().get("AdmRulSearch", {}).get("admrul") or []
    return [_kr_meta(r) for r in (rows if isinstance(rows, list) else [rows])]


def kr_fetch_live(serial: str) -> dict:
    """행정규칙 본문 → 필요한 부분만: 개정문(무엇을 바꿨나)·이번 부칙(시행일·경과조치)·바뀐 조문·조문·별표."""
    resp = httpx.get(f"{LAW_API}/lawService.do", timeout=settings.http_timeout_s,
                     params={"OC": settings.law_api_oc, "target": "admrul", "ID": serial, "type": "JSON"})
    resp.raise_for_status()
    body = resp.json()["AdmRulService"]
    meta = _kr_meta(body["행정규칙기본정보"])
    # 부칙은 개정 때마다 쌓인다 → 이번 발령번호의 부칙만 (시행일·경과조치)
    addenda = [a for a in _lines((body.get("부칙") or {}).get("부칙내용")) if f"제{meta['number']}호" in a]
    annex = (body.get("별표") or {}).get("별표단위") or []
    annex_lines = [line for unit in (annex if isinstance(annex, list) else [annex])
                   for line in _lines(unit.get("별표내용"))
                   if "버튼" not in line]                       # "자세한 내용은 … 버튼" 같은 안내문 제외
    return {**meta, "amendment": _lines((body.get("개정문") or {}).get("개정문내용")),
            "addenda": addenda, "changes": kr_changed_articles(serial),
            "articles": _lines(body.get("조문내용")), "annexes": annex_lines}


def kr_changed_articles(serial: str) -> list[str]:
    """신구 조문 대비표(admrulOldAndNew)에서 이번에 바뀐 새 조문만. 바뀐 부분은 <P>…</P>로 표시돼 온다.
    개정문이 없는 고시도 무엇이 바뀌었는지 알 수 있다 (별표만 바뀐 경우는 대비표가 없음)."""
    try:
        resp = httpx.get(f"{LAW_API}/lawService.do", timeout=settings.http_timeout_s, params={
            "OC": settings.law_api_oc, "target": "admrulOldAndNew", "ID": serial, "type": "JSON"})
        resp.raise_for_status()
        new = (resp.json().get("AdmRulOldAndNewService") or {}).get("신조문목록") or {}
    except (httpx.HTTPError, ValueError):
        return []
    rows = new.get("조문") if isinstance(new, dict) else new
    rows = rows if isinstance(rows, list) else [rows] if rows else []
    return [re.sub(r"</?P>", "", r["content"]).strip() for r in rows if "<P>" in r.get("content", "")]


def _kr_snapshot() -> dict:
    return json.loads(KR_SNAPSHOT.read_text(encoding="utf-8")) if KR_SNAPSHOT.exists() else {"documents": []}


def _kr_saved(serial: str) -> dict | None:
    for saved in (KR_FULLTEXT_DIR / f"{serial}.json", KR_CACHE_DIR / f"{serial}.json"):
        if saved.exists():
            return json.loads(saved.read_text(encoding="utf-8"))
    return None


def _kr_text(doc: dict, change_only: bool = False) -> str:
    """근거 문장을 고르기 쉽게 줄마다 빈 줄로 나눈 본문. change_only=True면 개정문·이번 부칙만 (무엇이 바뀌었나)."""
    parts = doc["amendment"] + doc["addenda"] + doc.get("changes", []) + ([] if change_only else doc["articles"] + doc["annexes"])
    return "\n\n".join(parts)


def _kr_mentions(text: str, substances: list[dict], unique_ids: dict[str, dict]) -> list[dict]:
    """영문 이름·CAS + 한글 이름 + 화관법 고유번호로 언급된 회사 물질."""
    names_ko = {}
    for sub in substances:
        names_ko[sub["cas"]] = names_ko.get(sub["cas"]) or sub["name_ko"]
    found = {m["cas"]: m for m in find_substance_mentions(text, substances)}
    extra = find_korean_mentions(text, substances)
    extra += [{**sub, "mentions": len(re.findall(rf"(?<![\d-]){re.escape(ref)}(?![\d-])", text)), "matched_terms": [ref]}
              for ref, sub in unique_ids.items() if ref in text]
    for m in extra:
        if not m["mentions"]:
            continue
        hit = found.setdefault(m["cas"], {**m, "mentions": 0, "matched_terms": []})
        hit["mentions"] += m["mentions"]
        hit["matched_terms"] += m["matched_terms"]
    for hit in found.values():
        hit["name_ko"] = names_ko.get(hit["cas"]) or hit["name_ko"]
        hit["matched_terms"] = list(dict.fromkeys(hit["matched_terms"]))
    return sorted(found.values(), key=lambda m: -m["mentions"])


def _kr_from_snapshot(query: str, days: int, body: bool, limit: int, warning: str,
                      since: str | None = None, until: str | None = None) -> dict:
    """스냅샷에서 검색. 기간은 since·until이 있으면 그대로, 없으면 스냅샷을 받은 날 기준 최근 N일
    (90일 → 1년 재검색도 실시간과 같게 재현)."""
    snap = _kr_snapshot()
    if not since and snap.get("captured_on"):
        since = (date.fromisoformat(snap["captured_on"]) - timedelta(days=days)).isoformat()
    hits = []
    for d in snap["documents"]:
        if not _in_period(d["issued_on"], since, until):
            continue
        saved = _kr_saved(d["serial"]) if body else None
        if query in d["title"] or (saved and query in _kr_text(saved)):
            hits.append(d)
    return {"source": "snapshot", "warning": warning, "query": query, "days": days,
            "captured_on": snap.get("captured_on"), "documents": hits[:limit]}


@mcp.tool()
def search_kr_admin_rules(query: str, days: int = 90, body: bool = False, limit: int = 10,
                          since: str | None = None, until: str | None = None) -> dict:
    """국내 행정규칙(고시·훈령·예규)을 법제처에서 최신 발령순으로 검색합니다.
    - query: 검색어 (예: '유해화학물질', '화학물질의 분류', '산업안전보건')
    - days: 최근 며칠 안에 발령된 것만 (기본 90일). since·until(YYYY-MM-DD)을 주면 그 발령 기간으로
    - body: True면 제목뿐 아니라 본문에서도 찾습니다 (물질 이름으로 찾을 때)
    결과마다 일련번호(serial)·제목·소관부처·제개정 구분·발령일·시행일을 줍니다."""
    if settings.feed_mode == "snapshot":
        return _kr_from_snapshot(query, days, body, limit, "스냅샷 모드 — 저장된 국내 목록 사용", since, until)
    if not settings.law_api_oc:
        return {"source": "disabled", "documents": [],
                "message": "LAW_API_OC 미설정 — open.law.go.kr에서 Open API를 신청한 뒤 .env에 넣으세요."}
    try:
        return {"source": "live", "query": query, "days": days, "body": body, "since": since, "until": until,
                "documents": kr_search_live(query, days, body, limit, since, until)}
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return _kr_from_snapshot(query, days, body, limit, f"실시간 조회 실패({type(exc).__name__}) — 저장된 스냅샷 사용",
                                 since, until)


def _kr_unique_ids() -> dict[str, dict]:
    """회사 제품 성분 중 화관법 목록에 있는 물질의 고유번호 → 물질 (고시 개정문은 물질을 고유번호로 가리킨다)."""
    substances = {s["cas"]: s for s in db.company_substances()}
    out = {}
    for lst in db.listings_for_cas(list(substances)):
        for ref in UNIQUE_ID.findall(lst.get("entry_ref") or ""):
            if lst["reg_id"].startswith("KR_CCA"):
                out[ref] = substances[lst["cas"]]
    return out


@mcp.tool()
def get_kr_admin_rule(serial: str, max_chars: int = 60000) -> dict:
    """국내 행정규칙 하나의 본문을 가져오고, 회사 제품 성분의 언급을 찾습니다.
    - substance_mentions: 이번 개정 내용(개정문·이번 부칙·신구 대비의 바뀐 조문)에서 언급된 회사 물질 → 영향 판정 대상
    - body_mentions: 현행 본문 전체(조문·별표)에서 언급된 회사 물질 → 참고 (바뀐 내용인지는 알 수 없음)
    - change_text_available: 개정문·신구 조문 대비 중 하나라도 있는지 (없으면 무엇이 바뀌었는지 원문 확인 필요)
    물질은 한글 이름·영문 이름·CAS·화관법 고유번호(예: 97-1-309)로 찾습니다. serial 예: 2100000285186"""
    doc, source = _kr_saved(serial), "snapshot"
    if doc is None:
        if settings.feed_mode == "snapshot" or not settings.law_api_oc:
            raise ValueError(f"저장된 본문이 없습니다 (스냅샷 모드 또는 키 미설정): {serial}")
        doc, source = kr_fetch_live(serial), "live"
        KR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (KR_CACHE_DIR / f"{serial}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    substances, unique_ids = db.company_substances(), _kr_unique_ids()
    change, text = _kr_text(doc, change_only=True), _kr_text(doc)
    return {"source": source, **{k: v for k, v in doc.items() if k not in ("articles", "annexes")},
            "change_text": change, "change_text_available": bool(doc["amendment"] or doc.get("changes")),
            "text": text[:max_chars], "text_truncated": len(text) > max_chars,
            "substance_mentions": _kr_mentions(change, substances, unique_ids),
            "body_mentions": [{k: m[k] for k in ("cas", "name_ko", "name_en", "mentions")}
                              for m in _kr_mentions(text, substances, unique_ids)]}


# ── EU: 공식 문서 저장소(Cellar) — REACH·CLP를 개정한 법령 (Step 11) ─────────────────────
# EUR-Lex 웹사이트는 자동 요청을 막지만(403), 같은 공식 문서를 EU 출판국 Cellar가 SPARQL·XHTML로 준다 (키 불필요)
CELLAR_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
EU_BASE_ACTS = {"32006R1907": "REACH", "32008R1272": "CLP"}
EU_SNAPSHOT = settings.feeds_dir / "eu_acts.json"            # 검색 결과 고정본
EU_FULLTEXT_DIR = settings.feeds_dir / "eu_fulltext"         # 고정본 법령 본문 (평문)
EU_CACHE_DIR = CACHE_DIR / "eu"
OJ_DATE = re.compile(r"L series\s+\d{4}/\d+\s+(\d{1,2})\.(\d{1,2})\.(\d{4})")          # 관보 게재일 "2.6.2026"
ADOPTED = re.compile(r"\bof (\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|"
                     r"November|December) (\d{4})")                                     # 채택일 "of 8 August 2025"
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]


def eu_search_live(since: str, until: str, limit: int) -> list[dict]:
    """REACH·CLP를 개정한 법령 (채택일 기준 기간). 결과: CELEX·채택일·제목·개정 대상."""
    query = f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex ?date ?base ?title WHERE {{
  VALUES ?base {{ {" ".join(f'"{b}"' for b in EU_BASE_ACTS)} }}
  ?target cdm:resource_legal_id_celex ?baseLit . FILTER(STR(?baseLit) = ?base)
  ?work cdm:resource_legal_amends_resource_legal ?target ; cdm:resource_legal_id_celex ?celex ;
        cdm:work_date_document ?date .
  OPTIONAL {{ ?expr cdm:expression_belongs_to_work ?work ;
              cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
              cdm:expression_title ?title }}
  FILTER(?date >= "{since}"^^<http://www.w3.org/2001/XMLSchema#date> &&
         ?date <= "{until}"^^<http://www.w3.org/2001/XMLSchema#date>)
}} ORDER BY DESC(?date) LIMIT {limit}"""
    resp = httpx.get(CELLAR_SPARQL, params={"query": query}, timeout=settings.http_timeout_s * 3,
                     headers={"Accept": "application/sparql-results+json"})
    resp.raise_for_status()
    acts: dict[str, dict] = {}
    for b in resp.json()["results"]["bindings"]:
        celex = b["celex"]["value"]
        act = acts.setdefault(celex, _eu_meta(celex, b["date"]["value"], b.get("title", {}).get("value", "")))
        act["amends"] = sorted(set(act.get("amends", [])) | {EU_BASE_ACTS[b["base"]["value"]]})
    return list(acts.values())


def _eu_meta(celex: str, adopted: str, title: str) -> dict:
    number = f"{celex[1:5]}/{int(celex[6:])}" if len(celex) > 6 and celex[6:].isdigit() else celex
    return {"celex": celex, "number": number, "title": re.sub(r"\s+", " ", title).strip()[:300], "adopted_on": adopted,
            "html_url": f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"}


def _eu_snapshot() -> dict:
    return json.loads(EU_SNAPSHOT.read_text(encoding="utf-8")) if EU_SNAPSHOT.exists() else {"acts": []}


def _eu_from_snapshot(since: str, until: str, limit: int, warning: str) -> dict:
    acts = [a for a in _eu_snapshot()["acts"] if _in_period(a["adopted_on"], since, until)]
    return {"source": "snapshot", "warning": warning, "since": since, "until": until, "documents": acts[:limit]}


def _eu_period(days: int, since: str | None, until: str | None, base: date) -> tuple[str, str]:
    return since or (base - timedelta(days=days)).isoformat(), until or base.isoformat()


@mcp.tool()
def search_eu_acts(days: int = 90, since: str | None = None, until: str | None = None, limit: int = 10) -> dict:
    """EU 공식 문서 저장소에서 REACH·CLP를 개정한 법령(위원회 규칙 등)을 최신 채택일 순으로 찾습니다.
    since·until(YYYY-MM-DD)을 주면 그 기간, 없으면 최근 days일. 결과: CELEX·번호·제목·채택일·개정 대상(REACH/CLP).
    주의: SVHC 후보 목록 추가는 법령이 아니라 ECHA 결정이라 여기 나오지 않습니다."""
    if settings.feed_mode == "snapshot":
        base = date.fromisoformat(_eu_snapshot().get("captured_on") or date.today().isoformat())
        start, end = _eu_period(days, since, until, base)
        return _eu_from_snapshot(start, end, limit, "스냅샷 모드 — 저장된 EU 개정 법령 목록 사용")
    start, end = _eu_period(days, since, until, date.today())
    try:
        return {"source": "live", "since": start, "until": end, "documents": eu_search_live(start, end, limit)}
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return _eu_from_snapshot(start, end, limit, f"실시간 조회 실패({type(exc).__name__}) — 저장된 스냅샷 사용")


def eu_fetch_live(celex: str) -> str:
    """법령 본문 XHTML → 평문 (영어)."""
    resp = httpx.get(f"https://publications.europa.eu/resource/celex/{celex}", follow_redirects=True,
                     timeout=settings.http_timeout_s * 3,
                     headers={"Accept": "application/xhtml+xml", "Accept-Language": "eng"})
    resp.raise_for_status()
    text = html.unescape(re.sub(r"<[^>]+>", " ", resp.text))
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", text)).strip()


@mcp.tool()
def get_eu_act(celex: str, max_chars: int = 60000) -> dict:
    """EU 개정 법령 하나의 본문을 가져오고, 회사 제품 성분의 언급(영문 이름·CAS)을 찾습니다.
    관보 게재일(본문 첫머리 "L series 2026/1168 2.6.2026")도 돌려줍니다. celex 예: 32025R1731"""
    meta = next((a for a in _eu_snapshot()["acts"] if a["celex"] == celex), None)
    text, source = None, "snapshot"
    for saved in (EU_FULLTEXT_DIR / f"{celex}.txt", EU_CACHE_DIR / f"{celex}.txt"):
        if saved.exists():
            text = saved.read_text(encoding="utf-8")
            break
    if text is None:
        if settings.feed_mode == "snapshot":
            raise ValueError(f"저장된 본문이 없습니다 (스냅샷 모드): {celex}")
        text, source = eu_fetch_live(celex), "live"
        EU_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (EU_CACHE_DIR / f"{celex}.txt").write_text(text, encoding="utf-8")
    m = OJ_DATE.search(text[:2000])
    oj = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None
    a = ADOPTED.search(text[:3000].replace("\xa0", " "))
    adopted = (meta or {}).get("adopted_on") or (
        f"{a.group(3)}-{MONTHS_EN.index(a.group(2)) + 1:02d}-{int(a.group(1)):02d}" if a else "")
    title = (meta or {}).get("title") or next((line for line in text.splitlines() if "REGULATION" in line), celex)
    return {"source": source, **_eu_meta(celex, adopted, title),
            "amends": (meta or {}).get("amends", []), "published_on": oj,
            "text": text[:max_chars], "text_truncated": len(text) > max_chars,
            "cas_numbers": find_cas_numbers(text),
            "substance_mentions": find_substance_mentions(text, db.company_substances())}


if __name__ == "__main__":
    mcp.run(show_banner=False)
