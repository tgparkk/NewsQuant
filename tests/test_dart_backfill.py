"""실 DB(kis_template) 왕복 — DART published_at 백필.

DART 공시 149,996건이 전부 자정으로 저장돼 있었다(원인은 dart_crawler 참고).
크롤러는 고쳤지만 이미 쌓인 행은 그대로다. created_at 이 전 행에 있고
default now() 이며 upsert 가 건드리지 않으므로 «최초 관측 시각» 이다.
그 값으로 되돌려 준다.

DB 없으면 conftest.db 픽스처가 skip 한다.
"""
from datetime import datetime

import pytest

from scripts.backfill_dart_published_at import (
    BACKUP_TABLE,
    backfill,
    ensure_backup_table,
    revert,
)

pytestmark = pytest.mark.db

SENTINEL = "test-dart-backfill-0001"
FILED_DATE = datetime(2026, 5, 20, 0, 0, 0)      # 지금까지 저장되던 값
COLLECTED_AT = datetime(2026, 5, 20, 17, 46, 12)  # 실제로 처음 본 시각


@pytest.fixture
def sentinel_row(db):
    ensure_backup_table(db)
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {BACKUP_TABLE} WHERE news_id = %s", (SENTINEL,))
            cur.execute("DELETE FROM news WHERE news_id = %s", (SENTINEL,))
            cur.execute("""
                INSERT INTO news (news_id, title, content, published_at, source,
                                  category, url, related_stocks, created_at)
                VALUES (%s, %s, %s, %s, 'dart', '공시', %s, '', %s)
            """, (SENTINEL, "[테스트] 백필 센티널", "본문", FILED_DATE,
                  f"https://example.invalid/{SENTINEL}", COLLECTED_AT))
        conn.commit()
    finally:
        db._put_connection(conn)

    yield

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {BACKUP_TABLE} WHERE news_id = %s", (SENTINEL,))
            cur.execute("DELETE FROM news WHERE news_id = %s", (SENTINEL,))
        conn.commit()
    finally:
        db._put_connection(conn)


def _published_at(db, news_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT published_at FROM news WHERE news_id = %s", (news_id,))
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.rollback()
        db._put_connection(conn)


def test_실행_전에는_바꾸지_않고_대상만_센다(db, sentinel_row):
    stats = backfill(db, apply=False, only_news_id=SENTINEL)

    assert stats["candidates"] == 1
    assert stats["updated"] == 0
    assert _published_at(db, SENTINEL) == FILED_DATE


def test_최초_관측_시각으로_되돌린다(db, sentinel_row):
    stats = backfill(db, apply=True, only_news_id=SENTINEL)

    assert stats["updated"] == 1
    assert _published_at(db, SENTINEL) == COLLECTED_AT


def test_원본을_백업_테이블에_남긴다(db, sentinel_row):
    backfill(db, apply=True, only_news_id=SENTINEL)

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT published_at_old FROM {BACKUP_TABLE} WHERE news_id = %s",
                        (SENTINEL,))
            assert cur.fetchone()[0] == FILED_DATE
    finally:
        conn.rollback()
        db._put_connection(conn)


def test_두_번_돌려도_같다(db, sentinel_row):
    backfill(db, apply=True, only_news_id=SENTINEL)

    again = backfill(db, apply=True, only_news_id=SENTINEL)

    assert again["candidates"] == 0
    assert _published_at(db, SENTINEL) == COLLECTED_AT


def test_백업으로_되돌릴_수_있다(db, sentinel_row):
    backfill(db, apply=True, only_news_id=SENTINEL)

    reverted = revert(db, apply=True, only_news_id=SENTINEL)

    assert reverted["updated"] == 1
    assert _published_at(db, SENTINEL) == FILED_DATE


def test_자정이_아닌_행은_건드리지_않는다(db, sentinel_row):
    backfill(db, apply=True, only_news_id=SENTINEL)   # 이제 17:46:12 다

    stats = backfill(db, apply=True, only_news_id=SENTINEL)

    assert stats["candidates"] == 0
