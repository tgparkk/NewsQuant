"""뉴스 신호 백테스트 — 신호 재현 → 수익 결합 → 측정 → 리포트.

    python scripts/reprocess_news.py --apply          # 먼저 (약 34분)
    python scripts/run_news_backtest.py --replay --apply
    python scripts/run_news_backtest.py               # 측정만 다시

설계: docs/superpowers/specs/2026-09-12-news-signal-backtest-design.md

이 파일은 조립과 출력만 한다 — 로직은 Task 1~6(signal_replay/returns/metrics)
에 있고 거기서 테스트된다. 여기서 지켜야 하는 건 «정직한 출력» 뿐이다:

1. permutation_test 뿐 아니라 «어떤» 지표든 NaN/inf 로 나오면 숫자로
   포맷하지 않고 "측정불가" 라고 명시한다(_fmt_metric).
2. mean_ic 는 «일자 가중»(거래일 1개 = 1표)이고, hit_rate·quantile_returns 는
   «행 가중»(종목이 많은 날이 더 크게 반영)이다 — 서로 다른 척도라 리포트
   푸터에서 섞어 비교하지 말라고 적어 둔다.
3. 모든 지표 줄에 그 지표가 근거한 거래일 수와 관측치 수를 같이 적는다.
   푸터의 표본 거래일 수도 이번 실행이 실제로 다룬 거래일 수에서 계산한다
   (고정값 아님) — 창 종류별로 다르면 따로 적는다.
4. --replay 만 쓰고 --apply 를 빼는 조합은 거부한다. 그 조합은 재현 결과를
   버리는데, 아래 지표는 여전히 DB에 저장된 «이전» 신호를 읽는다 — "재현"
   줄과 "측정" 줄이 서로 다른 것을 가리키게 되는, 바로 이 리포트가 막아야
   하는 종류의 오해다.
"""
import argparse
import logging
import math
import os
import sys
from datetime import date, datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_START = date(2026, 1, 7)
DEFAULT_END = date(2026, 9, 11)


def _load_signals(db, start, end) -> pd.DataFrame:
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT trade_date, window_kind, stock_code, composite_score
                FROM backtest_signal
                WHERE trade_date >= %s AND trade_date <= %s
            """, (start, end))
            return pd.DataFrame(cur.fetchall(),
                                columns=["trade_date", "window_kind",
                                         "stock_code", "composite_score"])
    finally:
        conn.rollback()
        db._put_connection(conn)


def _ic_obs_count(df: pd.DataFrame, ic: pd.Series, score_col: str = "composite_score",
                   ret_col: str = "excess_h1") -> int:
    """daily_ic 가 실제로 채택한 거래일들의 관측치(유효 행) 합.

    daily_ic 는 MIN_STOCKS_PER_DAY 미달이거나 순위상관이 NaN인 날을 걷어내고
    남은 거래일만 ic 의 인덱스로 돌려준다. 같은 dropna 기준으로 다시 걸러
    그 인덱스에 속한 날만 세면 daily_ic 내부와 동일한 표본을 얻는다.
    """
    valid = df.dropna(subset=[score_col, ret_col])
    return int(sum(len(g) for day, g in valid.groupby("trade_date") if day in ic.index))


def _hit_rate_stats(df: pd.DataFrame, ret_col: str, top_n: int = 10,
                     score_col: str = "composite_score"):
    """hit_rate() 와 «같은» 선택 로직으로 관측치·거래일 수를 센다(행 가중)."""
    work = df.dropna(subset=[score_col, ret_col])
    picked = (work.sort_values(score_col, ascending=False)
                  .groupby("trade_date").head(top_n))
    return len(picked), int(picked["trade_date"].nunique())


def _quantile_days_used(df: pd.DataFrame, score_col: str, ret_col: str, n_q: int) -> int:
    """quantile_returns() 와 «같은» 조건으로 실제 분위수 계산에 쓰인 거래일 수."""
    work = df.dropna(subset=[score_col, ret_col])
    return sum(1 for _, g in work.groupby("trade_date") if g[score_col].nunique() >= n_q)


def _fmt_metric(value, fmt: str) -> str:
    """NaN/inf 는 숫자로 포맷하지 않는다 — 실패한 측정이 그럴듯한 숫자로

    보이는 걸 막는 것이 이 스크립트 전체의 목적이므로, permutation_test
    뿐 아니라 mean_ic·t_stat·hit_rate·스프레드 등 어떤 지표가 NaN/inf 로
    나오든 이 함수를 거쳐 "측정불가" 로 통일해서 보여준다.
    """
    if value is None or not math.isfinite(value):
        return "측정불가"
    return format(value, fmt)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--replay", action="store_true", help="신호를 다시 재현한다")
    ap.add_argument("--apply", action="store_true", help="재현 결과를 저장한다")
    ap.add_argument("--start", default=DEFAULT_START.isoformat())
    ap.add_argument("--end", default=DEFAULT_END.isoformat())
    ap.add_argument("--permutations", type=int, default=500)
    args = ap.parse_args()

    if args.replay and not args.apply:
        print("--replay 만 쓰고 --apply 를 빼는 조합은 거부한다 — 재현 결과를 "
              "저장하지 않으면서 아래 지표는 여전히 DB에 이미 저장된 «이전» "
              "신호를 읽어 측정한다. «재현» 과 «측정» 이 서로 다른 것을 "
              "가리키게 된다. --replay --apply 로 저장하거나, --replay 를 "
              "빼고 저장된 값만 측정하라.")
        return 1

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    from news_scraper.backtest.metrics import (
        daily_ic, hit_rate, ic_summary, permutation_test, quantile_returns,
    )
    from news_scraper.backtest.returns import HORIZONS, attach_returns, load_returns
    from news_scraper.backtest.signal_replay import WINDOW_KINDS, replay_range
    from news_scraper.database import NewsDatabase

    db = NewsDatabase()

    if args.replay:
        # 위 가드 때문에 여기 도달했다는 것 자체가 args.apply=True 임을 뜻한다.
        stats = replay_range(db, start, end, apply=True)
        print(f"재현: 거래일 {stats['days']} · 신호 {stats['rows']:,}행 "
              f"(apply={stats['applied']})")

    signals = _load_signals(db, start, end)
    if signals.empty:
        print("backtest_signal 이 비었다. --replay --apply 를 먼저 돌려라.")
        return 1

    rets = load_returns(db, start, end)
    df = attach_returns(signals, rets)

    print(f"\n기간 {start} ~ {end} · 신호 {len(signals):,}행 · 수익 결합 {len(df):,}행")
    print("=" * 74)

    day_counts = {}  # 창별로 이번 실행에서 실제로 다룬(=usable 관측이 있는) 거래일 수 — 푸터에 쓴다
    for kind in WINDOW_KINDS:
        sub = df[df["window_kind"] == kind]
        if sub.empty:
            print(f"\n[{kind}] 관측 없음")
            continue
        n_days_this_kind = sub["trade_date"].nunique()
        day_counts[kind] = n_days_this_kind
        print(f"\n[{kind}] 관측 {len(sub):,} · 거래일 {n_days_this_kind}")

        h1_stats = None  # 순열검정 표본 크기 표시에 재사용(h=1 IC 와 동일 표본)
        for h in HORIZONS:
            col = f"excess_h{h}"
            if col not in sub.columns or sub[col].notna().sum() == 0:
                continue
            ic = daily_ic(sub, ret_col=col)
            s = ic_summary(ic)
            obs = _ic_obs_count(sub, ic, ret_col=col)
            hr = hit_rate(sub, col)
            hr_n, hr_days = _hit_rate_stats(sub, col)
            print(f"  h{h}: 평균IC {_fmt_metric(s['mean_ic'], '+.4f')} "
                  f"(거래일 {s['n_days']}·관측 {obs}) "
                  f"· t {_fmt_metric(s['t_stat'], '+.2f')} "
                  f"· 히트율(top10,행가중) {_fmt_metric(hr, '.3f')} "
                  f"(관측 {hr_n}·거래일 {hr_days})")
            if h == 1:
                h1_stats = (s, obs)

        q = quantile_returns(sub, "excess_h1")
        if not q.empty:
            total_n = int(q["n"].sum())
            q_days = _quantile_days_used(sub, "composite_score", "excess_h1", 5)
            cells = " ".join(f"Q{int(r.quantile) + 1} {r.mean_excess:+.4f}(n={r.n})"
                             for r in q.itertuples())
            print(f"  h1 분위수(행가중, 관측 {total_n}·거래일 {q_days}): {cells}")
            spread = q["mean_excess"].iloc[-1] - q["mean_excess"].iloc[0]
            print(f"  h1 Q5-Q1 스프레드: {_fmt_metric(spread, '+.4f')}")

        p = permutation_test(sub, "excess_h1", n_iter=args.permutations)
        if p["n_iter"] == 0 or pd.isna(p["observed"]):
            print("  순열검정: 측정 불가 — 유효한 거래일 없음")
        else:
            # 이 분기에 왔다는 것 자체가 h=1 IC 가 유효하다는 뜻이다(위 NaN
            # 분기가 그 반대 — 유효 거래일 없음 — 를 이미 가로챈다) — h1_stats
            # 는 항상 채워져 있다.
            s1, obs1 = h1_stats
            print(f"  순열검정: 관측 평균IC {p['observed']:+.4f} "
                  f"(거래일 {s1['n_days']}·관측 {obs1}) · "
                  f"p={p['p_value']:.3f} ({p['n_iter']}회)")

    print("\n" + "=" * 74)
    if not day_counts:
        sample_note = "표본 0 거래일(관측 없음)"
    elif len(set(day_counts.values())) == 1:
        sample_note = f"표본 {next(iter(day_counts.values()))} 거래일"
    else:
        sample_note = "표본 " + " · ".join(f"{k} {v}거래일" for k, v in day_counts.items())
    print(f"한계: 생존 편향(상장폐지 종목 없음, 결과를 낙관적으로 만든다) · "
          f"수정주가 부재(±30% 밖만 제거) · {sample_note} · "
          f"일별 IC 자기상관(t통계량은 참고값)")
    print("※ 가중치 주의: 평균IC 는 «일자 가중»(거래일 1개 = 1표)이고, "
          "히트율·분위수는 «행 가중»(종목이 많은 날이 더 크게 반영)이다 — "
          "서로 다른 척도이니 같은 수치로 비교하지 마라 "
          "(실측 예: 동일 픽스처에서 히트율 행가중 0.833 vs 일자균등 0.5).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
