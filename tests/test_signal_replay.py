"""신호 재현 — 과거 거래일의 신호를 point-in-time 으로 다시 만든다.

미래 참조가 이 파일의 주제다. 창 경계를 한 칸 잘못 잡으면 백테스트는
조용히 훌륭한 성과를 낸다.
"""
from datetime import date, datetime

import pytest

from news_scraper.backtest.signal_replay import (
    TABLE,
    WINDOW_KINDS,
    ensure_table,
    replay_day,
    replay_range,
    trading_days,
    window_bounds,
)

pytestmark = pytest.mark.db

D = date(2026, 6, 15)      # 월요일


def test_as_of_는_언제나_거래일_09시다():
    for kind in WINDOW_KINDS:
        _, as_of = window_bounds(D, kind)

        assert as_of == datetime(2026, 6, 15, 9, 0)


def test_생산_창은_그날_자정부터다():
    start, _ = window_bounds(D, "prod_calendar")

    assert start == datetime(2026, 6, 15, 0, 0)


def test_섹터_창은_직전_평일_1530_부터다():
    start, _ = window_bounds(D, "sector_1530")

    assert start == datetime(2026, 6, 12, 15, 30)   # 금요일


def test_두_창의_차이는_시작점_하나뿐이다():
    prod_start, prod_as_of = window_bounds(D, "prod_calendar")
    sect_start, sect_as_of = window_bounds(D, "sector_1530")

    assert prod_as_of == sect_as_of
    assert sect_start < prod_start


def test_알_수_없는_창은_거부한다():
    with pytest.raises(ValueError):
        window_bounds(D, "made_up")


def test_명시적_이전_거래일이_있으면_그날_1530_부터다():
    """2026-08-18 의 달력상 직전 평일(8/17, 월)은 대체공휴일이라 거래일이
    아니다. 실제 이전 거래일은 8/14(금) — prev_session 을 주면 그걸 써야
    한다(prev_weekday() 의 달력 근사가 아니라)."""
    start, as_of = window_bounds(date(2026, 8, 18), "sector_1530",
                                  prev_session=date(2026, 8, 14))

    assert start == datetime(2026, 8, 14, 15, 30)
    assert as_of == datetime(2026, 8, 18, 9, 0)


def test_trading_days_는_주말을_뺀다(db):
    days = trading_days(db, date(2026, 6, 12), date(2026, 6, 16))  # 금~화, 주말 포함

    assert all(d.weekday() < 5 for d in days)
    assert date(2026, 6, 13) not in days   # 토
    assert date(2026, 6, 14) not in days   # 일
    assert date(2026, 6, 12) in days
    assert date(2026, 6, 15) in days


def test_재현된_신호에_as_of_이후_뉴스가_섞이지_않는다(db):
    """news_reprocessed 를 직접 조회해 창 밖 뉴스가 없음을 확인한다.

    all() 은 빈 리스트에서도 참이 되므로, rows 가 실제로 있다는 것도
    같이 확인해야 이 테스트가 검증력을 가진다.
    """
    from news_scraper.backtest.signal_replay import _news_in_window

    start, as_of = window_bounds(D, "sector_1530")
    rows = _news_in_window(db, start, as_of)

    assert len(rows) > 0
    assert all(start < r["published_at"] <= as_of for r in rows)


def test_두_창의_뉴스_수가_다르다_밤새_뉴스가_있는_날(db):
    """이 비교 전체가 성립하려면 두 창이 실제로 다른 뉴스 집합을 봐야 한다."""
    from news_scraper.backtest.signal_replay import _news_in_window

    prod_start, prod_as_of = window_bounds(D, "prod_calendar")
    sect_start, sect_as_of = window_bounds(D, "sector_1530")

    prod_count = len(_news_in_window(db, prod_start, prod_as_of))
    sect_count = len(_news_in_window(db, sect_start, sect_as_of))

    assert prod_count != sect_count
    assert sect_count > prod_count   # 밤새(D-1 장마감~자정) 뉴스가 더 잡힌다


def test_replay_day_가_실제_거래일에_대해_행을_만든다(db):
    rows = replay_day(db, D, "sector_1530")

    assert len(rows) > 0   # 비어 있으면 아래 필드 검증이 아무것도 지키지 못한다
    for r in rows:
        assert r["trade_date"] == D
        assert r["window_kind"] == "sector_1530"
        assert r["as_of"] == datetime(2026, 6, 15, 9, 0)
        assert isinstance(r["composite_score"], (int, float))


def test_replay_range_는_사라진_종목의_이전_행을_지운다(db):
    """news_reprocessed 가 바뀌어 어떤 종목이 이번 창에서 더는 나오지
    않으면, 이전 실행이 남긴 그 종목의 행도 지워져야 한다.

    실제 결과에는 절대 나오지 않을 가짜 종목코드로 «이전 실행의 잔재»를
    미리 심어 두고, replay_range 가 그걸 청소하는지 본다.
    """
    ensure_table(db)
    stale_code = "999999"

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {TABLE}
                  (trade_date, window_kind, as_of, stock_code, news_count,
                   avg_sentiment, adjusted_sentiment, avg_overall,
                   volume_signal, composite_score, code_version)
                VALUES (%s, %s, %s, %s, 1, 0, 0, 0, 0, 0, 'stale-test')
                ON CONFLICT (trade_date, window_kind, stock_code) DO NOTHING
            """, (D, "sector_1530", datetime(2026, 6, 15, 9, 0), stale_code))
        conn.commit()
    finally:
        db._put_connection(conn)

    replay_range(db, D, D, apply=True)

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT count(*) FROM {TABLE}
                            WHERE trade_date = %s AND window_kind = %s AND stock_code = %s""",
                        (D, "sector_1530", stale_code))
            remaining = cur.fetchone()[0]

            cur.execute(f"""SELECT stock_code, count(*) FROM {TABLE}
                            WHERE trade_date = %s
                            GROUP BY trade_date, window_kind, stock_code
                            HAVING count(*) > 1""", (D,))
            dupes = cur.fetchall()
        conn.rollback()
    finally:
        db._put_connection(conn)

    assert remaining == 0
    assert dupes == []
