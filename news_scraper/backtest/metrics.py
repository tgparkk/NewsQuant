"""「신호가 수익을 예측하는가」에 답하는 숫자들.

IC(정보계수)가 핵심이다 — 거래일마다 신호 점수와 이후 초과수익의 순위상관을
구하고, 그 일별 시계열의 평균이 0 과 구별되는지를 본다.

169 거래일은 넉넉한 표본이 아니다. 그래서 순열 검정을 같이 돌린다.
일별 IC 는 자기상관이 있으므로 단순 t통계량의 한계는 리포트에 적는다.

새 의존성을 더하지 않는다 — 스피어만은 rank() 후 피어슨으로,
t통계량은 mean/(std/sqrt(n)) 로 직접 구한다.

이 모듈은 순수 계산만 한다 — DB 를 건드리지 않는다.
"""
import logging
import math
from typing import Dict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 정확히 2종목인 날은 순위상관이 신호와 무관하게 항상 ±1 이 나온다 — 값이
# 2개뿐이면 순위쌍은 일치(+1) 아니면 반대(-1) 뿐이라 수학적 필연이다.
# 그런 날을 IC 시계열에 그대로 섞으면 신호 정보 없이 순수 분산만 늘어난다.
# 그래서 하루에 최소 3종목(=MIN_STOCKS_PER_DAY)은 있어야 그 날의 IC 를 쓴다.
MIN_STOCKS_PER_DAY = 3


def daily_ic(df: pd.DataFrame, score_col: str = "composite_score",
             ret_col: str = "excess_h1") -> pd.Series:
    """거래일별 스피어만 순위상관. 종목이 MIN_STOCKS_PER_DAY 미만인 날은 건너뛴다."""
    out = {}
    for day, g in df.dropna(subset=[score_col, ret_col]).groupby("trade_date"):
        if len(g) < MIN_STOCKS_PER_DAY:
            continue
        ic = g[score_col].rank().corr(g[ret_col].rank())
        if pd.notna(ic):
            out[day] = ic
    return pd.Series(out, dtype=float).sort_index()


def ic_summary(ic: pd.Series) -> Dict:
    """평균 IC 와 t통계량. 표본 수를 «항상» 같이 돌려준다."""
    n = int(ic.notna().sum())
    if n == 0:
        return {"n_days": 0, "mean_ic": float("nan"),
                "std_ic": float("nan"), "t_stat": float("nan")}
    mean = float(ic.mean())
    std = float(ic.std(ddof=1)) if n > 1 else float("nan")
    t = mean / (std / math.sqrt(n)) if n > 1 and std and std > 0 else float("nan")
    return {"n_days": n, "mean_ic": mean, "std_ic": std, "t_stat": t}


def quantile_returns(df: pd.DataFrame, ret_col: str = "excess_h1",
                     n_q: int = 5, score_col: str = "composite_score") -> pd.DataFrame:
    """일별로 점수를 n_q 분위로 나눠 분위별 평균 초과수익을 낸다.

    NaN 을 먼저 걷어낸 «유효한» 행만으로 날짜별 그룹을 만들고, 그 유효
    행 기준으로 distinct 점수 개수를 판단한다(n_q 미달이면 그 날은
    통째로 건너뛴다) — 제거 «전» 원본 기준으로 판단하면, excess 가
    NaN 인 종목까지 세어 실제로는 n_q 분위를 채울 수 없는 날인데도
    채울 수 있다고 오판하게 된다.

    날짜별로 루프를 돌며 라벨을 모아 pd.concat 으로 합친다 —
    groupby().apply() 로 한 번에 처리하면 «거래일이 딱 하나뿐인» 입력에서
    pandas(2.2 계열 확인됨)가 결과를 행별로 정렬하지 않고 통째로 뒤집어
    반환하는 버그가 있어, n_q 분위 라벨이 종목에 잘못 붙는다.

    반환 프레임의 .attrs["tie_fraction_median"] 에 «날짜별 최다 동점 비율»의
    중앙값을 같이 담아 돌려준다(C2) — 실 데이터는 하루 176종목에 distinct
    점수가 36개뿐이고 그중 39%가 같은 값(0.0647)인 날이 있을 정도로 동점이
    크다. qcut 이 그 동점 블록 «안»에서 경계를 끊으면 Q2~Q4 평균과 Q5-Q1
    스프레드가 동점 처리 방식에 좌우된다 — 이 값이 크면 스프레드를 신호로
    읽으면 안 된다.
    """
    empty_cols = ["quantile", "mean_excess", "n"]
    work = df.dropna(subset=[score_col, ret_col]).copy()
    if work.empty:
        empty = pd.DataFrame(columns=empty_cols)
        empty.attrs["tie_fraction_median"] = float("nan")
        return empty

    labels = []
    tie_fractions = []
    for _, g in work.groupby("trade_date"):
        if g[score_col].nunique() < n_q:
            continue
        # rank(method="first")는 동점을 «이 g 가 받은 행 순서» 대로 끊어서
        # 순위를 매긴다 — 즉 qcut 버킷 경계가 동점 블록 안 어디서 잘리는지는
        # 호출자가 넘긴 프레임의 행 순서에 달려 있다. 이 함수는 순서를 스스로
        # 정하지 않으므로, 결과가 재현되려면 호출자(_load_signals 등)가 이미
        # 결정적인 순서(예: ORDER BY)로 정렬해 넘겨야 한다(C2).
        labels.append(pd.qcut(g[score_col].rank(method="first"), n_q, labels=False))
        tie_fractions.append(float(g[score_col].value_counts(normalize=True).iloc[0]))

    if not labels:
        empty = pd.DataFrame(columns=empty_cols)
        empty.attrs["tie_fraction_median"] = float("nan")
        return empty

    work["quantile"] = pd.concat(labels)
    work = work.dropna(subset=["quantile"])
    agg = (work.groupby("quantile")[ret_col]
               .agg(mean_excess="mean", n="size").reset_index())
    agg["quantile"] = agg["quantile"].astype(int)
    agg = agg.sort_values("quantile").reset_index(drop=True)
    agg.attrs["tie_fraction_median"] = float(pd.Series(tie_fractions, dtype=float).median())
    return agg


def hit_rate(df: pd.DataFrame, ret_col: str = "excess_h1", top_n: int = 10,
             score_col: str = "composite_score") -> float:
    """일별 상위 top_n 종목의 초과수익이 양인 비율."""
    work = df.dropna(subset=[score_col, ret_col])
    picked = (work.sort_values(score_col, ascending=False)
                  .groupby("trade_date").head(top_n))
    return float((picked[ret_col] > 0).mean()) if len(picked) else float("nan")


def _shuffle_within_day(work: pd.DataFrame, score_col: str,
                        rng: np.random.Generator) -> pd.Series:
    """거래일(trade_date) 경계를 넘지 않고 그 날 안에서만 점수를 뒤섞는다.

    permutation_test 가 이 함수를 통해서만 셔플하도록 분리해 둔 이유는
    "날짜 경계를 지키는지" 를 이 함수 하나로 직접 테스트할 수 있게 하기
    위해서다 — p_value 비교로는 이 성질을 못 잡는다(모듈 하단 테스트의
    코멘트 참고): 스피어만은 순위통계라, 같은 크기의 부분집합을 «그 날
    자신의 값만으로» 섞든 «전체 풀에서» 섞든 그 날의 상대순위 분포 자체는
    수학적으로 항상 균등무작위가 되어 버려 통계량만으로는 구별되지 않는다.
    """
    return work.groupby("trade_date")[score_col].transform(
        lambda s: rng.permutation(s.values))


def permutation_test(df: pd.DataFrame, ret_col: str = "excess_h1",
                     n_iter: int = 500, seed: int = 0,
                     score_col: str = "composite_score") -> Dict:
    """거래일 안에서 점수를 섞어 평균 IC 분포를 만들고 실제값 위치를 본다."""
    observed = float(daily_ic(df, score_col, ret_col).mean())
    if not math.isfinite(observed):
        # 살아남는 거래일이 하나도 없으면(=관측치가 없으면) observed 가
        # NaN 이다. 이럴 때 순열을 그냥 돌리면 abs(nan) >= abs(nan) 이
        # 항상 False 라 hits=0, p_value=1/(n_iter+1) — 표본이 «전혀» 없는데
        # 가장 유의해 보이는 값이 나오는 최악의 오답이다. 관측이 없으면
        # 유의해 보여서는 안 되므로 즉시 NaN 을 돌려주고, n_iter=0 으로
        # 표본이 없었다는 사실 자체를 드러낸다.
        return {"observed": observed, "p_value": float("nan"), "n_iter": 0}

    rng = np.random.default_rng(seed)
    work = df.dropna(subset=[score_col, ret_col]).copy()

    hits = 0
    shuffled = work.copy()  # 루프 밖에서 한 번만 만들고 점수 컬럼만 매 반복 덮어쓴다.
    for _ in range(n_iter):
        shuffled[score_col] = _shuffle_within_day(work, score_col, rng)
        if abs(float(daily_ic(shuffled, score_col, ret_col).mean())) >= abs(observed):
            hits += 1

    return {"observed": observed,
            "p_value": (hits + 1) / (n_iter + 1),
            "n_iter": n_iter}
