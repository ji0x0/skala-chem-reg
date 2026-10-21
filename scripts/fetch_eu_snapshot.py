"""EU 공식 문서 저장소(Cellar)에서 REACH·CLP 개정 법령의 목록·본문을 받아 스냅샷으로 저장한다 (Step 11).

    uv run python scripts/fetch_eu_snapshot.py              # 최근 400일
    uv run python scripts/fetch_eu_snapshot.py --days 800

왜 스냅샷을 저장하나? (미국 관보·국내 고시 스냅샷과 같은 이유) 평가 재현성과 오프라인 시연.
스냅샷 모드에서도 "최근 N일" 조건은 스냅샷을 받은 날 기준으로 지킨다. 키는 필요 없다.
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp_servers import reg_feed_server as feed  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=400)
    args = parser.parse_args()
    today = date.today()
    acts = feed.eu_search_live((today - timedelta(days=args.days)).isoformat(), today.isoformat(), 50)
    feed.EU_FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)
    for act in acts:
        text = feed.eu_fetch_live(act["celex"])
        (feed.EU_FULLTEXT_DIR / f"{act['celex']}.txt").write_text(text, encoding="utf-8")
        print(f"  {act['adopted_on']} {act['number']} ({', '.join(act['amends'])}) {act['title'][:70]}")
    feed.EU_SNAPSHOT.write_text(json.dumps({"captured_on": today.isoformat(), "days": args.days, "acts": acts},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {feed.EU_SNAPSHOT} (법령 {len(acts)}건, 본문 {feed.EU_FULLTEXT_DIR})")


if __name__ == "__main__":
    main()
