"""섹터 선행-후행 — 「전날 같은 그룹이 시장보다 올랐으면 익일 더 오르는가」.

설계: docs/superpowers/specs/2026-10-07-sector-leadlag-design.md

점수(스펙 §4):
    g_i(D)   = 그룹 g 의 D 수익 평균, i 자신 제외        (n_g(D) >= MIN_MEMBERS 일 때만)
    resid    = g_i(D) − m(D)                              (m = 그날 패널 전체 평균)
    score_i  = i 가 속한 그룹들의 resid 평균
    trade_date = D 의 다음 거래일 (봇은 다음 날 09:00 에 읽고 시가에 들어간다)

이 모듈은 DB 를 읽기만 한다(load_panel/load_groups). 나머지는 순수 함수다.
기업행위 판정(±30%)은 returns.CORPORATE_ACTION_LIMIT 를 그대로 쓴다.
"""
import logging
from datetime import date
from typing import Dict, Sequence

import pandas as pd

from news_scraper.backtest.returns import CORPORATE_ACTION_LIMIT

logger = logging.getLogger(__name__)

PANEL_COLUMNS = ("date", "stock_code", "ret")


def clean_panel(raw: pd.DataFrame) -> pd.DataFrame:
    """daily_prices 모양 프레임 → (date, stock_code, ret) 패널.

    - date 는 TEXT 일 수 있다 → datetime.date 로 바꾼다(안 그러면 load_returns
      결과와 병합이 조용히 0 행이 된다).
    - 기업행위 행 제거: |returns_1d| > CORPORATE_ACTION_LIMIT, NULL, open/close <= 0.
    - stock_code trim 후 같은 (date, stock_code) 는 첫 행만 남긴다.
    """
    if raw.empty:
        return pd.DataFrame(columns=list(PANEL_COLUMNS))

    df = raw.copy()
    df["stock_code"] = df["stock_code"].astype(str).str.strip()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["returns_1d"] = pd.to_numeric(df["returns_1d"], errors="coerce")
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")

    keep = (df["returns_1d"].notna()
            & (df["returns_1d"].abs() <= CORPORATE_ACTION_LIMIT)
            & (df["open"] > 0) & (df["close"] > 0))
    df = df[keep]

    df = (df.rename(columns={"returns_1d": "ret"})[list(PANEL_COLUMNS)]
            .drop_duplicates(subset=["date", "stock_code"], keep="first")
            .sort_values(["date", "stock_code"])
            .reset_index(drop=True))
    df["ret"] = df["ret"].astype(float)
    return df


def load_panel(db, start: date, end: date) -> pd.DataFrame:
    """daily_prices [start, end] 를 읽어 clean_panel 로 정제한다. 필터는 전부
    clean_panel 에서 한다(테스트 가능한 한 곳)."""
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT stock_code, date, open, close, returns_1d
                FROM daily_prices
                WHERE date >= %s AND date <= %s
                ORDER BY date, stock_code
            """, (start.isoformat(), end.isoformat()))
            rows = cur.fetchall()
    finally:
        conn.rollback()
        db._put_connection(conn)
    raw = pd.DataFrame(rows, columns=["stock_code", "date", "open", "close", "returns_1d"])
    return clean_panel(raw)


def next_trading_day_map(dates: Sequence[date]) -> Dict[date, date]:
    """거래일 목록 → {D: D 의 다음 거래일}. «다음 거래일» 은 달력 +1 이 아니라
    목록에 있는 다음 날짜다(주말·연휴 자동 건너뜀). 마지막 날짜는 키에 없다."""
    uniq = sorted(set(dates))
    return {d: nxt for d, nxt in zip(uniq, uniq[1:])}
