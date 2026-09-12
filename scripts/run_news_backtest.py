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
from datetime import date, datetime, time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_START = date(2026, 1, 7)
DEFAULT_END = date(2026, 9, 11)

# C1 재지시 — 국내 언론으로 볼 소스 목록. 이건 DB 가 대신 답해줄 수 있는
# "사실"이 아니라 "국내 언론이란 무엇인가"라는 분류 결정이라 리터럴로
# 남겨 둔다(수치 자체는 아래 _corpus_gap_stats 가 실행마다 쿼리로 잰다).
DOMESTIC_PRESS_SOURCES = ("naver_finance", "hankyung", "mk_news")

# hit_rate 의 상위 N — 리포트 라벨이 이 값을 따라가야 한다(재지시 3번).
HIT_RATE_TOP_N = 10

# IC(순위상관)는 MIN_STOCKS_PER_DAY=3 이면 «정의»는 되지만, n 이 작으면
# 그날 나올 수 있는 로우(rho) 값 자체가 몇 개 이산값으로 쪼그라든다 —
# n=4 면 가능한 순열은 4!=24개뿐이라 로우가 가질 수 있는 값도
# {-1, -0.8, -0.6, 0, +0.6, +0.8, +1} 처럼 몇 안 되는 값 중 하나로만
# 떨어진다. 이건 "상관계수를 쟀다"가 아니라 "그날 하필 어느 순열이
# 나왔는지를 봤다"에 더 가깝다 — hit_rate 에서 top_n 을 그날 «전체» 로
# 뽑으면 히트율이 0.5로 쏠리는 것과 같은 표본붕괴(C1)다. 그래서 히트율
# 경고에 이미 쓰는 문턱(top_n=10)을 IC 경고에도 그대로 재사용한다 —
# "이 정도보다 얇은 표본에서는 두 지표 다 못 믿는다"를 하나의 문턱으로
# 통일해서 말한다.
MIN_IC_CROSS_SECTION_FOR_WARN = HIT_RATE_TOP_N


def _load_signals(db, start, end) -> pd.DataFrame:
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            # ORDER BY 가 없으면 행 순서는 PostgreSQL 힙 순서(=삽입/재작성
            # 순서)를 그대로 따른다. quantile_returns 의 qcut 은 동점을 «입력
            # 순서» 로 끊으므로(C2), 이 순서가 매 실행 달라지면 동점 블록
            # 안에 걸린 Q2~Q4 평균과 Q5-Q1 스프레드도 재현되지 않는다.
            cur.execute("""
                SELECT trade_date, window_kind, stock_code, composite_score
                FROM backtest_signal
                WHERE trade_date >= %s AND trade_date <= %s
                ORDER BY trade_date, window_kind, stock_code
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


def _cross_section_stats(df: pd.DataFrame, ret_col: str,
                          score_col: str = "composite_score"):
    """거래일별 «유효 종목 수»(횡단면 크기)의 median/25백분위/75백분위(C1).

    prod_calendar 는 실측으로 하루 평균 4.6종목(2026-06), sector_1530 은
    같은 달에 하루 평균 107종목이다 — 둘 다 MIN_STOCKS_PER_DAY=3 만 넘으면
    같은 표에 «평균IC» 로 나란히 찍히므로, 표본 크기의 이 차이를 분포로
    같이 보여주지 않으면 4종목짜리 날의 IC 와 107종목짜리 날의 IC 가
    비교 가능한 것처럼 읽힌다.
    """
    sizes = df.dropna(subset=[score_col, ret_col]).groupby("trade_date").size()
    if sizes.empty:
        return None
    q = sizes.quantile([0.25, 0.5, 0.75])
    return {"n_days": int(len(sizes)), "p25": float(q.loc[0.25]),
            "median": float(q.loc[0.5]), "p75": float(q.loc[0.75])}


def _hit_rate_wide_days_only(df: pd.DataFrame, ret_col: str, top_n: int = 10,
                              score_col: str = "composite_score"):
    """cross-section(그날 유효 종목 수)이 top_n 을 «초과»하는 거래일만 골라
    hit_rate 를 낸다(C1).

    top_n=10 인데 그 날 유효 종목이 4~5개뿐이면 «상위 10종목»이 사실상
    «그 날 종목 전체» 가 되어 버려, 히트율이 신호와 무관하게 0.5 쪽으로
    수렴한다(전체 모집단을 다 뽑으면 상승/하락 비율 자체가 답이 된다).
    metrics.hit_rate 자체는 바꾸지 않고, 여기서 넘기는 프레임만 좁힌다.

    반환: (히트율 또는 NaN, 뽑힌 행 수, 이 필터를 통과한 거래일 수).
    """
    from news_scraper.backtest.metrics import hit_rate  # main() 지역 임포트에 의존하지 않는다

    work = df.dropna(subset=[score_col, ret_col])
    sizes = work.groupby("trade_date").size()
    wide_days = sizes[sizes > top_n].index
    if len(wide_days) == 0:
        return float("nan"), 0, 0
    filtered = df[df["trade_date"].isin(wide_days)]
    hr = hit_rate(filtered, ret_col, top_n=top_n, score_col=score_col)
    hr_n, hr_days = _hit_rate_stats(filtered, ret_col, top_n=top_n, score_col=score_col)
    return hr, hr_n, hr_days


def _month_range(start: date, end: date):
    """start~end 를 덮는 달의 1일들(달력월, 리스트) — 기사가 0건인 달도
    포함해야 «공백» 이 보인다. GROUP BY 는 행이 있는 달만 돌려주므로,
    이 목록에 없는 달의 개수는 호출부가 0으로 채워 넣는다."""
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(date(y, m, 1))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


def _corpus_gap_stats(db, start: date, end: date) -> dict:
    """이 백테스트 구간의 뉴스 코퍼스 공백을 «실행마다» DB 에서 직접 잰다.

    코디네이터 재지시(2차 재검토) — 이전 라운드는 리뷰 시점 스냅숏 수치를
    리포트 문자열에 리터럴로 박아 넣었는데, 뉴스가 계속 쌓여 실측치와
    어긋났다. 이 파일에서 «표본 169 거래일» 을 하드코딩했다가 같은 이유로
    틀렸던 것(day_counts 로 고쳤던 바로 그 결함)과 같은 결함 종류다 — DB 가
    답해 줄 수 있는 숫자는 리터럴로 적지 않는다.

    이 문단은 «백테스트가 그 순간(D 09:00)에 본 것» 이 아니라 «이 달력
    구간 전체의 코퍼스가 얼마나 비어 있는가» 를 묘사하는 것이 목적이라
    (원 리뷰의 C1 서술 자체가 이 전제다), 신호 as_of(§5.3, D 09:00) 로
    자르지 않고 [start 00:00, end 23:59:59] 달력일 전체로 잰다 — end 당일
    저녁 뉴스까지 포함해야 «그 날 하루의 코퍼스» 를 온전히 재는 것이 된다.
    news_reprocessed 를 직접 집계하므로 news_scraper.database 연결 하나만
    있으면 되고 신규 의존성은 없다.
    """
    lo = datetime.combine(start, time(0, 0))
    hi = datetime.combine(end, time(23, 59, 59))

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT count(*) FILTER (WHERE source = 'dart'), count(*)
                FROM news_reprocessed
                WHERE related_stocks <> '' AND published_at >= %s AND published_at <= %s
            """, (lo, hi))
            dart_cnt, total_cnt = cur.fetchone()

            cur.execute("""
                SELECT date_trunc('month', published_at)::date, count(*)
                FROM news_reprocessed
                WHERE source = ANY(%s) AND published_at >= %s AND published_at <= %s
                GROUP BY 1 ORDER BY 1
            """, (list(DOMESTIC_PRESS_SOURCES), lo, hi))
            monthly_nonzero = dict(cur.fetchall())
    finally:
        conn.rollback()
        db._put_connection(conn)

    total_cnt = int(total_cnt or 0)
    dart_cnt = int(dart_cnt or 0)
    monthly = [(m, int(monthly_nonzero.get(m, 0))) for m in _month_range(start, end)]

    return {
        "total": total_cnt,
        "dart": dart_cnt,
        "dart_share": (dart_cnt / total_cnt) if total_cnt else float("nan"),
        "monthly": monthly,
        "computed_at": datetime.now(),
    }


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
        daily_ic, ic_summary, permutation_test, quantile_returns,
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

        # C1-1: 횡단면 크기(그날 유효 종목 수) 분포 — 4종목짜리 날과 107종목짜리
        # 날이 같은 "표본 충분" 취급을 받지 않도록 median/25·75백분위를 같이 찍는다.
        cs = _cross_section_stats(sub, "excess_h1")
        if cs:
            print(f"  횡단면 크기(일별 유효 종목 수, excess_h1 기준): "
                  f"중앙값 {cs['median']:.1f} · 25백분위 {cs['p25']:.1f} · "
                  f"75백분위 {cs['p75']:.1f} (n={cs['n_days']}일)")

        h1_stats = None  # 순열검정 표본 크기 표시에 재사용(h=1 IC 와 동일 표본)
        for h in HORIZONS:
            col = f"excess_h{h}"
            if col not in sub.columns or sub[col].notna().sum() == 0:
                continue
            ic = daily_ic(sub, ret_col=col)
            s = ic_summary(ic)
            obs = _ic_obs_count(sub, ic, ret_col=col)

            # 재지시 2번: IC 줄도 히트율 줄과 같은 종류의 표본 경고를 달아야
            # 한다 — hit_rate 만 걸러 두고 «핵심 숫자»인 평균IC/t 는 무경고로
            # 나가면, 이 지표가 근거한 표본(그날 유효 종목 3~5개)이 히트율
            # 쪽보다 덜 얇아 보인다는 착시를 만든다. 그 horizon(col) 자신의
            # 유효 종목 수 분포에서 중앙값을 그대로 이 줄에 실어 나른다 —
            # 숫자는 지우지 않고(_fmt_metric 은 NaN/inf 에만 반응한다),
            # 문턱 미달일 때만 ⚠ 를 덧붙인다.
            cs_h = _cross_section_stats(sub, col)
            median_cs = cs_h["median"] if cs_h else float("nan")
            ic_warn = ""
            if math.isfinite(median_cs) and median_cs < MIN_IC_CROSS_SECTION_FOR_WARN:
                ic_warn = (f" ⚠순위상관 표본 부족(횡단면 중앙값 {median_cs:.1f} < "
                           f"{MIN_IC_CROSS_SECTION_FOR_WARN})")

            # C1-2: 히트율은 그날 유효 종목이 top_n 을 «초과»하는 거래일만
            # 골라 낸다 — 안 그러면 top_n 이 그 날 전체 종목이 되어 버려
            # (예: prod_calendar 하루 평균 4.6종목) 히트율이 신호와 무관하게
            # 0.5 로 수렴한다. 걸러진 뒤 거래일이 하나도 안 남으면 NaN 을
            # 돌려주고 _fmt_metric 이 "측정불가" 로 찍는다. 라벨의 top_n·문턱
            # 표기는 HIT_RATE_TOP_N 에서 그대로 뽑아 쓴다(재지시 3번) — 상수를
            # 바꿔도 라벨이 실제 값과 어긋나지 않는다.
            hr, hr_n, hr_days = _hit_rate_wide_days_only(sub, col, top_n=HIT_RATE_TOP_N)
            hr_label = f"top{HIT_RATE_TOP_N},행가중,횡단면>{HIT_RATE_TOP_N}인 날만"
            print(f"  h{h}: 평균IC {_fmt_metric(s['mean_ic'], '+.4f')} "
                  f"(거래일 {s['n_days']}·관측 {obs}·횡단면 중앙값 "
                  f"{_fmt_metric(median_cs, '.1f')}){ic_warn} "
                  f"· t {_fmt_metric(s['t_stat'], '+.2f')} "
                  f"· 히트율({hr_label}) {_fmt_metric(hr, '.3f')} "
                  f"(관측 {hr_n}·거래일 {hr_days})")
            if h == 1:
                h1_stats = (s, obs)

        q = quantile_returns(sub, "excess_h1")
        if not q.empty:
            total_n = int(q["n"].sum())
            q_days = _quantile_days_used(sub, "composite_score", "excess_h1", 5)
            tie_med = q.attrs.get("tie_fraction_median", float("nan"))
            cells = " ".join(f"Q{int(r.quantile) + 1} {r.mean_excess:+.4f}(n={r.n})"
                             for r in q.itertuples())
            print(f"  h1 분위수(행가중, 관측 {total_n}·거래일 {q_days}): {cells}")
            print(f"  h1 분위수 동점(최다 동일점수) 비율 중앙값: "
                  f"{_fmt_metric(tie_med, '.3f')} — 클수록 아래 스프레드가 "
                  f"동점 처리(입력 순서)에 좌우된 값이라는 뜻이다(C2)")
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
          f"일별 IC 자기상관(t통계량은 참고값) · "
          f"수익 구간 정렬은 «다음 거래일» 이 아니라 «다음 관측행» 이다"
          f"(거래정지 등으로 하루가 빠지면 h1/h5 가 조용히 D+2/D+6 이 된다, I3)")
    print("※ 가중치 주의: 평균IC 는 «일자 가중»(거래일 1개 = 1표)이고, "
          "히트율·분위수는 «행 가중»(종목이 많은 날이 더 크게 반영)이다 — "
          "서로 다른 척도이니 같은 수치로 비교하지 마라 "
          "(실측 예: 동일 픽스처에서 히트율 행가중 0.833 vs 일자균등 0.5).")
    cg = _corpus_gap_stats(db, start, end)
    monthly_str = " · ".join(f"{m.strftime('%Y-%m')} {c:,}" for m, c in cg["monthly"])
    dart_share_str = _fmt_metric(cg["dart_share"], ".1%")
    print(f"※ 뉴스 코퍼스 공백(C1, {cg['computed_at']:%Y-%m-%d %H:%M} DB 실측 — "
          f"리터럴 아님): 국내 언론({'/'.join(DOMESTIC_PRESS_SOURCES)}) 월별 "
          f"기사 건수 — {monthly_str}. 이 구간 종목귀속 행 {cg['total']:,}건 중 "
          f"DART 공시가 {cg['dart']:,}건({dart_share_str})을 차지한다 — 국내 "
          f"언론이 0~수십 건뿐인 달은 신호가 실질적으로 DART 단독이다. DART 는 "
          f"15:30 이후 접수분에 쏠려 sector_1530 창(직전 15:30 부터)에는 잡히고 "
          f"prod_calendar 창(달력 하루, D-1 마감 후~자정 뉴스를 뺀다)에는 상당수가 "
          f"빠진다 — 그래서 두 창은 «창 정의» 뿐 아니라 «코퍼스 커버리지» 도 "
          f"다르다. 위 두 창의 지표를 나란히 놓아도 깨끗한 A/B 비교로 읽지 마라.")
    print(f"※ IC 표본 경고 기준(재지시 2번): 거래일별 횡단면(그 horizon 의 유효 "
          f"종목 수) 중앙값이 {MIN_IC_CROSS_SECTION_FOR_WARN} 미만이면 평균IC·t "
          f"줄에 ⚠ 를 붙인다 — n 이 이보다 작으면 그날 나올 수 있는 순위상관 "
          f"값 자체가 가능한 순열(n!) 수만큼의 이산값으로 쪼그라들어(예: n=4 면 "
          f"24가지) «상관계수를 쟀다» 기보다 «그날 어느 순열이 나왔는지 봤다» "
          f"에 가깝다. 히트율 경고와 같은 문턱(top_n={HIT_RATE_TOP_N})을 그대로 "
          f"쓴다 — 숫자는 지우지 않되(IC·t 는 항상 그대로 찍힌다) 근거 표본이 "
          f"얇다는 것만 눈에 보이게 한다.")
    print("※ 초과수익의 기준(I1): excess_h* 는 시장 전체가 아니라 «그 날 뉴스가 "
          "붙은 종목들» 의 횡단면 평균 대비다(index_daily/market_index 가 이 기간 "
          "중 약 4개월을 못 덮어 시장 대비를 계산할 수 없다, §0.6). IC·Q5-Q1 "
          "스프레드는 순위·상대비교라 이 기준으로도 유효하지만, 히트율을 «시장을 "
          "이겼다» 로 읽으면 안 된다 — 그 날 뉴스 종목 전체가 하락해도 히트율은 "
          "100%가 나올 수 있다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
