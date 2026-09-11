"""run_news_backtest.py 의 표본 크기 헬퍼 — daily_ic/hit_rate/quantile_returns

를 «재구현» 하지 않고 그 함수들이 실제로 채택한 표본을 그대로 세는지 본다.

이 헬퍼들(_ic_obs_count/_hit_rate_stats/_quantile_days_used)은 metrics.py
함수의 반환값만으로는 관측치·거래일 수를 끝까지 얻을 수 없어서(daily_ic 는
날짜→IC 값만, quantile_returns 는 버킷 집계만 돌려준다) 남겨 둔 것들이다 —
그래서 Task 7 리뷰가 "논리 없이 테스트만 없는 건 안 된다" 며 요구한 대로
여기서 직접 핀한다.

_cross_section_stats/_hit_rate_wide_days_only 는 최종 전체브랜치 리뷰 C1
(표본 크기가 안 보이는 문제)의 수정이다 — 이 둘도 «조립·출력» 이 아니라
계산 로직이라 여기서 다룬다. run_news_backtest.py 의 나머지(조립·출력)에는
별도 테스트를 두지 않는다(Task 7 브리프가 그렇게 지시했다).
"""
from datetime import date

import pandas as pd
import pytest

from news_scraper.backtest.metrics import daily_ic
from scripts.run_news_backtest import (
    _cross_section_stats,
    _hit_rate_stats,
    _hit_rate_wide_days_only,
    _ic_obs_count,
    _load_signals,
    _quantile_days_used,
)

DAY1 = date(2026, 6, 1)
DAY2 = date(2026, 6, 2)
DAY3 = date(2026, 6, 3)


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


def test_cross_section_stats는_일별_유효_종목수의_분포를_낸다():
    """day1=2종목, day2=4종목, day3=6종목 — 유효행(점수·수익 다 있음) 기준
    median/25백분위/75백분위가 pandas 선형보간과 일치하는지 손으로 고정한다."""
    df = pd.DataFrame(
        _rows(DAY1, [(0.1, 0.01), (0.2, 0.02)])
        + _rows(DAY2, [(0.1, 0.01), (0.2, 0.02), (0.3, 0.03), (0.4, 0.04)])
        + _rows(DAY3, [(0.1, 0.01), (0.2, 0.02), (0.3, 0.03),
                       (0.4, 0.04), (0.5, 0.05), (0.6, 0.06)])
    )

    stats = _cross_section_stats(df, "excess_h1")

    assert stats["n_days"] == 3
    assert stats["median"] == 4.0   # [2,4,6] 의 중앙값
    assert stats["p25"] == 3.0
    assert stats["p75"] == 5.0


def test_cross_section_stats는_NaN_행을_세지_않는다():
    """점수는 있지만 수익이 NaN인 행은 «유효 종목 수»에서 빼야 한다 — 안
    그러면 4~5종목짜리 창이 실제보다 넓어 보인다(C1 이 지키려는 것)."""
    rows = _rows(DAY1, [(0.1, 0.01), (0.2, 0.02)])
    rows.append({"trade_date": DAY1, "composite_score": 0.9, "excess_h1": None})
    df = pd.DataFrame(rows)

    stats = _cross_section_stats(df, "excess_h1")

    assert stats["median"] == 2.0   # NaN 행(3번째)은 세지 않는다


def test_cross_section_stats는_유효행이_없으면_None이다():
    df = pd.DataFrame(_rows(DAY1, [(0.1, None)]))

    assert _cross_section_stats(df, "excess_h1") is None


def test_히트율_wide_days_only는_횡단면이_top_n_초과하는_날만_쓴다():
    """day1 은 5종목(top_n=2 초과, «넓은» 날)이라 포함되고, day2 는 2종목뿐
    (top_n=2 초과 아님, «좁은» 날)이라 완전히 빠져야 한다 — 안 그러면
    day2 에서 top2 를 뽑는 것이 «그 날 전체» 를 뽑는 것과 같아져
    (C1) 히트율이 신호와 무관하게 0.5 로 쏠린다."""
    df = pd.DataFrame(
        _rows(DAY1, [(0.9, 0.01), (0.7, -0.01), (0.5, 0.02),
                     (0.3, -0.02), (0.1, 0.03)])
        + _rows(DAY2, [(0.6, 0.01), (0.5, -0.02)])
    )

    hr, hr_n, hr_days = _hit_rate_wide_days_only(df, "excess_h1", top_n=2)

    # day1 top2 = (0.9, +0.01), (0.7, -0.01) => 2건 중 1건 양수 => 0.5
    assert hr == pytest.approx(0.5)
    assert hr_n == 2
    assert hr_days == 1


def test_히트율_wide_days_only는_넓은_날이_하나도_없으면_NaN이다():
    """모든 거래일의 횡단면이 top_n 이하면(예: prod_calendar 처럼 하루
    4~5종목뿐인 창) 히트율을 «측정 불가» 로 돌려줘야 한다 — 억지로 계산해
    0.5 근방의 그럴듯한 숫자를 내면 안 된다."""
    df = pd.DataFrame(
        _rows(DAY1, [(0.9, 0.01), (0.5, -0.02), (0.1, 0.03)])
        + _rows(DAY2, [(0.6, 0.01), (0.5, -0.02)])
    )

    hr, hr_n, hr_days = _hit_rate_wide_days_only(df, "excess_h1", top_n=10)

    assert pd.isna(hr)
    assert hr_n == 0
    assert hr_days == 0


@pytest.mark.db
def test_load_signals는_결정적_순서로_정렬해_돌려준다(db):
    """C2: quantile_returns 의 qcut 이 동점을 «입력 순서» 로 끊으므로, 이
    함수가 정렬 없이 반환하면 결과가 PostgreSQL 힙 순서(=삽입/재작성 순서)에
    좌우돼 재현되지 않는다. 실제 backtest_signal(2026-06, 기존 데이터)로
    반환 프레임이 (trade_date, window_kind, stock_code) 순서인지 직접 본다."""
    out = _load_signals(db, date(2026, 6, 1), date(2026, 6, 30))

    assert len(out) > 0
    keys = list(zip(out["trade_date"], out["window_kind"], out["stock_code"]))
    assert keys == sorted(keys)
