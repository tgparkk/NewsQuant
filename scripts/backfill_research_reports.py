"""증권사 리서치 리포트 백필 CLI(2년 · 없는 nid 만 backfilled=TRUE · 다시 돌려도 안전).

    python scripts/backfill_research_reports.py --config D:/GIT/NewsQuant/config.yaml --dry-run --max-pages 2
    python scripts/backfill_research_reports.py --config D:/GIT/NewsQuant/config.yaml
    python scripts/backfill_research_reports.py --config D:/GIT/NewsQuant/config.yaml --start-index 412

종료 코드: 끝까지/상한 도달 0 · 요청·DB 오류로 중단 1
DDL: docs/research_reports_ddl_2026-10-17.sql (먼저 적용돼 있어야 한다)
"""
import argparse
import contextlib
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_scraper import research_collector as rc


def _connect(config_path: str):
    import psycopg2
    import yaml

    with open(config_path, "r", encoding="utf-8") as f:
        db = (yaml.safe_load(f) or {}).get("database") or {}
    return psycopg2.connect(
        host=db.get("host", "localhost"),
        port=int(db.get("port", 5432)),
        dbname=db.get("name", "kis_template"),
        user=db.get("user", "postgres"),
        password=db.get("password", ""),
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="증권사 리서치 리포트 백필")
    ap.add_argument("--config", required=True, help="DB 설정 YAML(읽기 전용) — 예: D:/GIT/NewsQuant/config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="DB 접속·쓰기 0, 요청·파싱 요약만 출력")
    ap.add_argument("--max-pages", type=int, default=None, help="요청 쪽 수 상한(시험용)")
    ap.add_argument("--start-index", type=int, default=0,
                    help="이 쪽(index)부터 — 중단 뒤 이어 돌릴 때 출력된 「마지막 index」를 준다")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    conn = None if args.dry_run else _connect(args.config)
    try:
        res = rc.run_backfill(
            conn,
            fetch=rc.fetch_page,
            sleep=time.sleep,
            max_pages=args.max_pages,
            dry_run=args.dry_run,
            start_index=args.start_index,
        )
    finally:
        if conn is not None:
            conn.close()

    print(f"[research_backfill] mode={'DRY-RUN' if args.dry_run else 'WRITE'} "
          f"컷오프={rc.BACKFILL_CUTOFF} 쪽크기={rc.BACKFILL_PAGE_SIZE} 시작 index={args.start_index}")
    print(f"  요청={res['requests']} 마지막 index={res['last_index']} 멈춤={res['stop_reason'] or '오류'}")
    if args.dry_run:
        print(f"  넣을 행(추정)={res['would_insert']}")
    else:
        print(f"  넣은 행={res['inserted']} · 이미 있음(생략)={res['skipped']}")
    print(f"  컷오프 미만={res['below_cutoff']} · 오늘 작성분(정방향 몫)={res['today_skipped']} · "
          f"무효={res['invalid']} · 가장 오래된 작성일={res['oldest_date']}")
    if res.get("error"):
        print(f"  ! {res['error']} — --start-index {res['last_index']} 로 이어 돌릴 수 있다"
              f"(처음부터 다시 돌려도 있는 nid 는 건너뛴다)")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
