"""미국 연방 관보(Federal Register) API에서 EPA TSCA 문서를 받아 스냅샷으로 저장한다.

    uv run python scripts/fetch_feed_snapshot.py            # 최근 30일
    uv run python scripts/fetch_feed_snapshot.py --days 90

왜 스냅샷을 저장하나?
- 평가 재현성: 실시간 API 결과는 날마다 바뀐다. Before/After를 같은 입력으로 비교하려면 고정본이 필요하다
- 오프라인 데모: 발표 중 네트워크가 끊겨도 같은 화면을 보여 줄 수 있다
실시간 조회는 Step 2의 MCP 서버가 같은 API를 호출해 처리한다.

API: https://www.federalregister.gov/api/v1/documents.json (공개, 키 불필요)
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_settings  # noqa: E402

API_URL = "https://www.federalregister.gov/api/v1/documents.json"
FIELDS = ["document_number", "title", "type", "abstract", "publication_date",
          "html_url", "raw_text_url", "agencies", "effective_on", "comments_close_on"]


def fetch(days: int, term: str = "TSCA", per_page: int = 50) -> dict:
    since = date.today() - timedelta(days=days)
    params = [
        ("conditions[agencies][]", "environmental-protection-agency"),
        ("conditions[term]", term),
        ("conditions[publication_date][gte]", since.isoformat()),
        ("order", "newest"),
        ("per_page", str(per_page)),
    ] + [("fields[]", f) for f in FIELDS]
    resp = httpx.get(API_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {
        "source": "US Federal Register API",
        "query": {"agency": "EPA", "term": term, "since": since.isoformat()},
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": data.get("count", 0),
        "documents": [
            {**doc, "agencies": [a.get("name") for a in doc.get("agencies") or []]}
            for doc in data.get("results", [])
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    snapshot = fetch(args.days)
    out = get_settings().feeds_dir / "federal_register_tsca.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"저장: {out.name} — 최근 {args.days}일 EPA TSCA 문서 {len(snapshot['documents'])}건")
    for doc in snapshot["documents"][:5]:
        print(f"  {doc['publication_date']} [{doc['type']}] {doc['title'][:80]}")


if __name__ == "__main__":
    main()
