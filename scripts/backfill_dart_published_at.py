"""DART 공시의 published_at 을 최초 관측 시각으로 되돌린다.

Open DART list.json 은 접수 «시각» 을 주지 않는다(rcept_dt 는 YYYYMMDD).
그래서 크롤러가 strptime("%Y%m%d") 결과를 그대로 써 공시 149,996건이 전부
자정으로 저장됐다. 그 탓에 섹터 집계 창([직전 평일 15:30, now]) 의 시작보다
앞서서, 장 마감 뒤에 나온 공시가 다음 거래일 집계에서 통째로 빠졌다.
수집 시각 기준 15:30 이후 접수분이 60,709건(40.5%) 이다.

크롤러는 고쳤다(수집 시각을 쓴다). 이미 쌓인 행은 created_at 으로 되돌린다 —
default now() 이고 upsert 의 ON CONFLICT 가 건드리지 않으므로 «최초 관측
시각» 이 맞다. 전 행에 값이 있고 98.6% 가 접수일과 같은 날이며, 대량
마이그레이션으로 한 시점에 몰린 구간도 없다(2026-01-07 ~ 09-11 고르게 분포).

나머지 1.4% 는 DART 가 마감 후 제출분에 «익일» 접수번호를 주기 때문이다
(D 23:41 에 수집했는데 접수일은 D+1). 그때도 우리가 실제로 본 시각은
D 23:41 이라 created_at 이 맞다.

    python scripts/backfill_dart_published_at.py            # 대상만 세고 끝
    python scripts/backfill_dart_published_at.py --apply    # 실제 갱신
    python scripts/backfill_dart_published_at.py --revert --apply   # 되돌리기
"""
import argparse
import logging
import os
import sys
from typing import Dict, Optional

# 스크립트로 직접 돌릴 때 저장소 루트를 import 경로에 올린다 (migrate_sqlite_to_pg 와 동일)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

BACKUP_TABLE = "news_dart_published_at_backup"

_CREATE_BACKUP = f"""
CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} (
    news_id           TEXT PRIMARY KEY,
    published_at_old  TIMESTAMP NOT NULL,
    backed_up_at      TIMESTAMP NOT NULL DEFAULT now()
)
"""

# 자정으로 찍힌 DART 행만. 이미 고쳐진 행은 다시 건드리지 않는다(재실행 안전).
_WHERE = """
    source = 'dart'
    AND published_at::time = time '00:00:00'
    AND created_at IS NOT NULL
    AND created_at <> published_at
"""


def ensure_backup_table(db) -> None:
    """백업 테이블을 만든다. 없으면 되돌릴 수 없으므로 쓰기 전에 항상 부른다."""
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_BACKUP)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_connection(conn)


def backfill(db, apply: bool = False, only_news_id: Optional[str] = None) -> Dict:
    """published_at ← created_at. 원본은 백업 테이블에 남긴다."""
    extra = " AND news_id = %s" if only_news_id else ""
    params = (only_news_id,) if only_news_id else ()

    ensure_backup_table(db)
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM news WHERE {_WHERE}{extra}", params)
            candidates = cur.fetchone()[0]

            updated = 0
            if candidates:
                cur.execute(f"""
                    INSERT INTO {BACKUP_TABLE} (news_id, published_at_old)
                    SELECT news_id, published_at FROM news WHERE {_WHERE}{extra}
                    ON CONFLICT (news_id) DO NOTHING
                """, params)
                cur.execute(
                    f"UPDATE news SET published_at = created_at WHERE {_WHERE}{extra}", params
                )
                updated = cur.rowcount

        if apply:
            conn.commit()
        else:
            conn.rollback()
            updated = 0
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_connection(conn)

    return {"candidates": candidates, "updated": updated, "applied": apply}


def revert(db, apply: bool = False, only_news_id: Optional[str] = None) -> Dict:
    """백업 테이블의 원본 값으로 되돌린다."""
    extra = " AND n.news_id = %s" if only_news_id else ""
    params = (only_news_id,) if only_news_id else ()

    ensure_backup_table(db)
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                UPDATE news n SET published_at = b.published_at_old
                FROM {BACKUP_TABLE} b
                WHERE n.news_id = b.news_id AND n.published_at <> b.published_at_old{extra}
            """, params)
            updated = cur.rowcount
        if apply:
            conn.commit()
        else:
            conn.rollback()
            updated = 0
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_connection(conn)

    return {"updated": updated, "applied": apply}


def _report(db) -> None:
    """되돌린 값이 집계 창에 들어오는지 눈으로 확인할 수치."""
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT count(*),
                       count(*) FILTER (WHERE published_at::time = time '00:00:00'),
                       count(*) FILTER (WHERE published_at::time >= time '15:30')
                FROM news WHERE source = 'dart'
            """)
            total, midnight, after_close = cur.fetchone()
    finally:
        conn.rollback()
        db._put_connection(conn)
    print(f"  DART 전체 {total} · 자정 {midnight} · 15:30 이후 {after_close}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다 (기본은 세어만 본다)")
    ap.add_argument("--revert", action="store_true", help=f"{BACKUP_TABLE} 의 원본으로 되돌린다")
    args = ap.parse_args()

    from news_scraper.database import NewsDatabase
    db = NewsDatabase()

    print("실행 전:")
    _report(db)

    if args.revert:
        stats = revert(db, apply=args.apply)
        print(f"되돌림 {stats['updated']}건 (apply={args.apply})")
    else:
        stats = backfill(db, apply=args.apply)
        print(f"대상 {stats['candidates']}건 · 갱신 {stats['updated']}건 (apply={args.apply})")

    print("실행 후:")
    _report(db)
    if not args.apply:
        print("\n※ --apply 없이 돌렸다. 아무것도 쓰지 않았다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
