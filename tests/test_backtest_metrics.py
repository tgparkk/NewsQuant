"""측정 — 「신호가 수익을 예측하는가」에 답하는 숫자들.

169 거래일은 IC 유의성에 넉넉한 표본이 아니다. 그래서 순열 검정을 같이
돌려 「IC 0.03」이 우연과 구별되는지 말할 수 있게 한다.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from news_scraper.backtest.metrics import (
    daily_ic, hit_rate, ic_summary, permutation_test, quantile_returns,
)


def _frame(pairs, day=date(2026, 6, 15)):
    return pd.DataFrame([
        {"trade_date": day, "window_kind": "sector_1530",
         "stock_code": f"S{i}", "composite_score": s, "excess_h1": r}
        for i, (s, r) in enumerate(pairs)
    ])


def test_완전_상관이면_IC가_1이다():
    df = _frame([(0.1, 0.01), (0.2, 0.02), (0.3, 0.03), (0.4, 0.04)])

    assert daily_ic(df).iloc[0] == pytest.approx(1.0)


def test_완전_역상관이면_IC가_마이너스_1이다():
    df = _frame([(0.1, 0.04), (0.2, 0.03), (0.3, 0.02), (0.4, 0.01)])

    assert daily_ic(df).iloc[0] == pytest.approx(-1.0)


def test_종목이_3개_미만인_날은_IC를_내지_않는다():
    """정확히 2종목이면 순위상관은 신호와 무관하게 늘 ±1 이다 — 두 값의
    순위쌍은 일치 아니면 반대뿐이라 수학적 필연이다(여기서는 반대라 -1).
    MIN_STOCKS_PER_DAY=3 이 이런 날을 걸러내는지를 본다 — 기준이 2였다면
    이 날의 IC 는 -1 로 시계열에 섞였을 것이다."""
    df = _frame([(0.1, 0.05), (0.2, 0.01)])

    assert len(daily_ic(df)) == 0


def test_IC요약이_표본수와_t통계량을_준다():
    ic = pd.Series([0.1, 0.2, 0.15], index=[date(2026, 6, d) for d in (15, 16, 17)])

    out = ic_summary(ic)

    assert out["n_days"] == 3
    assert out["mean_ic"] == pytest.approx(0.15)
    # std(ddof=1)=0.05, t = mean/(std/sqrt(3)) 를 손으로 미리 계산해 고정한다 —
    # 부호만 보면 "항상 양수를 반환" 하는 고장난 구현도 통과하기 때문이다.
    assert out["std_ic"] == pytest.approx(0.05)
    assert out["t_stat"] == pytest.approx(5.196152, rel=1e-5)


def test_분위수_수익이_단조롭다():
    df = _frame([(i / 10, i / 100) for i in range(1, 11)])

    q = quantile_returns(df, "excess_h1", n_q=5)

    assert list(q["mean_excess"]) == sorted(q["mean_excess"])


def test_유효한_값이_모자란_날은_분위수를_건너뛴다():
    """NaN 을 뺀 «유효한» 행 기준으로 n_q 미달을 판단해야 한다 — 제거
    전 원본에는 점수가 n_q개 이상 달라도, excess_h1 이 NaN 인 종목을
    빼고 나면 실제로는 분위를 채울 수 없는 날일 수 있다."""
    day1, day2 = date(2026, 6, 15), date(2026, 6, 16)
    rows = []
    for i, (s, r) in enumerate([(0.1, 0.01), (0.2, 0.02), (0.3, 0.03),
                                  (0.4, np.nan), (0.5, np.nan)]):
        rows.append({"trade_date": day1, "window_kind": "sector_1530",
                     "stock_code": f"D1S{i}", "composite_score": s, "excess_h1": r})
    for i, (s, r) in enumerate([(0.1, 0.01), (0.2, 0.02), (0.3, 0.03),
                                  (0.4, 0.04), (0.5, 0.05)]):
        rows.append({"trade_date": day2, "window_kind": "sector_1530",
                     "stock_code": f"D2S{i}", "composite_score": s, "excess_h1": r})

    q = quantile_returns(pd.DataFrame(rows), "excess_h1", n_q=5)

    # day1 은 유효 3종목뿐(n_q=5 미달)이라 통째로 빠지고, day2 의 5건만 남는다.
    assert q["n"].sum() == 5


def test_히트율은_상위_N의_양의_비율이다():
    df = _frame([(0.9, 0.01), (0.7, -0.01), (0.3, -0.02), (0.1, -0.03)])

    assert hit_rate(df, "excess_h1", top_n=2) == pytest.approx(0.5)


def test_무작위_신호는_순열검정을_통과하지_못한다():
    rng = np.random.default_rng(7)
    days = [date(2026, 6, 1) + timedelta(days=i) for i in range(30)]
    rows = []
    for d in days:
        for i in range(20):
            rows.append({"trade_date": d, "window_kind": "sector_1530",
                         "stock_code": f"S{i}",
                         "composite_score": rng.normal(),
                         "excess_h1": rng.normal()})

    out = permutation_test(pd.DataFrame(rows), "excess_h1", n_iter=200, seed=1)

    assert out["p_value"] > 0.05


def test_강한_신호는_순열검정에서_작은_p값을_받는다():
    """무작위 신호 테스트의 반대쪽을 채운다 — p_value 를 «항상 1.0»
    으로 돌려주는 고장난 구현도 「무작위 신호는 통과 못한다」테스트 하나만
    으로는 잡히지 않는다(1.0 > 0.05 이므로 그 테스트도 통과해 버린다).
    강한 신호에서 작은 p값이 나오는지까지 같이 봐야 통계량 자체가
    양방향으로 고정된다."""
    rng = np.random.default_rng(3)
    days = [date(2026, 6, 1) + timedelta(days=i) for i in range(30)]
    rows = []
    for d in days:
        for i in range(20):
            score = rng.normal()
            rows.append({"trade_date": d, "window_kind": "sector_1530",
                         "stock_code": f"S{i}",
                         "composite_score": score,
                         "excess_h1": score})  # 수익이 점수와 완전히 같다 — 일별 IC=1

    out = permutation_test(pd.DataFrame(rows), "excess_h1", n_iter=200, seed=1)

    assert out["p_value"] < 0.05
