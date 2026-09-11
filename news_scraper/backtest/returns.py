"""신호에 이후 수익을 붙이고 초과수익을 만든다.

진입은 D 시가다 — 봇이 09:00 에 후보를 읽고 개장에 매매하는 규약과 맞춘다.
청산은 D 종가 / D+1 종가 / D+5 종가 셋을 모두 잰다.

초과수익은 «일별 횡단면 평균 차감» 이다. 지수를 쓰지 않는 이유는 데이터가
없기 때문이다 — market_index 는 2026-02-12 에서 끊기고 index_daily 는
2026-06-15 부터라 169 거래일 중 넉 달이 빈다. IC 는 어차피 순위상관이라
횡단면이고 시장중립이다.

daily_prices.returns_1d 는 (close-prev)/prev 의 «소수» 이고 수정주가가
아니다. 거래소 일간 가격제한폭 ±30% 는 «종가 대 전일 종가» 에 걸리는
규칙이다 — «시가 대 종가»(ret_h0) 는 이 규칙의 대상이 아니다. 상한가
근처에서 열려 하한가 근처에서 닫히는(또는 반대) 날은 이 규칙을 어기지
않으면서도 시가 대비로는 30% 를 크게 넘을 수 있다 — 그런 날이 바로 뉴스
신호가 있다면 가장 크게 반응했을 날이라, ret_h0 자체에 ±30% 를 걸면
연구 대상인 극단값을 결과에 유리한 방향으로(상관을 0쪼으로) 지워버린다.
그래서 기업행위 판정은 returns_1d 창(당일 및 D+5 까지의 종가-종가) 에만
건다 — 2026년 430,912건 중 441건(0.102%)뿐이다. returns_1d 가 NULL(신규
상장 등 전일 종가가 없음) 인 진입일도 같은 이유로 뺀다 — 그 날은
«시가 대비» 판단 자체가 근거가 없다.
"""
import logging
from datetime import date, timedelta
from typing import List

import pandas as pd

logger = logging.getLogger(__name__)

HORIZONS = (0, 1, 5)
CORPORATE_ACTION_LIMIT = 0.30

# h5(5거래일 뒤 종가)를 구하려면 end 뒤의 가격도 읽어야 한다. 거래소
# 공휴일이 이어져도 10 달력일이면 5 거래일을 덮는다.
_FORWARD_PAD_DAYS = 10


def load_returns(db, start: date, end: date) -> pd.DataFrame:
    """거래일별 (종목, 진입 시가 기준 수익). 기업행위 구간은 뺀다.

    daily_prices 조회 상한은 end 가 아니라 end + 10 달력일이다 — 안 그러면
    요청 범위 «마지막» 며칠의 신호는 h1/h5 를 구할 가격이 아직 안 읽혀
    전부 NaN 이 된다. 진입(entry) 자체는 마지막 WHERE 로 [start, end]
    안으로만 되돌린다 — 반환되는 trade_date 는 항상 요청 범위 안이다.
    """
    padded_end = end + timedelta(days=_FORWARD_PAD_DAYS)
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
                    -- 중간 하루만 분할이어도 h5 수익이 통째로 망가진다. p 전체
                    -- (padded_end 까지) 에 대해 계산해야 end 근처 진입일도
                    -- D+5 까지 제대로 본다.
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
                       h0.close, h1.close, h5.close, e.max_abs_move, e.returns_1d
                FROM f e
                LEFT JOIN p h0 ON h0.stock_code = e.stock_code AND h0.rn = e.rn
                LEFT JOIN p h1 ON h1.stock_code = e.stock_code AND h1.rn = e.rn + 1
                LEFT JOIN p h5 ON h5.stock_code = e.stock_code AND h5.rn = e.rn + 5
                WHERE e.date <= %s
            """, (start.isoformat(), padded_end.isoformat(), end.isoformat()))
            rows = cur.fetchall()
    finally:
        conn.rollback()
        db._put_connection(conn)

    out: List[dict] = []
    for code, d, open_, c0, c1, c5, max_move, returns_1d in rows:
        if max_move is not None and max_move > CORPORATE_ACTION_LIMIT:
            continue
        if returns_1d is None:
            # 전일 종가가 없다(신규상장 등) — 판단 근거가 없으니 뺀다.
            continue
        rec = {"trade_date": pd.Timestamp(d).date(), "stock_code": code}
        for h, close in ((0, c0), (1, c1), (5, c5)):
            rec[f"ret_h{h}"] = None if close is None else (close - open_) / open_
        out.append(rec)
    return pd.DataFrame(out)


def attach_returns(signals: pd.DataFrame, rets: pd.DataFrame) -> pd.DataFrame:
    """신호에 수익을 붙이고 거래일·창별 횡단면 평균을 뺀다.

    반환하는 프레임은 excess_h0/h1/h5 중 «일부만» NaN 일 수 있다 — 예를
    들어 D+4 에 분할이 나면 h5 만 못 믿을 뿐 h0/h1 은 이미 실현되어
    유효하다. 같은 진입을 공유한다고 해서 다른 horizon 까지 같이 버리지
    않는다. Task 7 은 이 프레임을 «컬럼 단위» 로 다뤄야 한다 — 행 단위로
    dropna 하면 멀쩡한 h0/h1 까지 잃는다.
    """
    if signals.empty or rets.empty:
        return pd.DataFrame()

    df = signals.merge(rets, on=["trade_date", "stock_code"], how="inner")

    for h in HORIZONS:
        col = f"ret_h{h}"
        if col not in df.columns:
            continue
        if h != 0:
            # 기업행위는 load_returns 가 이미 뺐지만, 직접 만든 표로 부를
            # 수도 있다. 이 horizon 만 못 믿는 것이니 이 컬럼만 null 처리
            # 한다 — 다른 horizon 을 같이 버리면 실현된 유효한 수익까지
            # 잃는다(위 참고). h0(시가 대 종가)에는 걸지 않는다 — ±30%
            # 는 «종가 대 전일종가» 규칙이라 h0 에는 적용 대상이 아니고,
            # 여기서 걸면 load_returns 에서 뺀(모듈 docstring) 상한가·
            # 하한가 세션의 ret_h0 를 이 안전망이 다시 지워버린다.
            df.loc[df[col].abs() > CORPORATE_ACTION_LIMIT, col] = None
        grp = df.groupby(["trade_date", "window_kind"])[col]
        df[f"excess_h{h}"] = df[col] - grp.transform("mean")

    keep = df[[f"ret_h{h}" for h in HORIZONS]].notna().any(axis=1)
    return df[keep].reset_index(drop=True)
