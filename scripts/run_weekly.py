"""정기 브리핑을 만든다 (Step 10) — 지난 주차 예시 생성·내보내기용. 평소에는 서버의 스케줄러가 매주 월요일에 만든다.

    uv run python scripts/run_weekly.py --backfill 3                      # 끝난 주 3개 (최근 주부터)
    uv run python scripts/run_weekly.py --start 2026-10-12                # 그 주 (월요일)
    uv run python scripts/run_weekly.py --backfill 3 --export data/weekly # 처음 실행 때 채울 예시로 내보내기

.env 설정(LLM_BACKEND, LAW_API_OC)을 그대로 쓴다 — 실제 미국 관보·법제처를 그 기간으로 조회한다.
"""
import argparse
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_settings  # noqa: E402
from app.service import AgentService  # noqa: E402
from app.weekly import last_complete_weeks, run_weekly, week_of  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backfill", type=int, default=0, help="끝난 주 몇 개를 만들지")
    parser.add_argument("--start", help="이 주(월요일, YYYY-MM-DD)만")
    parser.add_argument("--export", help="결과를 주차별 JSON으로 내보낼 폴더 (예: data/weekly)")
    args = parser.parse_args()
    weeks = [week_of(date.fromisoformat(args.start))] if args.start else last_complete_weeks(date.today(), args.backfill)
    if not weeks:
        sys.exit("--backfill N 또는 --start YYYY-MM-DD 를 주세요")
    settings = get_settings()
    print(f"LLM {settings.llm_backend} · 법제처 키 {'있음' if settings.law_api_oc else '없음'} · 수집 {settings.feed_mode}")
    async with AsyncExitStack() as stack:
        service = await AgentService.create(settings, stack)
        for week_id, start, end in weeks:
            print(f"  {week_id} ({start}~{end}) 생성 중…", flush=True)
            record = await run_weekly(service, start, end)
            print(f"    {record['status']} · 관련 변경 {record.get('documents', 0)}건 · 영향 제품 "
                  f"{record.get('impacted') or '없음'} · {record['latency_ms'] / 1000:.0f}초")
            if args.export:
                folder = Path(args.export)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{week_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1),
                                                        encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
