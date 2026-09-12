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

# trading_days() 의 행수 필터를 실 데이터와 겹치지 않게 검증하기 위한 센티널.
# 실 데이터 범위(2021-01-04~2026-09-11) 밖의 평일을 쓴다.
_LOW_ROW_SENTINEL_DATE = "2027-03-02"     # 화요일
_LOW_ROW_SENTINEL_CODE = "999998"

# 요일 필터를 행수 필터와 분리해서 검증하기 위한 센티널 — 행이 충분한(≥
# MIN_ROWS_PER_DAY) «가짜» 주말. 실 데이터의 주말은 항상 행이 없거나
# 잡음 1행뿐이라(2026-01-11), 행수 필터만으로 걸러지지 않는 주말 사례가 없다.
_BUSY_WEEKEND_DATE = "2027-04-03"         # 토요일
_BUSY_WEEKEND_CODES = [f"9997{i:02d}" for i in range(150)]


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
    """2026-01-11(일요일) 은 daily_prices 에 잡음성 1행이 있다 — 그러니
    후보로는 실제로 걸리고, 필터가 그걸 걷어내는지를 봐야 이 테스트가
    뭔가를 지킨다(이전엔 후보 날짜 자체가 daily_prices 에 없어 공허했다).

    다만 이 날은 행수도 1개뿐이라 요일 필터를 없애도 행수 필터가 대신
    걸러낸다 — 요일 필터 자체를 따로 못박는 건 아래
    test_행수가_충분해도_주말은_거래일에서_빠진다 쪽이다.
    """
    days = trading_days(db, date(2026, 1, 9), date(2026, 1, 13))   # 금~화, 일요일 잡음행 포함

    assert date(2026, 1, 11) not in days   # 일요일, daily_prices 에 실제로 1행 있음
    assert date(2026, 1, 9) in days
    assert date(2026, 1, 12) in days
    assert date(2026, 1, 13) in days


@pytest.fixture
def busy_weekend(db):
    """행 수는 충분한(≥MIN_ROWS_PER_DAY) «가짜» 주말 하루. 요일 필터를
    행수 필터와 분리해서 검증하려면 필요하다 — 실 데이터의 주말은 전부
    행이 없거나(그래서 후보가 안 됨) 1행뿐(그래서 행수 필터에도 걸림)이라,
    요일 필터가 «유일하게» 배제하는 자연 사례가 없다.
    """
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE date = %s", (_BUSY_WEEKEND_DATE,))
            for code in _BUSY_WEEKEND_CODES:
                cur.execute("""INSERT INTO daily_prices (stock_code, date, close)
                               VALUES (%s, %s, 1000)""", (code, _BUSY_WEEKEND_DATE))
        conn.commit()
    finally:
        db._put_connection(conn)

    yield

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE date = %s", (_BUSY_WEEKEND_DATE,))
        conn.commit()
    finally:
        db._put_connection(conn)


def test_행수가_충분해도_주말은_거래일에서_빠진다(db, busy_weekend):
    days = trading_days(db, date(2027, 3, 31), date(2027, 4, 6))

    assert date(2027, 4, 3) not in days   # 행이 150개나 있어도 토요일이면 빠져야 한다


@pytest.fixture
def low_row_weekday(db):
    """MIN_ROWS_PER_DAY 미달인 «평일». 실 데이터에는 이런 날이 없다 — 유일한
    미달일(2026-01-11)이 일요일이라 행수 필터와 요일 필터를 구분하지 못한다.
    그래서 평일 하나에 1행만 심어 행수 필터 자체를 따로 검증한다.
    """
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE date = %s AND stock_code = %s",
                        (_LOW_ROW_SENTINEL_DATE, _LOW_ROW_SENTINEL_CODE))
            cur.execute("""INSERT INTO daily_prices (stock_code, date, close)
                           VALUES (%s, %s, 1000)""",
                        (_LOW_ROW_SENTINEL_CODE, _LOW_ROW_SENTINEL_DATE))
        conn.commit()
    finally:
        db._put_connection(conn)

    yield

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE date = %s AND stock_code = %s",
                        (_LOW_ROW_SENTINEL_DATE, _LOW_ROW_SENTINEL_CODE))
        conn.commit()
    finally:
        db._put_connection(conn)


def test_행수가_MIN_ROWS_PER_DAY_미달인_평일은_거래일에서_빠진다(db, low_row_weekday):
    days = trading_days(db, date(2027, 2, 27), date(2027, 3, 5))

    assert date(2027, 3, 2) not in days   # 화요일이지만 1행뿐 — 요일 필터는 통과하지만 행수 필터에 걸려야 한다


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


def test_진짜_이전_거래일을_쓰면_replay_day_결과가_늘어난다(db):
    """2026-08-18 은 대체공휴일(8/17) 다음 거래일이다. prev_session 을
    안 주면(구 근사, prev_weekday()=8/17) 밤새 뉴스가 크게 빠진다. 실제
    이전 거래일(8/14)을 넘기면 결과가 늘어야 한다 — _news_in_window 가
    아니라 replay_day 를 직접 불러서 이번에 고친 경로(fix 2) 전체를 태운다.
    """
    naive = replay_day(db, date(2026, 8, 18), "sector_1530")
    fixed = replay_day(db, date(2026, 8, 18), "sector_1530", prev_session=date(2026, 8, 14))

    assert len(fixed) > len(naive)


def test_replay_day_가_실제_거래일에_대해_행을_만든다(db):
    rows = replay_day(db, D, "sector_1530")

    assert len(rows) > 0   # 비어 있으면 아래 필드 검증이 아무것도 지키지 못한다
    for r in rows:
        assert r["trade_date"] == D
        assert r["window_kind"] == "sector_1530"
        assert r["as_of"] == datetime(2026, 6, 15, 9, 0)
        assert isinstance(r["composite_score"], (int, float))


@pytest.fixture
def backtest_signal_cleanup(db):
    """replay_range(apply=True) 로 실 backtest_signal 에 쓰는 테스트용 청소기.

    trade_date 를 append 해 두면 테스트가 실패해도(yield 뒤는 항상 돈다)
    그 날짜의 모든 행(두 창 다)을 지운다 — 공유 표에 테스트 잔재를 남기지 않는다.
    """
    trade_dates = []

    yield trade_dates

    if not trade_dates:
        return
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE trade_date = ANY(%s)", (trade_dates,))
        conn.commit()
    finally:
        db._put_connection(conn)


def test_replay_range_는_사라진_종목의_이전_행을_지운다(db, backtest_signal_cleanup):
    """news_reprocessed 가 바뀌어 어떤 종목이 이번 창에서 더는 나오지
    않으면, 이전 실행이 남긴 그 종목의 행도 지워져야 한다.

    실제 결과에는 절대 나오지 않을 가짜 종목코드로 «이전 실행의 잔재»를
    미리 심어 두고, replay_range 가 그걸 청소하는지 본다. (PK 는 중복
    자체를 막아 주지만 «사라진 종목의 잔존» 은 못 막는다 — 그게 fix 5 다.)
    """
    ensure_table(db)
    backtest_signal_cleanup.append(D)
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
        conn.rollback()
    finally:
        db._put_connection(conn)

    assert remaining == 0
