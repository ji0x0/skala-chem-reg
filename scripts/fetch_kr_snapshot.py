"""법제처 Open API에서 화학물질 관련 국내 행정규칙(고시)의 목록·본문을 받아 스냅샷으로 저장한다.

    uv run python scripts/fetch_kr_snapshot.py              # 최근 400일
    uv run python scripts/fetch_kr_snapshot.py --days 200

왜 스냅샷을 저장하나? (미국 관보 스냅샷과 같은 이유)
- 평가 재현성: 실시간 결과는 날마다 바뀐다. 같은 입력으로 Before/After를 반복하려면 고정본이 필요하다
- 오프라인 시연: 키·네트워크 없이도 같은 화면을 보여 줄 수 있다
스냅샷 모드(FEED_MODE=snapshot)에서도 "최근 N일" 조건은 스냅샷을 받은 날 기준으로 지킨다.

필요: .env의 LAW_API_OC (법제처 Open API 인증키). 결과에 인증키는 저장하지 않는다.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp_servers import reg_feed_server as feed  # noqa: E402

# 국내 수집 에이전트가 쓰는 기본 검색어와 같다 (에이전트가 다른 검색어를 쓰면 제목·본문에서 찾는다)
QUERIES = ["유해화학물질", "제한물질", "금지물질", "사고대비물질", "허가물질", "화학물질", "산업안전보건", "관리대상"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=400)
    args = parser.parse_args()
    if not feed.settings.law_api_oc:
        sys.exit("LAW_API_OC가 없습니다 — .env에 법제처 Open API 인증키를 넣으세요.")

    found: dict[str, dict] = {}
    for query in QUERIES:
        for doc in feed.kr_search_live(query, args.days, body=False, limit=50):
            found.setdefault(doc["serial"], doc)
        print(f"  검색 '{query}' → 누적 {len(found)}건")

    feed.KR_FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)
    for i, (serial, meta) in enumerate(sorted(found.items()), start=1):
        doc = feed.kr_fetch_live(serial)
        doc["annexes"] = doc["annexes"][:400]          # 큰 별표는 앞부분만 (본문 언급 참고용 — 변경 판단에는 안 씀)
        (feed.KR_FULLTEXT_DIR / f"{serial}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  [{i}/{len(found)}] {meta['issued_on']} {meta['title']}")

    documents = sorted(found.values(), key=lambda d: d["issued_on"] or "", reverse=True)
    feed.KR_SNAPSHOT.write_text(json.dumps({"captured_on": date.today().isoformat(), "days": args.days,
                                            "queries": QUERIES, "documents": documents},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {feed.KR_SNAPSHOT} (문서 {len(documents)}건, 본문 {feed.KR_FULLTEXT_DIR})")


if __name__ == "__main__":
    main()
