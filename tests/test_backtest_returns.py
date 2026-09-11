"""수익 결합 — 신호에 이후 수익을 붙인다.

returns_1d 는 수정주가가 아니다. 거래소 가격제한폭 ±30% 는 «종가 대
전일종가» 에 걸리는 규칙이다 — «시가 대 종가»(ret_h0) 에는 이 규칙이
직접 적용되지 않는다. 상한가 근처에서 열려 하한가 근처에서 닫히는 날은
이 규칙을 어기지 않고도 시가 대비로는 30% 를 넘을 수 있고, 그런 날이
바로 뉴스 신호가 있다면 가장 크게 반응했을 날이다 — 그래서 기업행위
판정은 returns_1d(종가-종가) 창에만 건다.
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


def test_기업행위_horizon만_NaN이_되고_다른_horizon은_남는다():
    """±30% 를 넘는 건 그 horizon 만 못 믿는 것이다 — 같은 진입(시가)의
    다른 horizon 은 이미 실현된 유효한 값이니 같이 버리면 안 된다."""
    out = attach_returns(_signals(), _rets(0.55, 0.02))

    row_a = out[out["stock_code"] == "A"].iloc[0]
    assert pd.isna(row_a["excess_h1"])       # 못 믿는 horizon
    assert row_a["excess_h0"] == pytest.approx(0.0)   # 다른 horizon 은 살아있다
    assert "B" in set(out["stock_code"])


def test_h5만_기업행위여도_h0_h1은_남는다():
    """D+4 에 분할이 나면 h5 만 오염된다 — h0/h1 은 진입 당일·다음날 이미
    실현된 값이라 여전히 유효하다(브리핑 원래 취지: 컬럼 단위 처리)."""
    sig = _signals()
    rets = pd.DataFrame([
        {"trade_date": date(2026, 6, 15), "stock_code": "A",
         "ret_h0": 0.01, "ret_h1": 0.02, "ret_h5": 0.55},
        {"trade_date": date(2026, 6, 15), "stock_code": "B",
         "ret_h0": 0.0, "ret_h1": 0.0, "ret_h5": 0.0},
    ])

    out = attach_returns(sig, rets)

    row_a = out[out["stock_code"] == "A"].iloc[0]
    assert pd.notna(row_a["excess_h0"])
    assert pd.notna(row_a["excess_h1"])
    assert pd.isna(row_a["excess_h5"])
    assert "A" in set(out["stock_code"])   # 행 자체는 살아있다


def test_h0에는_제한폭을_적용하지_않는다():
    """±30% 는 «종가 대 전일종가» 규칙이다 — «시가 대 종가»(ret_h0) 는
    대상이 아니다. 상한가 근처에서 열려 하한가 근처에서 닫히는 날은 이
    규칙을 어기지 않고도 ret_h0 가 30% 를 넘을 수 있고, 뉴스 신호가
    있었다면 가장 크게 반응했을 그 날을 지우면 안 된다."""
    sig = _signals()
    rets = pd.DataFrame([
        {"trade_date": date(2026, 6, 15), "stock_code": "A",
         "ret_h0": 0.55, "ret_h1": 0.02, "ret_h5": 0.0},
        {"trade_date": date(2026, 6, 15), "stock_code": "B",
         "ret_h0": 0.0, "ret_h1": 0.0, "ret_h5": 0.0},
    ])

    out = attach_returns(sig, rets)

    row_a = out[out["stock_code"] == "A"].iloc[0]
    assert pd.notna(row_a["excess_h0"])
    assert row_a["excess_h0"] == pytest.approx(0.55 - 0.275)   # 평균(0.55, 0.0)


def test_제한폭_경계값은_남긴다():
    out = attach_returns(_signals(), _rets(CORPORATE_ACTION_LIMIT, 0.02))

    assert "A" in set(out["stock_code"])


def test_수익이_없는_신호는_빠진다():
    """신호만 있고 수익이 없으면 빠지고(B), 수익만 있고 신호가 없는 유령
    종목(Z, outer/right 조인이면 새어드는 경우)도 들어오면 안 된다."""
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
                                    # daily_prices 에 있다 — 10일 패딩 안.
    out = load_returns(db, entry_day, entry_day)

    assert len(out) > 0
    assert out["ret_h5"].notna().sum() > 0
    assert set(out["trade_date"].unique()) == {entry_day}
