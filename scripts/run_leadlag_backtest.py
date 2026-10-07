# scripts/run_leadlag_backtest.py
"""섹터 선행-후행 백테스트 — 점수 생성 → 수익 결합 → 측정 → 표.

    python scripts/run_leadlag_backtest.py                                  # H1 arm 포함 main 구간, both
    python scripts/run_leadlag_backtest.py --kind theme --period test=2026-08-01:2026-10-07 --permutations 50
    python scripts/run_leadlag_backtest.py --period main=2024-01-02:2026-10-07 --period aux=2021-01-04:2023-12-29 --out docs/superpowers/specs/leadlag_run.txt

설계: docs/superpowers/specs/2026-10-07-sector-leadlag-design.md

이 파일은 조립과 출력만 한다. 로직은 leadlag.py / returns.py / metrics.py 에
있고 거기서 테스트된다. 여기서 지키는 것:

1. NaN/inf 지표는 "측정불가" 로 찍는다(_fmt_metric, run_news_backtest 재사용).
2. 주 가설 arm(PRIMARY_ARM) 은 [H1] 표시와 함께 판정 줄을 따로 찍는다.
   판정 통계량은 HAC t·p(metrics.hac_t, lag=h+1)다. 나머지 arm 의 HAC p 는
   Holm 보정값을 나란히 찍는다. 순열 p 는 횡단면 독립을 가정해 그룹 구조에서
   과소추정되므로 참고로만 찍는다(스펙 §7, §13 개정 1).
3. 당일 IC(same_excess) 를 익일 IC 와 같은 줄에 둔다 — 동조화 판별표(§7).
4. 표본(거래일 수·횡단면 중앙값·평균·유효 그룹 수·그룹표 행 수)은 실행마다
   실측해 찍는다.
5. arm 세트(분류×구간)가 끝나는 대로 바로 찍는다 — 주 구간 실행은 수십 분이다.
   --permutations 0 이면 순열검정을 통째로 건너뛴다(빠른 재실행).
"""
import argparse
import logging
import math
import os
import sys
from datetime import date, datetime
from typing import Dict, List, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_news_backtest import _cross_section_stats, _fmt_metric, _ic_obs_count  # noqa: E402

PRIMARY_ARM = ("theme", "main", 1)          # (kind, period_name, horizon) — 스펙 §7
DEFAULT_PERIOD = "main=2024-01-02:2026-10-07"
HIT_TOP_NS = (10, 50)
N_QUANTILES = 5
SIG_LEVEL = 0.05          # 스펙 §7 — 통과 = HAC p < 0.05 이고 평균 IC > 0
SAME_DAY_IC_BIG = 0.05    # 스펙 §13 — 동조화 판별표의 「당일 IC 큼」 = 당일 IC > 0.05


def parse_period(s: str) -> Tuple[str, date, date]:
    """'NAME=YYYY-MM-DD:YYYY-MM-DD' → (name, start, end)."""
    if "=" not in s or ":" not in s:
        raise ValueError(f"--period 형식은 NAME=START:END 다: {s!r}")
    name, rng = s.split("=", 1)
    a, b = rng.split(":", 1)
    start = datetime.strptime(a, "%Y-%m-%d").date()
    end = datetime.strptime(b, "%Y-%m-%d").date()
    if not name or start > end:
        raise ValueError(f"--period 가 잘못됐다(이름 없음 또는 start > end): {s!r}")
    return name, start, end


def holm_adjust(pvals: Dict[str, float]) -> Dict[str, float]:
    """Holm step-down. 작은 p 부터 (m − 순위 + 1) 배, 앞 값보다 작아지지 않게,
    1 로 캡. NaN 은 보정 대상에서 빼고 NaN 그대로 돌려준다."""
    valid = {k: v for k, v in pvals.items() if v is not None and math.isfinite(v)}
    out: Dict[str, float] = {k: float("nan") for k in pvals if k not in valid}
    m = len(valid)
    running = 0.0
    for rank, (k, p) in enumerate(sorted(valid.items(), key=lambda kv: kv[1])):
        adj = min(1.0, max(running, p * (m - rank)))
        out[k] = adj
        running = adj
    return out


def _arm_key(kind: str, period: str, h: int) -> str:
    return f"{kind}·{period}·h{h}"


def _cross_section_mean(df: pd.DataFrame, ret_col: str, score_col: str = "score") -> float:
    """거래일별 유효 종목 수(횡단면 크기)의 평균 — 중앙값 옆에 나란히 찍는다."""
    sizes = df.dropna(subset=[score_col, ret_col]).groupby("trade_date").size()
    return float(sizes.mean()) if len(sizes) else float("nan")


def _run_arm_set(db, kind: str, period: str, start: date, end: date,
                 n_perm: int, lines: List[str]) -> Dict[str, dict]:
    """한 (분류, 구간) 에 대해 h0/h1/h5 를 돌리고 arm_key → 결과 dict 를 돌려준다.

    n_perm <= 0 이면 permutation_test 를 부르지 않는다(순열 p=생략)."""
    from news_scraper.backtest.leadlag import build_scores, load_groups, load_panel
    from news_scraper.backtest.metrics import (daily_ic, hac_t, hit_rate, ic_summary,
                                               permutation_test, quantile_returns)
    from news_scraper.backtest.returns import HORIZONS, attach_returns, load_returns

    groups = load_groups(db, kind)
    panel = load_panel(db, start, end)
    score_stats: dict = {}
    scores = build_scores(panel, groups, kind=kind, stats=score_stats)
    lines.append(f"\n[{kind} · {period} {start}~{end}] 그룹표 {len(groups):,}행"
                 f"(종목 {groups['stock_code'].nunique():,} · 그룹 {groups['group_id'].nunique():,})"
                 f" · 패널 {len(panel):,}행 · 거래일 {panel['date'].nunique()} · 점수 {len(scores):,}행"
                 f" · 유효 그룹 수(일평균) {_fmt_metric(score_stats.get('valid_groups_per_day'), '.1f')}")
    if scores.empty:
        lines.append("  관측 없음")
        return {}

    rets = load_returns(db, start, end)
    df = attach_returns(scores, rets)
    if df.empty:
        lines.append("  수익 결합 0행 — trade_date 형식(date 객체) 또는 기간을 확인하라")
        return {}
    lines.append(f"  수익 결합 {len(df):,}행 · 거래일 {df['trade_date'].nunique()}")

    same_ic = daily_ic(df, score_col="score", ret_col="same_excess")
    same_s = ic_summary(same_ic)
    lines.append(f"  당일(대조군) IC {_fmt_metric(same_s['mean_ic'], '+.4f')} "
                 f"· t {_fmt_metric(same_s['t_stat'], '+.2f')} · 거래일 {same_s['n_days']}")

    results: Dict[str, dict] = {}
    for h in HORIZONS:
        col = f"excess_h{h}"
        if col not in df.columns or df[col].notna().sum() == 0:
            continue
        ic = daily_ic(df, score_col="score", ret_col=col)
        s = ic_summary(ic)
        hac = hac_t(ic, lag=h + 1)     # h1/h5 수익 구간의 겹침까지 덮도록 lag = h+1 (스펙 §13)
        obs = _ic_obs_count(df, ic, score_col="score", ret_col=col)
        cs = _cross_section_stats(df, col, score_col="score")
        med = cs["median"] if cs else float("nan")
        cs_mean = _cross_section_mean(df, col)
        hrs = {n: hit_rate(df, col, top_n=n, score_col="score") for n in HIT_TOP_NS}
        if n_perm > 0:
            perm = permutation_test(df, col, n_iter=n_perm, score_col="score")
            p_perm = perm["p_value"]
            perm_str = f"순열 p={_fmt_metric(p_perm, '.3f')} ({perm['n_iter']}회, 참고)"
        else:
            p_perm = float("nan")
            perm_str = "순열 p=생략"
        key = _arm_key(kind, period, h)
        tag = " [H1]" if (kind, period, h) == PRIMARY_ARM else ""
        results[key] = {"kind": kind, "period": period, "start": start, "end": end, "h": h,
                        "summary": s, "p_perm": p_perm, "perm_skipped": n_perm <= 0,
                        "p_hac": hac["p_hac"], "t_hac": hac["t_hac"], "se_hac": hac["se_hac"],
                        "lag": hac["lag"], "same_ic": same_s["mean_ic"], "tag": tag}
        hr_str = " · ".join(f"히트율top{n} {_fmt_metric(v, '.3f')}" for n, v in hrs.items())
        lines.append(f"  h{h}{tag}: 평균IC {_fmt_metric(s['mean_ic'], '+.4f')} "
                     f"(거래일 {s['n_days']}·관측 {obs:,}·횡단면 중앙값 {_fmt_metric(med, '.0f')}"
                     f"·평균 {_fmt_metric(cs_mean, '.0f')}) "
                     f"· HAC t {_fmt_metric(hac['t_hac'], '+.2f')} (lag {hac['lag']}) "
                     f"· HAC p={_fmt_metric(hac['p_hac'], '.3f')} · {hr_str} · {perm_str}")

    q = quantile_returns(df, "excess_h1", n_q=N_QUANTILES, score_col="score")
    if not q.empty:
        cells = " ".join(f"Q{int(r.quantile) + 1} {r.mean_excess:+.4f}(n={r.n:,})"
                         for r in q.itertuples())
        spread = q["mean_excess"].iloc[-1] - q["mean_excess"].iloc[0]
        lines.append(f"  h1 분위수(행가중): {cells} · Q5-Q1 {_fmt_metric(spread, '+.4f')} "
                     f"· 동점비율 중앙값 {_fmt_metric(q.attrs.get('tie_fraction_median'), '.3f')}")
    return results


def _verdict(primary: dict) -> str:
    """스펙 §7(§13 개정 1) — 통과 = HAC p<0.05 & 평균IC>0. 동조화 판별표의 읽기를
    같이 적는다. 당일 IC 가 작으면(≤ SAME_DAY_IC_BIG) 통과·실패와 무관하게 표의
    마지막 행(「분류가 그룹을 못 묶는다」)으로 읽는다. 구간 범위를 같이 찍어 어느
    실행의 판정인지 줄 하나로 알 수 있게 한다."""
    s, p, t, same = primary["summary"], primary["p_hac"], primary["t_hac"], primary["same_ic"]
    span = f"{primary['period']} {primary['start']}~{primary['end']}"
    if not (math.isfinite(s["mean_ic"]) and math.isfinite(p)):
        return (f"H1 판정 [{span}]: 측정불가 — 평균IC {_fmt_metric(s['mean_ic'], '+.4f')}, "
                f"HAC t {_fmt_metric(t, '+.2f')}, HAC p={_fmt_metric(p, '.3f')}")
    passed = p < SIG_LEVEL and s["mean_ic"] > 0
    reversal = p < SIG_LEVEL and s["mean_ic"] < 0
    if not math.isfinite(same):
        reading = "당일 IC 측정불가"
    elif same <= SAME_DAY_IC_BIG:
        reading = "당일 IC 작음 → 분류가 그룹을 못 묶는다 — 다른 분류 결과와 비교"
    elif passed:
        reading = "선행-후행 있음 → 스펙 §9"
    elif reversal:
        reading = "익일 되돌림 → 별건"
    else:
        reading = "동조화뿐, 알파 아님 → 끝"
    return (f"H1 판정 [{span}]: {'통과' if passed else '실패'} — 평균IC {s['mean_ic']:+.4f}, "
            f"HAC t {t:+.2f} (lag {primary['lag']}), HAC p={p:.3f}, "
            f"당일 IC {_fmt_metric(same, '+.4f')} → {reading}")


def _emit(lines: List[str], start: int) -> int:
    """lines[start:] 를 바로 찍고(flush) 다음 시작 위치를 돌려준다. 파이프나
    리다이렉트로 받아도 arm 세트가 끝나는 대로 보이게 한다."""
    if len(lines) > start:
        print("\n".join(lines[start:]), flush=True)
    return len(lines)


def _write_out(path, lines: List[str]) -> None:
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=("theme", "wics", "both"), default="both")
    ap.add_argument("--period", action="append", default=None,
                    help="NAME=START:END (반복 가능). 기본 " + DEFAULT_PERIOD)
    ap.add_argument("--permutations", type=int, default=500)
    ap.add_argument("--out", default=None, help="출력을 이 파일에도 저장")
    args = ap.parse_args()

    from news_scraper.backtest.leadlag import KINDS, THEME_SNAP_DATE
    from news_scraper.database import NewsDatabase

    kinds = list(KINDS) if args.kind == "both" else [args.kind]
    periods = [parse_period(p) for p in (args.period or [DEFAULT_PERIOD])]
    db = NewsDatabase()

    lines: List[str] = [f"섹터 선행-후행 백테스트 · {datetime.now():%Y-%m-%d %H:%M} · "
                        f"테마 스냅샷 {THEME_SNAP_DATE} · 순열 {args.permutations}회"]
    printed = _emit(lines, 0)
    results: Dict[str, dict] = {}
    for name, start, end in periods:
        for kind in kinds:
            results.update(_run_arm_set(db, kind, name, start, end, args.permutations, lines))
            printed = _emit(lines, printed)

    lines.append("\n" + "=" * 74)
    if not results:
        lines.append("관측 없음")
        _emit(lines, printed)
        _write_out(args.out, lines)
        return 1

    primary_key = _arm_key(*PRIMARY_ARM)
    secondary = {k: v["p_hac"] for k, v in results.items() if k != primary_key}
    adj = holm_adjust(secondary)
    lines.append(f"arm 표 (판정 = HAC p · Holm m={len(secondary)}: 부 가설 arm 의 HAC p 보정, "
                 f"주 가설은 보정 없음 · 순열 p 는 참고):")
    for k, v in results.items():
        s = v["summary"]
        padj = "—(H1)" if k == primary_key else _fmt_metric(adj.get(k), ".3f")
        pperm = "생략" if v["perm_skipped"] else _fmt_metric(v["p_perm"], ".3f")
        lines.append(f"  {k:<24} IC {_fmt_metric(s['mean_ic'], '+.4f')} "
                     f"· HAC t {_fmt_metric(v['t_hac'], '+.2f')} "
                     f"· HAC p {_fmt_metric(v['p_hac'], '.3f')} "
                     f"· Holm(HAC p) {padj} "
                     f"· 순열 p(참고) {pperm} "
                     f"· 당일IC {_fmt_metric(v['same_ic'], '+.4f')}")
    if primary_key in results:
        lines.append(_verdict(results[primary_key]))
    else:
        lines.append("H1 arm(theme·main·h1) 이 이번 실행에 없다 — 판정 생략")

    lines.append("한계: 테마·WICS 소속표는 현재 스냅샷을 과거에 적용(미래 참조, 결과는 상한선) · "
                 "생존 편향(상장폐지 종목 없음) · 수정주가 부재(±30% 밖만 제거) · "
                 "h1/h5 는 «다음 관측행»(거래정지 결측 시 D+2/D+6) · 밤사이 갭 미측정 · "
                 "판정은 HAC t(Newey-West, lag=h+1) · 순열 p 는 횡단면 독립을 가정해 "
                 "그룹 구조에서 과소추정되므로 참고만(§7 개정) · "
                 "평균IC 는 일자 가중, 히트율·분위수는 행 가중")

    _emit(lines, printed)
    _write_out(args.out, lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
