"""실 DB 왕복 — news → news_reprocessed 재처리.

저장된 related_stocks 는 어제 고친 추출기(b75de2a)의 출력이고
sentiment_score 는 구 로직이다. 그대로 백테스트하면 이미 고친 버그가
섞인 파이프라인을 측정하게 된다. 그래서 현재 코드로 다시 돈다.

news 는 «읽기만» 한다 — 운영 테이블을 또 덮어쓰지 않는다.
"""
from datetime import datetime

import pytest

from news_scraper.backtest.reprocess import ensure_table, reprocess

pytestmark = pytest.mark.db

SENTINEL = "test-reprocess-0001"


@pytest.fixture
def sentinel_row(db):
    ensure_table(db)
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news_reprocessed WHERE news_id = %s", (SENTINEL,))
            cur.execute("DELETE FROM news WHERE news_id = %s", (SENTINEL,))
            cur.execute("""
                INSERT INTO news (news_id, title, content, published_at, source,
                                  category, url, related_stocks, sentiment_score)
                VALUES (%s, %s, %s, %s, 'test', '테스트', %s, %s, %s)
            """, (SENTINEL, "삼성전자 4분기 실적 사상 최대",
                  "삼성전자가 4분기 영업이익이 늘었다고 밝혔다.",
                  datetime(2026, 6, 15, 10, 0), f"https://example.invalid/{SENTINEL}",
                  "999999", -0.9))
        conn.commit()
    finally:
        db._put_connection(conn)

    yield

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news_reprocessed WHERE news_id = %s", (SENTINEL,))
            cur.execute("DELETE FROM news WHERE news_id = %s", (SENTINEL,))
        conn.commit()
    finally:
        db._put_connection(conn)


def _row(db, news_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT related_stocks, sentiment_score, code_version
                           FROM news_reprocessed WHERE news_id = %s""", (news_id,))
            return cur.fetchone()
    finally:
        conn.rollback()
        db._put_connection(conn)


def test_apply_없이는_쓰지_않는다(db, sentinel_row):
    stats = reprocess(db, apply=False, only_news_id=SENTINEL)

    assert stats["candidates"] == 1
    assert stats["written"] == 0
    assert _row(db, SENTINEL) is None


def test_현재_추출기로_종목을_다시_붙인다(db, sentinel_row):
    reprocess(db, apply=True, only_news_id=SENTINEL)

    related, _, _ = _row(db, SENTINEL)
    assert "005930" in related.split(",")
    assert "999999" not in related.split(",")


def test_현재_로직으로_감성을_다시_매긴다(db, sentinel_row):
    """저장돼 있던 -0.9 는 구 로직 값이다."""
    reprocess(db, apply=True, only_news_id=SENTINEL)

    _, sentiment, _ = _row(db, SENTINEL)
    assert sentiment > 0


def test_어느_코드의_출력인지_남긴다(db, sentinel_row):
    reprocess(db, apply=True, only_news_id=SENTINEL)

    _, _, code_version = _row(db, SENTINEL)
    assert code_version


def test_두_번_돌려도_한_행이다(db, sentinel_row):
    reprocess(db, apply=True, only_news_id=SENTINEL)
    reprocess(db, apply=True, only_news_id=SENTINEL)

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM news_reprocessed WHERE news_id = %s",
                        (SENTINEL,))
            assert cur.fetchone()[0] == 1
    finally:
        conn.rollback()
        db._put_connection(conn)


def test_원본_news_를_건드리지_않는다(db, sentinel_row):
    reprocess(db, apply=True, only_news_id=SENTINEL)

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT related_stocks, sentiment_score FROM news WHERE news_id = %s",
                        (SENTINEL,))
            assert cur.fetchone() == ("999999", -0.9)
    finally:
        conn.rollback()
        db._put_connection(conn)
