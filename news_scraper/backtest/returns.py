"""신호에 이후 수익을 붙이고 초과수익을 만든다.

진입은 D 시가다 — 봇이 09:00 에 후보를 읽고 개장에 매매하는 규약과 맞춘다.
청산은 D 종가 / D+1 종가 / D+5 종가 셋을 모두 잰다.

초과수익은 «일별 횡단면 평균 차감» 이다. 지수를 쓰지 않는 이유는 데이터가
없기 때문이다 — market_index 는 2026-02-12 에서 끊기고 index_daily 는
2026-06-15 부터라 169 거래일 중 넉 달이 빈다. IC 는 어차피 순위상관이라
횡단면이고 시장중립이다.

daily_prices.returns_1d 는 (close-prev)/prev 의 «소수» 이고 수정주가가
아니다. 거래소 일간 가격제한폭이 ±30% 이므로 그걸 넘는 값은 정의상 수익이
아니라 기업행위다 — 2026년 430,912건 중 441건(0.102%)뿐이다.
"""
import logging
from datetime import date
from typing import List

import pandas as pd

logger = logging.getLogger(__name__)

HORIZONS = (0, 1, 5)
CORPORATE_ACTION_LIMIT = 0.30


def load_returns(db, start: date, end: date) -> pd.DataFrame:
    """거래일별 (종목, 진입 시가 기준 수익). 기업행위 구간은 뺀다."""
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                WITH p AS (
                    SELECT trim(stock_code) AS stock_code, date, open, close, returns_1d,
                           row_number() OVER (PARTITION BY trim(stock_code)
                                              ORDER BY date) rn
                    FROM daily_prices
                    WHERE date >= %s AND date <= %s
                      AND open > 0 AND close > 0
                ), f AS (
                    -- 진입일부터 D+5 까지 «어느 하루라도» 제한폭을 넘었는지 본다.
                    -- 중간 하루만 분할이어도 h5 수익이 통째로 망가진다.
                    SELECT p.*,
                           GREATEST(
                             COALESCE(abs(returns_1d), 0),
                             COALESCE(MAX(abs(returns_1d)) OVER (
                                 PARTITION BY stock_code ORDER BY rn
                                 ROWS BETWEEN 1 FOLLOWING AND 5 FOLLOWING), 0)
                           ) AS max_abs_move
                    FROM p
                )
                SELECT e.stock_code, e.date, e.open,
                       h0.close, h1.close, h5.close, e.max_abs_move
                FROM f e
                LEFT JOIN p h0 ON h0.stock_code = e.stock_code AND h0.rn = e.rn
                LEFT JOIN p h1 ON h1.stock_code = e.stock_code AND h1.rn = e.rn + 1
                LEFT JOIN p h5 ON h5.stock_code = e.stock_code AND h5.rn = e.rn + 5
            """, (start.isoformat(), end.isoformat()))
            rows = cur.fetchall()
    finally:
        conn.rollback()
        db._put_connection(conn)

    out: List[dict] = []
    for code, d, open_, c0, c1, c5, max_move in rows:
        if max_move is not None and max_move > CORPORATE_ACTION_LIMIT:
            continue
        # returns_1d(전일 종가 대비) 창 검사만으로는 못 잡는 경우가 실제로 있다 —
        # returns_1d 가 NULL(신규상장 등 전일 종가 없음)이거나, 당일 시가가
        # 밴드 하단, 종가가 밴드 상단에 걸리면 종가 대비 등락은 ±30% 안이어도
        # «시가 대비» 등락(ret_h0)은 그걸 넘을 수 있다. h1/h5 는 같은 진입
        # 시가를 분모로 쓰므로 시가 자체가 의심스러우면 셋 다 버린다.
        ret_h0 = None if c0 is None else (c0 - open_) / open_
        if ret_h0 is not None and abs(ret_h0) > CORPORATE_ACTION_LIMIT:
            continue
        rec = {"trade_date": pd.Timestamp(d).date(), "stock_code": code, "ret_h0": ret_h0}
        for h, close in ((1, c1), (5, c5)):
            rec[f"ret_h{h}"] = None if close is None else (close - open_) / open_
        out.append(rec)
    return pd.DataFrame(out)


def attach_returns(signals: pd.DataFrame, rets: pd.DataFrame) -> pd.DataFrame:
    """신호에 수익을 붙이고 거래일·창별 횡단면 평균을 뺀다."""
    if signals.empty or rets.empty:
        return pd.DataFrame()

    df = signals.merge(rets, on=["trade_date", "stock_code"], how="inner")

    # 기업행위는 load_returns 가 이미 뺐지만, 직접 만든 표로 부를 수도 있다.
    # 한 horizon 이라도 제한폭을 넘으면 같은 진입(시가)을 공유하는 나머지
    # horizon 도 같이 못 믿는다 — 관측 전체(행)를 버린다.
    ret_cols = [f"ret_h{h}" for h in HORIZONS if f"ret_h{h}" in df.columns]
    if ret_cols:
        corporate_action = pd.Series(False, index=df.index)
        for col in ret_cols:
            corporate_action |= df[col].abs() > CORPORATE_ACTION_LIMIT
        df = df[~corporate_action].reset_index(drop=True)

    for h in HORIZONS:
        col = f"ret_h{h}"
        if col not in df.columns:
            continue
        grp = df.groupby(["trade_date", "window_kind"])[col]
        df[f"excess_h{h}"] = df[col] - grp.transform("mean")

    keep = df[[f"ret_h{h}" for h in HORIZONS]].notna().any(axis=1)
    return df[keep].reset_index(drop=True)
