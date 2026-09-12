"""news 전체를 현재 코드로 다시 돌려 news_reprocessed 에 쌓는다.

    python scripts/reprocess_news.py               # 대상만 센다
    python scripts/reprocess_news.py --apply       # 실제 실행 (약 34분)
    python scripts/reprocess_news.py --apply --limit 1000   # 맛보기

설계: docs/superpowers/specs/2026-09-12-news-signal-backtest-design.md §4
"""
import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다")
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N건만")
    args = ap.parse_args()

    from news_scraper.backtest.reprocess import reprocess
    from news_scraper.database import NewsDatabase

    db = NewsDatabase()
    t0 = time.monotonic()
    stats = reprocess(db, apply=args.apply, limit=args.limit)
    el = time.monotonic() - t0

    print(f"대상 {stats['candidates']:,}건 · 기록 {stats['written']:,}건 "
          f"· {el / 60:.1f}분 (apply={args.apply})")
    if not args.apply:
        print("\n※ --apply 없이 돌렸다. 아무것도 쓰지 않았다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
