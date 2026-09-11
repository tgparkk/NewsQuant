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


def test_category_별로_importance_가_다르다(db):
    """카테고리별로 importance_score 가 달라야 한다."""
    ensure_table(db)
    conn = db.get_connection()

    s1 = "test-importance-공시"
    s2 = "test-importance-산업"

    try:
        with conn.cursor() as cur:
            # 청소
            cur.execute("DELETE FROM news_reprocessed WHERE news_id IN (%s, %s)", (s1, s2))
            cur.execute("DELETE FROM news WHERE news_id IN (%s, %s)", (s1, s2))

            # 공시 카테고리
            cur.execute("""
                INSERT INTO news (news_id, title, content, published_at, source,
                                  category, url, related_stocks, sentiment_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (s1, "삼성 공시", "삼성전자가 공시했다",
                  datetime(2026, 6, 15, 10, 0), "test", "공시",
                  "https://example.invalid/1", "", 0))

            # 산업 카테고리
            cur.execute("""
                INSERT INTO news (news_id, title, content, published_at, source,
                                  category, url, related_stocks, sentiment_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (s2, "산업 뉴스", "산업 뉴스가 나왔다",
                  datetime(2026, 6, 15, 10, 0), "test", "산업",
                  "https://example.invalid/2", "", 0))

        conn.commit()
    finally:
        db._put_connection(conn)

    reprocess(db, apply=True, only_news_id=s1)
    reprocess(db, apply=True, only_news_id=s2)

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT importance_score FROM news_reprocessed WHERE news_id = %s",
                        (s1,))
            imp1 = cur.fetchone()[0]
            cur.execute("SELECT importance_score FROM news_reprocessed WHERE news_id = %s",
                        (s2,))
            imp2 = cur.fetchone()[0]
            assert imp1 != imp2, f"Importance scores should differ: {imp1} vs {imp2}"
    finally:
        conn.rollback()
        db._put_connection(conn)

    # 청소
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news_reprocessed WHERE news_id IN (%s, %s)", (s1, s2))
            cur.execute("DELETE FROM news WHERE news_id IN (%s, %s)", (s1, s2))
        conn.commit()
    finally:
        db._put_connection(conn)


def test_다중_종목_mention_은_impact_를_높인다(db):
    """여러 종목을 언급하는 기사는 impact_score > 0 이다."""
    ensure_table(db)
    conn = db.get_connection()

    sid = "test-impact-multi"

    try:
        with conn.cursor() as cur:
            # 청소
            cur.execute("DELETE FROM news_reprocessed WHERE news_id = %s", (sid,))
            cur.execute("DELETE FROM news WHERE news_id = %s", (sid,))

            # 여러 종목 언급
            cur.execute("""
                INSERT INTO news (news_id, title, content, published_at, source,
                                  category, url, related_stocks, sentiment_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (sid, "삼성과 SK, LG 동반 강세",
                  "삼성전자와 SK하이닉스, LG전자가 동반 상승했다",
                  datetime(2026, 6, 15, 10, 0), "test", "산업",
                  "https://example.invalid/multi", "", 0))

        conn.commit()
    finally:
        db._put_connection(conn)

    reprocess(db, apply=True, only_news_id=sid)

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT impact_score, related_stocks FROM news_reprocessed WHERE news_id = %s",
                        (sid,))
            impact, stocks = cur.fetchone()
            assert impact > 0, f"Impact score should be > 0 for multi-stock mention: {impact}"
            # 여러 종목이 추출되었는지 확인
            stock_list = stocks.split(",") if stocks else []
            assert len(stock_list) > 1, f"Should extract multiple stocks: {stock_list}"
    finally:
        conn.rollback()
        db._put_connection(conn)

    # 청소
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news_reprocessed WHERE news_id = %s", (sid,))
            cur.execute("DELETE FROM news WHERE news_id = %s", (sid,))
        conn.commit()
    finally:
        db._put_connection(conn)
