"""수익 결합 — 신호에 이후 수익을 붙인다.

기업행위(±30%) 판정은 load_returns 안에서 returns_1d(종가-전일종가)
창으로만 한다 — 이 규칙은 «전일 종가 대비 하루» 를 재는 규칙이라 시가를
기준점으로 삼는 ret_h0 나, 여러 날을 누적하는 ret_h1/ret_h5 에는 바인딩
하지 않는다(2세션·6세션 누적은 연속 상한가만으로도 30% 를 훌쩍 넘는 게
정상이다). attach_returns 는 이 판정을 다시 하지 않는다 — 입력을 그대로
믿고 병합·차감만 한다.
"""
from datetime import date

import pandas as pd
import pytest

from news_scraper.backtest.returns import CORPORATE_ACTION_LIMIT, attach_returns


def _signals():
    return pd.DataFrame([
        {"trade_date": date(2026, 6, 15), "window_kind": "sector_1530",
         "stock_code": "A", "composite_score": 0.9},
        {"trade_date": date(2026, 6, 15), "window_kind": "sector_1530",
         "stock_code": "B", "composite_score": 0.1},
    ])


def _rets(a_h1, b_h1):
    return pd.DataFrame([
        {"trade_date": date(2026, 6, 15), "stock_code": "A",
         "ret_h0": 0.0, "ret_h1": a_h1, "ret_h5": 0.0},
        {"trade_date": date(2026, 6, 15), "stock_code": "B",
         "ret_h0": 0.0, "ret_h1": b_h1, "ret_h5": 0.0},
    ])


def test_횡단면_평균을_뺀다():
    out = attach_returns(_signals(), _rets(0.04, 0.02))

    got = dict(zip(out["stock_code"], out["excess_h1"]))
    assert got["A"] == pytest.approx(0.01)    # 0.04 - 평균 0.03
    assert got["B"] == pytest.approx(-0.01)


def test_attach_returns는_극한값을_지우지_않는다():
    """기업행위 판정은 load_returns 의 몫이다(모듈 docstring). attach_returns
    는 입력을 그대로 믿는다 — ret_h0/h1/h5 가 ±30% 를 넘어도(연속
    상한가로 인한 정상적인 누적수익 포함) 지우면 안 된다. 이전 라운드에
    있던 «컬럼 단위 null» 안전망은 outcome-dependent truncation 이라
    삭제했다 — 이 테스트가 그 회귀를 잡는다."""
    sig = _signals()
    rets = pd.DataFrame([
        {"trade_date": date(2026, 6, 15), "stock_code": "A",
         "ret_h0": 0.55, "ret_h1": 0.60, "ret_h5": 0.70},
        {"trade_date": date(2026, 6, 15), "stock_code": "B",
         "ret_h0": 0.0, "ret_h1": 0.0, "ret_h5": 0.0},
    ])

    out = attach_returns(sig, rets)

    row_a = out[out["stock_code"] == "A"].iloc[0]
    assert row_a["excess_h0"] == pytest.approx(0.55 - 0.275)   # 평균(0.55, 0.0)
    assert row_a["excess_h1"] == pytest.approx(0.60 - 0.30)
    assert row_a["excess_h5"] == pytest.approx(0.70 - 0.35)


def test_수익이_없는_신호는_빠진다():
    """신호만 있고 수익이 없으면 빠지고(B), 수익만 있고 신호가 없는 유령
    종목(Z, outer/right 조인이면 새어드는 경우)도 들어오면 안 된다.

    주의(리뷰에서 받아들여진 한계): how="inner" 를 how="left" 로 바꿔도
    이 테스트는 여전히 통과한다 — B 는 left 조인이어도 ret_h* 전부 NaN
    이 되어 마지막 notna-any 필터가 결과적으로 같은 값을 만들기 때문에,
    이 파이프라인에서는 inner 와 (left + 그 필터) 가 출력상 수학적으로
    동치다. 대신 «수익만 있고 신호가 없는» 반대 케이스(outer/right
    조인이면 새는 것)로 조인 방향을 검증한다."""
    rets = _rets(0.04, 0.02)
    rets = rets[rets["stock_code"] == "A"]
    rets = pd.concat([rets, pd.DataFrame([
        {"trade_date": date(2026, 6, 15), "stock_code": "Z",
         "ret_h0": 0.01, "ret_h1": 0.01, "ret_h5": 0.01},
    ])], ignore_index=True)

    out = attach_returns(_signals(), rets)

    assert set(out["stock_code"]) == {"A"}


def test_창이_다르면_따로_평균낸다():
    """window_kind 뿐 아니라 trade_date 도 그룹 키다 — 둘 다 맞아야 같은
    그룹이다. 06-16 sector_1530(C/D) 을 더해 날짜를 안 가르면 06-15 A 의
    초과수익이 오염되는지까지 잡는다."""
    day1 = _signals()
    other_window = day1.copy()
    other_window["window_kind"] = "prod_calendar"
    other_window = other_window[other_window["stock_code"] == "A"]

    day2 = pd.DataFrame([
        {"trade_date": date(2026, 6, 16), "window_kind": "sector_1530",
         "stock_code": "C", "composite_score": 0.5},
        {"trade_date": date(2026, 6, 16), "window_kind": "sector_1530",
         "stock_code": "D", "composite_score": 0.5},
    ])
    rets_day2 = pd.DataFrame([
        {"trade_date": date(2026, 6, 16), "stock_code": "C",
         "ret_h0": 0.0, "ret_h1": 0.10, "ret_h5": 0.0},
        {"trade_date": date(2026, 6, 16), "stock_code": "D",
         "ret_h0": 0.0, "ret_h1": 0.00, "ret_h5": 0.0},
    ])

    signals = pd.concat([day1, other_window, day2], ignore_index=True)
    rets = pd.concat([_rets(0.04, 0.02), rets_day2], ignore_index=True)

    out = attach_returns(signals, rets)

    prod = out[out["window_kind"] == "prod_calendar"]
    assert prod["excess_h1"].iloc[0] == pytest.approx(0.0)   # 혼자면 초과수익 0

    a = out[(out["stock_code"] == "A") & (out["window_kind"] == "sector_1530")].iloc[0]
    # 06-16 sector_1530(C/D, 평균 0.05)과 섞이면 0.04-0.045 가 되어 버린다.
    assert a["excess_h1"] == pytest.approx(0.01)


class _FakeCursor:
    """load_returns 의 ±30% 경계(>, >= 아님)를 실DB 없이 못박기 위한
    최소 더미. get_connection()→cursor()→execute()→fetchall() 만
    흉내낸다 — SQL 자체는 실행하지 않고 미리 만든 행을 그대로 돌려준다."""

    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        pass

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)

    def rollback(self):
        pass


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def get_connection(self):
        return _FakeConn(self._rows)

    def _put_connection(self, conn):
        pass


def test_제한폭_경계값은_남긴다():
    """기업행위 판정은 load_returns 에서만 한다(모듈 docstring) —
    attach_returns 는 더 이상 이 규칙을 보지 않으므로(이전 라운드에서
    삭제) 경계도 load_returns 에서 못박는다. 규칙은 «초과»(>) 다 —
    경계값 자체는 기업행위가 아니다. 실DB 로는 max_abs_move 가 정확히
    0.30 인 행을 고를 수 없어(부동소수 실측값이 정확히 그 값일 확률이
    0에 가깝다) DB 커서를 흉내낸 더미로 SQL 결과 행을 직접 주입한다."""
    from news_scraper.backtest.returns import load_returns

    d = date(2026, 6, 15)
    # (stock_code, date, open, h0.close, h1.close, h5.close, max_abs_move, returns_1d)
    rows = [
        ("A", d, 10000.0, 10100.0, 10200.0, 10300.0, CORPORATE_ACTION_LIMIT, 0.01),
        ("B", d, 10000.0, 10100.0, 10200.0, 10300.0, CORPORATE_ACTION_LIMIT + 1e-6, 0.01),
    ]

    out = load_returns(_FakeDB(rows), d, d)

    assert "A" in set(out["stock_code"])       # 경계값 자체는 남는다
    assert "B" not in set(out["stock_code"])   # 경계를 살짝 넘으면 빠진다


@pytest.mark.db
def test_실DB_조인이_0행을_내지_않는다(db):
    """daily_prices.date 는 TEXT 'YYYY-MM-DD', stock_code 는 space-padded 일
    수 있다. 형식을 틀리면 조인 결과가 «조용히» 0행이 된다 — 설계 중 실제로
    겪었다."""
    from news_scraper.backtest.returns import load_returns

    out = load_returns(db, date(2026, 6, 1), date(2026, 6, 30))

    assert len(out) > 0
    assert out["ret_h0"].notna().sum() > 0
    assert out["ret_h1"].notna().sum() > 0
    assert isinstance(out["trade_date"].iloc[0], date)


@pytest.mark.db
def test_실DB_수익에_기업행위가_남아있지_않다(db):
    """load_returns 가 실제로 지키는 규칙은 «ret_h0 가 ±30% 안» 이 아니라
    «returns_1d 로 판정한 기업행위 창에 걸리지 않는다» 이다(상한가 세션은
    ret_h0 가 30% 를 넘을 수 있고 그건 정상이다). 독립적으로 같은 정의를
    다시 계산해, 살아남은 관측 중 그 창에 걸리는 게 없는지를 검증한다."""
    from news_scraper.backtest.returns import load_returns

    start, end = date(2026, 6, 1), date(2026, 6, 30)
    out = load_returns(db, start, end)
    assert len(out) > 0

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                WITH p AS (
                    SELECT trim(stock_code) AS stock_code, date, returns_1d,
                           row_number() OVER (PARTITION BY trim(stock_code)
                                              ORDER BY date) rn
                    FROM daily_prices
                    WHERE date >= %s AND date <= %s
                )
                SELECT p.stock_code, p.date,
                       GREATEST(
                         COALESCE(abs(p.returns_1d), 0),
                         COALESCE(MAX(abs(p.returns_1d)) OVER (
                             PARTITION BY p.stock_code ORDER BY p.rn
                             ROWS BETWEEN 1 FOLLOWING AND 5 FOLLOWING), 0)
                       ) AS max_abs_move
                FROM p
            """, (start.isoformat(), end.isoformat()))
            window = {(code, pd.Timestamp(d).date()): m for code, d, m in cur.fetchall()}
    finally:
        conn.rollback()
        db._put_connection(conn)

    bad = [(row.stock_code, row.trade_date) for row in out.itertuples()
           if window.get((row.stock_code, row.trade_date), 0.0) > CORPORATE_ACTION_LIMIT]
    assert bad == []


@pytest.mark.db
def test_실DB_전일종가없는_신규상장일은_빠진다(db):
    """returns_1d 가 NULL(전일 종가 없음, 신규상장 등)인 진입일은 시가 대비
    판단 근거가 없어 뺀다 — returns_1d 창 검사와는 별개의 규칙이다(그
    창 검사는 NULL 을 0 으로 취급해 통과시켜 버린다)."""
    from news_scraper.backtest.returns import load_returns

    start, end = date(2026, 6, 1), date(2026, 6, 30)
    out = load_returns(db, start, end)

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT trim(stock_code), date FROM daily_prices
                WHERE date >= %s AND date <= %s
                  AND returns_1d IS NULL AND open > 0 AND close > 0
            """, (start.isoformat(), end.isoformat()))
            null_days = {(code.strip(), pd.Timestamp(d).date()) for code, d in cur.fetchall()}
    finally:
        conn.rollback()
        db._put_connection(conn)

    assert len(null_days) > 0   # 실측: 2026-06 에 153890(06-29)·475040(06-30) 2건
    leaked = [(row.stock_code, row.trade_date) for row in out.itertuples()
              if (row.stock_code, row.trade_date) in null_days]
    assert leaked == []


@pytest.mark.db
def test_요청범위_마지막날_신호도_h5를_받는다(db):
    """start==end 로 좁혀도(요청 범위 마지막 날) h5(5거래일 뒤 종가)를
    구할 수 있어야 한다 — end 를 가격 조회 상한으로 그대로 쓰면 이후
    거래일이 조회 대상에서 빠져 h1/h5 가 전부 NaN 이 된다."""
    from news_scraper.backtest.returns import load_returns

    entry_day = date(2026, 6, 1)   # 실측: 이후 최소 5거래일(06-09까지)이
                                    # daily_prices 에 있다 — 15일 패딩 안.
    out = load_returns(db, entry_day, entry_day)

    assert len(out) > 0
    assert out["ret_h5"].notna().sum() > 0
    assert set(out["trade_date"].unique()) == {entry_day}


@pytest.mark.db
def test_설연휴_뒤_5거래일도_패딩_안에_들어온다(db):
    """실측(trading_days(), 2026-01-01~09-11): 진입일→5거래일뒤 캘린더
    갭의 최댓값이 2026-02-11→02-23(12일, 설 연휴+주말)이었다 — 옛
    _FORWARD_PAD_DAYS=10 이었다면 이 진입일의 h5 를 못 구했다. 그
    최악 사례를 직접 겨냥해 패딩이 실제로 충분한지 확인한다."""
    from news_scraper.backtest.returns import load_returns

    entry_day = date(2026, 2, 11)
    out = load_returns(db, entry_day, entry_day)

    assert len(out) > 0
    assert out["ret_h5"].notna().sum() > 0
