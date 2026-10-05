"""네이버 테마 일일 스냅샷 CLI.

    python scripts/snapshot_naver_themes.py --config D:/GIT/NewsQuant/config.yaml --dry-run
    python scripts/snapshot_naver_themes.py --config D:/GIT/NewsQuant/config.yaml

종료 코드: ok/skip 0 · partial 2 · failed 1
설계: docs/theme_snapshot_2026-10-05.md
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_scraper.theme_snapshot import DEFAULT_ARCHIVE_DIR, run_snapshot  # noqa: E402


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
    ap = argparse.ArgumentParser(description="네이버 테마 일일 스냅샷")
    ap.add_argument("--config", required=True, help="DB 설정 YAML(읽기 전용) — 예: D:/GIT/NewsQuant/config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="DB·보관 쓰기 0, 요약만 출력")
    ap.add_argument("--force", action="store_true", help="같은 날 ok run 이 있어도 다시 돌림(빠진 것만 채움)")
    ap.add_argument("--archive-dir", default=DEFAULT_ARCHIVE_DIR)
    ap.add_argument("--limit-themes", type=int, default=None, help="시험용: 앞의 N 테마만")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    conn = None if args.dry_run else _connect(args.config)
    try:
        res = run_snapshot(
            conn,
            dry_run=args.dry_run,
            force=args.force,
            archive_dir=args.archive_dir,
            limit_themes=args.limit_themes,
        )
    finally:
        if conn is not None:
            conn.close()

    print(f"[theme_snapshot] snap_date={res.snap_date} status={res.status} run_id={res.run_id}")
    print(f"  mode={'DRY-RUN' if args.dry_run else 'WRITE'} market_status={res.market_status}")
    print(f"  테마 수(관측)={res.n_themes} (목록 totalCount={res.total_count_expected})")
    print(f"  멤버 수(관측)={res.n_members}")
    print(f"  stocks/map 어긋남 = {res.n_mismatch_themes}테마 · {res.n_mismatch_codes}종목")
    print(f"  실패 수={res.n_errors}")
    if not args.dry_run:
        print(f"  넣은 행: theme_daily {res.n_inserted_themes} · theme_member_daily {res.n_inserted_members}")
        print(f"  보관: {res.archive_path}")
    for e in res.errors[:10]:
        print(f"  ! {e}")
    if res.note:
        print(f"  note: {res.note}")
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
