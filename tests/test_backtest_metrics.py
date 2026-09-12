"""측정 — 「신호가 수익을 예측하는가」에 답하는 숫자들.

169 거래일은 IC 유의성에 넉넉한 표본이 아니다. 그래서 순열 검정을 같이
돌려 「IC 0.03」이 우연과 구별되는지 말할 수 있게 한다.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from news_scraper.backtest.metrics import (
    _shuffle_within_day, daily_ic, hit_rate, ic_summary, permutation_test,
    quantile_returns,
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


def test_IC는_거래일마다_따로_계산된다():
    """단일 거래일 픽스처(_frame)로는 «날짜별로» 계산되는지 확인할 수
    없다 — 날짜 구분 없이 전체를 하나로 풀링해 계산해도 1개짜리 결과와
    구별이 안 된다. 두 거래일에 부호가 반대인 관계를 심어, 결과 Series
    가 날짜별로 «따로» 나오는지(풀링해 뭉치면 못 만들 값) 를 본다."""
    day1, day2 = date(2026, 6, 15), date(2026, 6, 16)
    rows = []
    for i, (s, r) in enumerate([(0.1, 0.01), (0.2, 0.02), (0.3, 0.03)]):
        rows.append({"trade_date": day1, "window_kind": "sector_1530",
                     "stock_code": f"D1S{i}", "composite_score": s, "excess_h1": r})
    for i, (s, r) in enumerate([(0.1, 0.03), (0.2, 0.02), (0.3, 0.01)]):
        rows.append({"trade_date": day2, "window_kind": "sector_1530",
                     "stock_code": f"D2S{i}", "composite_score": s, "excess_h1": r})

    ic = daily_ic(pd.DataFrame(rows))

    assert len(ic) == 2
    assert ic.loc[day1] == pytest.approx(1.0)
    assert ic.loc[day2] == pytest.approx(-1.0)


def test_IC요약이_표본수와_t통계량을_준다():
    ic = pd.Series([0.1, 0.2, 0.15], index=[date(2026, 6, d) for d in (15, 16, 17)])

    out = ic_summary(ic)

    assert out["n_days"] == 3
    assert out["mean_ic"] == pytest.approx(0.15)
    # std(ddof=1)=0.05, t = mean/(std/sqrt(3)) 를 손으로 미리 계산해 고정한다 —
    # 부호만 보면 "항상 양수를 반환" 하는 고장난 구현도 통과하기 때문이다.
    assert out["std_ic"] == pytest.approx(0.05)
    assert out["t_stat"] == pytest.approx(5.196152, rel=1e-5)


def test_IC요약은_표본이_없으면_NaN이고_죌_죽지_않는다():
    """빈 IC 시계열(살아남는 거래일이 0개)에서 t통계량 계산이 0으로
    나누기를 시도하면 죌 죽는다(math.sqrt(0) 이 분모에 들어감) — n==0
    가드가 없으면 이 호출 자체가 예외를 던진다."""
    out = ic_summary(pd.Series([], dtype=float))

    assert out["n_days"] == 0
    assert np.isnan(out["mean_ic"])
    assert np.isnan(out["std_ic"])
    assert np.isnan(out["t_stat"])


def test_IC요약은_표본이_1개면_표준편차와_t통계량이_NaN이다():
    """표본이 1개면 표준편차(ddof=1)를 낼 수 없다 — n-1=0 이라 분산의
    정의 자체가 없다. std_ic·t_stat 모두 NaN 이어야 하고, mean_ic 는
    그 하나의 값 그대로여야 한다."""
    out = ic_summary(pd.Series([0.2], index=[date(2026, 6, 15)]))

    assert out["n_days"] == 1
    assert out["mean_ic"] == pytest.approx(0.2)
    assert np.isnan(out["std_ic"])
    assert np.isnan(out["t_stat"])


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


def test_분위수는_거래일별로_계산된다():
    """두 거래일 모두 하나씩 묶으면 통과하는 단일-거래일 픽스처로는
    «날짜별로» 나누는지 못 본다. day2 의 점수 «수준» 을 day1 보다 100 배
    크게 떼어 놓으면, 날짜 구분 없이 전체를 풀링해 분위를 나누는(=버그)
    구현은 day1 전체를 하위 분위, day2 전체를 상위 분위로 통째로 몰아
    넣어 버려 날짜별로 나눈 것과 다른 값이 나온다."""
    day1, day2 = date(2026, 6, 15), date(2026, 6, 16)
    rows = []
    for i, (s, r) in enumerate([(1, 0.01), (2, 0.02), (3, 0.03), (4, 0.04)]):
        rows.append({"trade_date": day1, "window_kind": "sector_1530",
                     "stock_code": f"D1S{i}", "composite_score": s, "excess_h1": r})
    # day2 는 day1 보다 점수 수준이 훨씨 높지만(100대), 그 날 «안» 에서는
    # 점수와 수익이 반대 방향이다 — 날짜별로 나누면 day1·day2 각각의 하위/
    # 상위 절반이 한 분위에 섞이지만, 풀링하면 day2 전체가 상위 분위를
    # 통째로 차지한다.
    for i, (s, r) in enumerate([(100, 0.05), (101, 0.06), (102, 0.03), (103, 0.02)]):
        rows.append({"trade_date": day2, "window_kind": "sector_1530",
                     "stock_code": f"D2S{i}", "composite_score": s, "excess_h1": r})

    q = quantile_returns(pd.DataFrame(rows), "excess_h1", n_q=2)

    got = dict(zip(q["quantile"], q["mean_excess"]))
    # 손으로 계산: quantile0 = day1 하위{1,2}(0.01,0.02) + day2 하위{100,101}(0.05,0.06)
    #             quantile1 = day1 상위{3,4}(0.03,0.04) + day2 상위{102,103}(0.03,0.02)
    assert got[0] == pytest.approx(0.035)
    assert got[1] == pytest.approx(0.03)


def test_분위수는_동점_비율의_중앙값을_attrs에_담는다():
    """C2: 동점 블록이 크면 qcut 버킷 경계가(rank(method="first")가 입력
    순서로 끊는 지점) 재현 불가능해진다 — 그 정도를 attrs["tie_fraction_median"]
    로 드러내는지 손으로 계산해 고정한다."""
    dayA, dayB = date(2026, 6, 15), date(2026, 6, 16)
    rows = []
    for i, (s, r) in enumerate([(1, 0.01), (1, 0.02), (1, 0.03), (2, 0.04)]):
        rows.append({"trade_date": dayA, "window_kind": "sector_1530",
                     "stock_code": f"A{i}", "composite_score": s, "excess_h1": r})
    for i, (s, r) in enumerate([(1, 0.01), (2, 0.02), (3, 0.03), (4, 0.04)]):
        rows.append({"trade_date": dayB, "window_kind": "sector_1530",
                     "stock_code": f"B{i}", "composite_score": s, "excess_h1": r})
    df = pd.DataFrame(rows)

    q = quantile_returns(df, "excess_h1", n_q=2)

    # dayA: 값 1 이 4행 중 3행 => 0.75. dayB: 전부 유니크(1/4씩) => 0.25.
    # 중앙값([0.75, 0.25]) = 0.5.
    assert q.attrs["tie_fraction_median"] == pytest.approx(0.5)


def test_분위수가_비어있으면_동점_비율도_NaN이다():
    df = pd.DataFrame(columns=["trade_date", "window_kind", "stock_code",
                               "composite_score", "excess_h1"])

    q = quantile_returns(df, "excess_h1", n_q=5)

    assert q.empty
    assert np.isnan(q.attrs["tie_fraction_median"])


def test_히트율은_상위_N의_양의_비율이다():
    df = _frame([(0.9, 0.01), (0.7, -0.01), (0.3, -0.02), (0.1, -0.03)])

    assert hit_rate(df, "excess_h1", top_n=2) == pytest.approx(0.5)


def test_히트율은_거래일별로_계산된다():
    """단일-거래일 픽스처로는 「전역 top_n」 으로 구현해도 「날짜별 top_n」
    과 같은 값이 나올 수 있어(우연) 구별이 안 된다. day1 의 점수 수준을
    day2 보다 훨씬 높게 떼어 놓으면, 날짜 구분 없이 전역에서 top_n=1 을
    고르는(=버그) 구현은 day2 를 아예 못 뽑고 day1 것만 하나 뽑아 다른
    값이 나온다."""
    day1, day2 = date(2026, 6, 15), date(2026, 6, 16)
    rows = []
    for i, (s, r) in enumerate([(0.9, -0.01), (0.5, 0.02), (0.3, 0.03)]):
        rows.append({"trade_date": day1, "window_kind": "sector_1530",
                     "stock_code": f"D1S{i}", "composite_score": s, "excess_h1": r})
    for i, (s, r) in enumerate([(0.4, 0.05), (0.35, -0.02), (0.3, -0.01)]):
        rows.append({"trade_date": day2, "window_kind": "sector_1530",
                     "stock_code": f"D2S{i}", "composite_score": s, "excess_h1": r})

    # 날짜별 top1: day1 최고점(0.9)→-0.01(음), day2 최고점(0.4)→+0.05(양)
    # => 2건 중 1건 양 => 0.5. 전역 top1 이면 0.9(day1) 하나만 뽑혀 0.0 이 된다.
    assert hit_rate(pd.DataFrame(rows), "excess_h1", top_n=1) == pytest.approx(0.5)


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


def test_관측치가_없으면_순열검정은_NaN을_돌려준다():
    """살아남는 거래일이 하나도 없으면(MIN_STOCKS_PER_DAY 미달 등)
    observed 가 NaN 이다. abs(nan) >= abs(nan) 은 항상 False 이므로,
    이 가드가 없으면 hits=0 이 되어 p_value=1/(n_iter+1) — 표본이 «전혀»
    없는데 가장 유의해 보이는 값이 나오는 최악의 오답이다. 관측이 없으면
    유의해 보여선 안 된다."""
    df = _frame([(0.1, 0.05), (0.2, 0.01)])  # 2종목뿐 — MIN_STOCKS_PER_DAY=3 미달

    out = permutation_test(df, "excess_h1", n_iter=20, seed=0)

    assert np.isnan(out["observed"])
    assert np.isnan(out["p_value"])
    assert out["n_iter"] == 0


def test_순열은_거래일_안에서만_점수를_섞는다():
    """permutation_test 의 셔플이 날짜 경계를 넘지 않는지를 직접 검사한다.

    p_value 비교로는 이 성질을 못 잡는다 — 스피어만은 순위통계라, 동점
    (tie) 없는 연속값이면 어떤 크기의 부분집합이든 «그 날 자신의 값으로만»
    섞든 «전체 풀에서» 섞든 그 날의 상대순위 분포 자체는 수학적으로 항상
    균등무작위가 되어버려 구별이 안 된다(균등순열을 값과 무관한 고정
    파티션으로 나누면 블록 내부 순서는 서로 독립·균등이라는 조합론적
    사실이다 — 실측으로도 확인: 몬테카를로 60회, 불균등 그룹 크기
    5/20/35/50 + 날짜별 드리프트를 섞은 귀무가설 데이터에서 그룹 셔플과
    전역 셔플의 오탐률이 10.0% vs 10.0% 로 정확히 같았다). «동점이 있으면»
    이 논리가 깨진다 — 그 경우는 아래 test_동일점수_동점이_있으면_전역
    셔플과_구별된다 가 다룬다.

    이 테스트는(동점 없는 데이터로) 셔플 메커니즘 자체를 직접 검사한다:
    두 거래일의 점수 «수준» 을 완전히 떼어 놓으면(day1 은 1000대, day2
    는 2000대), 날짜 안에서만 섞을 경우 각 날의 점수 멀티셋(어떤 값들이
    있었는지)은 순서만 바뀌고 그대로 보존돼야 한다 — 전역으로 섞으면
    거의 항상 다른 날의 값이 끼어들어 깨진다.

    다만 이 화이트박스 테스트는 «_shuffle_within_day 함수 자체» 가
    맞는지만 본다 — permutation_test 가 «실제로 이 함수를 호출하는지»
    는 안 본다(호출부를 전역 셔플로 바꿔도 이 테스트는 그대로 통과한다).
    그 구멍은 아래 블랙박스 테스트가 막는다."""
    day1, day2 = date(2026, 6, 15), date(2026, 6, 16)
    rows = []
    for i in range(20):
        rows.append({"trade_date": day1, "stock_code": f"D1S{i}",
                     "composite_score": 1000.0 + i, "excess_h1": 0.01 * i})
    for i in range(20):
        rows.append({"trade_date": day2, "stock_code": f"D2S{i}",
                     "composite_score": 2000.0 + i, "excess_h1": 0.01 * i})
    work = pd.DataFrame(rows)

    rng = np.random.default_rng(0)
    shuffled = _shuffle_within_day(work, "composite_score", rng)

    for day, g in work.groupby("trade_date"):
        assert sorted(shuffled.loc[g.index]) == sorted(g["composite_score"])


def test_동일점수_동점이_있으면_전역셔플과_구별된다():
    """위 화이트박스 테스트의 구멍(호출부가 실제로 _shuffle_within_day
    를 쓰는지는 못 본다)을 permutation_test 의 «공개 인터페이스만»으로
    막는 블랙박스 테스트다.

    동점 없는 연속값에서는(위 테스트 코멘트) 그룹 셔플과 전역 셔플의
    p_value 가 수학적으로 구별 불가능하다 — «어느» 값이 어디로 가든
    상대순위 분포가 늘 균등무작위이기 때문이다. 하지만 «동점»이 있으면
    이 논리가 깨진다: dayA 의 세 종목을 완전히 같은 점수(1.0)로 만들면
    그 날은 분산이 0 이라 순위상관이 정의되지 않아(NaN) daily_ic 에서
    통째로 빠진다. 그룹 셔플은 dayA 를 «자기 자신의 동일한 값들» 로만
    섞으므로 매 반복 계속 동점 그대로라 dayA 는 널(null) 분포에서
    «영원히» 빠져 있다 — 그래서 그룹 셔플의 널은 dayB(10/20/30) 하나의
    3! 순열 법칙일 뿐이고, |rho|=1 이 나올 확률은 6가지 순열 중 정순열·
    역순열 2가지라 p≈1/3 이다. 전역 셔플은 dayB 의 서로 다른 값이 dayA
    자리로 새어 들어갈 수 있어 동점이 깨지고, dayA 가 이따금 널 분포에
    «들어오게» 된다 — 이게 두 셔플의 널 분포를 실제로 달라지게 만드는
    유일한 통로다(측정: 시드 0~4 에서 그룹 셔플 p=0.333/0.367/0.333/
    0.313/0.315, 전역 셔플 p=0.050/0.022/0.032/0.046/0.038 — 늘 0.2
    밖에서 갈린다). 그래서 이 픽스처에서는 p_value 만으로 «호출부가
    진짜 그룹 셔플을 쓰는지» 를 구별할 수 있다.

    한 시드만 보면 몬테카를로 잡음으로 우연히 맞을 수 있어, 시드 0~4
    다섯 개 모두에서 재확인한다."""
    dayA, dayB = date(2026, 6, 15), date(2026, 6, 16)
    rows = []
    for i, r in enumerate([0.01, 0.02, 0.03]):
        rows.append({"trade_date": dayA, "stock_code": f"A{i}",
                     "composite_score": 1.0, "excess_h1": r})
    for i, s in enumerate([10.0, 20.0, 30.0]):
        rows.append({"trade_date": dayB, "stock_code": f"B{i}",
                     "composite_score": s, "excess_h1": s})
    df = pd.DataFrame(rows)

    for seed in range(5):
        out = permutation_test(df, "excess_h1", n_iter=500, seed=seed)
        assert out["p_value"] > 0.2, f"seed={seed} p={out['p_value']}"
