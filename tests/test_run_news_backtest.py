"""run_news_backtest.py 의 표본 크기 헬퍼 — daily_ic/hit_rate/quantile_returns

를 «재구현» 하지 않고 그 함수들이 실제로 채택한 표본을 그대로 세는지 본다.

이 세 헬퍼(_ic_obs_count/_hit_rate_stats/_quantile_days_used)는 metrics.py
함수의 반환값만으로는 관측치·거래일 수를 끝까지 얻을 수 없어서(daily_ic 는
날짜→IC 값만, quantile_returns 는 버킷 집계만 돌려준다) 남겨 둔 것들이다 —
그래서 Task 7 리뷰가 "논리 없이 테스트만 없는 건 안 된다" 며 요구한 대로
여기서 직접 핀한다. run_news_backtest.py 자체(조립·출력)에는 별도 테스트를
두지 않는다(Task 7 브리프가 그렇게 지시했다) — 이 파일은 «그 조립이 쓰는
계산 헬퍼» 만 다룬다.
"""
from datetime import date

import pandas as pd

from news_scraper.backtest.metrics import daily_ic
from scripts.run_news_backtest import (
    _hit_rate_stats,
    _ic_obs_count,
    _quantile_days_used,
)

DAY1 = date(2026, 6, 1)
DAY2 = date(2026, 6, 2)


def _rows(day, pairs):
    return [
        {"trade_date": day, "composite_score": s, "excess_h1": r}
        for s, r in pairs
    ]


def test_ic_obs_count은_ic_인덱스에_속한_날의_유효행만_센다():
    """day1 은 4행이 유효(그중 점수·수익 다 있는 3개+1개, MIN_STOCKS_PER_DAY=3
    이상)해 daily_ic 의 인덱스에 남는다. day2 는 유효행이 2개뿐이라
    MIN_STOCKS_PER_DAY(3) 미달로 daily_ic 인덱스에서 빠진다 — day2 의 2개는
    관측치 합계에 «포함되면 안 된다»."""
    df = pd.DataFrame(
        _rows(DAY1, [(0.1, 0.01), (0.2, 0.02), (0.3, -0.01), (0.4, 0.05)])
        + _rows(DAY2, [(0.5, 0.01), (0.6, -0.02)])
    )

    ic = daily_ic(df)
    assert list(ic.index) == [DAY1]  # day2 는 표본 미달로 제외됐는지 먼저 확인

    assert _ic_obs_count(df, ic) == 4


def test_ic_obs_count은_NaN_행을_관측치에서_뺀다():
    """day1 에 excess_h1 이 NaN 인 행이 하나 섞여 있으면(예: h5 만 있고 h1
    가격이 아직 없는 진입) 그 행은 daily_ic 계산에도 안 쓰이므로 관측치
    합계에서도 빠져야 한다."""
    rows = _rows(DAY1, [(0.1, 0.01), (0.2, 0.02), (0.3, -0.01), (0.4, 0.05)])
    rows.append({"trade_date": DAY1, "composite_score": 0.9, "excess_h1": None})
    df = pd.DataFrame(rows)

    ic = daily_ic(df)

    assert _ic_obs_count(df, ic) == 4  # NaN 행(5번째)은 세지 않는다


def test_hit_rate_stats는_거래일별_top_n_행수를_합산한다():
    """day1 은 5종목이라 top_n=2 면 2행이 뽑히고, day2 는 1종목뿐이라
    top_n=2 를 채우지 못해 1행만 뽑힌다 — 합계는 2+1=3, 거래일은 2."""
    df = pd.DataFrame(
        _rows(DAY1, [(0.9, 0.01), (0.7, -0.01), (0.5, 0.02),
                     (0.3, -0.02), (0.1, 0.03)])
        + _rows(DAY2, [(0.6, 0.01)])
    )

    n, days = _hit_rate_stats(df, "excess_h1", top_n=2)

    assert n == 3
    assert days == 2


def test_hit_rate_stats는_NaN_행을_뽑기_전에_제외한다():
    """점수는 있지만 수익이 NaN인 행은 top_n 선발 대상에서 빠져야 한다 —
    안 그러면 값 없는 종목이 «뽑힌 행» 으로 잘못 세어진다."""
    rows = _rows(DAY1, [(0.9, 0.01), (0.7, -0.01)])
    rows.append({"trade_date": DAY1, "composite_score": 0.99, "excess_h1": None})
    df = pd.DataFrame(rows)

    n, days = _hit_rate_stats(df, "excess_h1", top_n=10)

    assert n == 2  # NaN 행(점수 0.99)은 top_n 안에 있어도 제외
    assert days == 1


def test_quantile_days_used는_score_고유값이_n_q_이상인_날만_센다():
    """day1 은 서로 다른 점수 5개(n_q=5 충족)이고, day2 는 5행이지만 점수가
    3종류뿐이라(동점 다수) n_q=5 를 못 채운다 — quantile_returns 도 이런 날은
    통째로 건너뛰므로(모듈 docstring 참고) 거래일 카운트에서 빠져야 한다."""
    df = pd.DataFrame(
        _rows(DAY1, [(0.1, 0.01), (0.2, 0.02), (0.3, -0.01),
                     (0.4, 0.03), (0.5, -0.02)])
        + _rows(DAY2, [(0.1, 0.01), (0.1, 0.02), (0.2, -0.01),
                       (0.2, 0.03), (0.3, -0.02)])
    )

    days = _quantile_days_used(df, "composite_score", "excess_h1", n_q=5)

    assert days == 1


def test_quantile_days_used는_NaN_행을_고유값_판정_전에_제외한다():
    """점수가 유니크해도 수익이 NaN이면 그 행은 quantile_returns 의 입력에서
    먼저 dropna 되므로, nunique 판정도 그 «이후» 기준으로 해야 한다."""
    rows = _rows(DAY1, [(0.1, 0.01), (0.2, 0.02), (0.3, -0.01), (0.4, 0.03)])
    rows.append({"trade_date": DAY1, "composite_score": 0.5, "excess_h1": None})
    df = pd.DataFrame(rows)

    # NaN 행을 포함하면 점수 고유값이 5개(>=5)지만, dropna 후에는 4개뿐이다.
    days = _quantile_days_used(df, "composite_score", "excess_h1", n_q=5)

    assert days == 0
