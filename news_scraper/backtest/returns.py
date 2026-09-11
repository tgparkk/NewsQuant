"""신호에 이후 수익을 붙이고 초과수익을 만든다.

진입은 D 시가다 — 봇이 09:00 에 후보를 읽고 개장에 매매하는 규약과 맞춘다.
청산은 D 종가 / D+1 종가 / D+5 종가 셋을 모두 잰다.

초과수익은 «일별 횡단면 평균 차감» 이다. 지수를 쓰지 않는 이유는 데이터가
없기 때문이다 — market_index 는 2026-02-12 에서 끊기고 index_daily 는
2026-06-15 부터라 169 거래일 중 넉 달이 빈다. IC 는 어차피 순위상관이라
횡단면이고 시장중립이다.

기업행위(±30% 규칙) 판정은 «이 파일에서 딱 한 곳» — load_returns 안에서
returns_1d 로만 한다. daily_prices.returns_1d 는 (close-prev)/prev 의
«소수» 이고 수정주가가 아니다. 거래소 일간 가격제한폭 ±30% 는 정확히
이 값(«종가 대 전일 종가»)에 걸리는 규칙이므로, returns_1d 가 그 한도를
넘으면 정의상 수익이 아니라 기업행위다 — 2026년 430,912건 중 441건
(0.102%)뿐이다. returns_1d 가 NULL(신규상장 등 전일 종가가 없음)인
진입일도 같은 이유로 뺀다 — 그 날은 판단 근거 자체가 없다.

그 외의 어떤 값도(ret_h0/h1/h5, 즉 «시가 대 종가»·«시가 대 D+1 종가»·
«시가 대 D+5 종가») ±30% 규칙의 대상이 아니다 — 이 규칙은 언제나 «전일
종가 대비 하루» 를 재는 규칙이라, 시가를 기준점으로 삼거나 여러 날을
누적하는 순간 더는 이 규칙이 바인딩하지 않는다. 실측(2026-01-01~09-11,
returns_1d 창 통과 후): ret_h0 는 436,197건 중 280건(0.06%, 상한가/하한가
세션)이 30% 를 넘고, ret_h1(2세션 누적)은 433,417건 중 1,967건(0.45%),
ret_h5(6세션 누적)은 422,353건 중 10,105건(2.39%)이 넘는다 — 연속
상한가만 이틀이면 누적 +69%를 넘으므로 이건 전부 정상적인 수익이다.
attach_returns 가 이 값들에 같은 ±30% 를 다시 걸면(과거에 실제로 그런
버그가 있었다) 연구 대상인 극단값을 결과에 유리한 방향으로(상관을
0쪽으로) 지우는 outcome-dependent truncation 이 된다 — h5 가 가장 크게
영향받는데, 느리게 퍼지는 뉴스 효과가 가장 있을 법한 지점이 바로 거기다.
그래서 attach_returns 는 입력을 그대로 믿고 «병합·차감만» 한다.
"""
import logging
from datetime import date, timedelta
from typing import List

import pandas as pd

logger = logging.getLogger(__name__)

HORIZONS = (0, 1, 5)
CORPORATE_ACTION_LIMIT = 0.30

# h5(5거래일 뒤 종가)를 구하려면 end 뒤의 가격도 읽어야 한다. 달력일이
# 아니라 «거래일» 5개를 덮어야 하는데, 연휴가 겹치면 달력일 간격이
# 꽤 벌어진다 — 실측(trading_days(), 2026-01-01~09-11, 171 거래일)으로
# 진입일→5거래일뒤 캘린더 갭의 최댓값이 12일이었다(2026-02-11→02-23,
# 설 연휴+주말). 여기에 여유를 얹어 15로 잡는다.
_FORWARD_PAD_DAYS = 15


def load_returns(db, start: date, end: date) -> pd.DataFrame:
    """거래일별 (종목, 진입 시가 기준 수익). 기업행위 구간은 뺀다.

    기업행위 판정은 «여기 한 곳» 뿐이다(모듈 docstring) — returns_1d 창이
    당일부터 D+5 까지 하루라도 ±30% 를 넘으면 그 진입 전체를 버리고,
    진입일 자체의 returns_1d 가 NULL(신규상장 등)이어도 버린다. ret_h0/
    h1/h5 자체에는 이 한도를 걸지 않는다 — attach_returns 도 마찬가지다.

    daily_prices 조회 상한은 end 가 아니라 end + 15 달력일이다 — 안 그러면
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

    기업행위 판정은 하지 않는다 — 그건 load_returns 의 몫이다(모듈
    docstring). 여기서는 입력을 그대로 믿고 병합·차감만 한다. ret_h0/h1/
    h5 가 얼마나 크든(예: 연속 상한가로 누적 h5 가 70% 든) 그대로 쓴다.

    반환하는 프레임은 excess_h0/h1/h5 중 «일부만» NaN 일 수 있다 — 예를
    들어 load_returns 가 넘겨준 rets 에 D+4 이후 가격이 아직 없어 h5 만
    없는 경우다. 같은 진입을 공유한다고 해서 다른 horizon 까지 같이
    버리지 않는다. Task 7 은 이 프레임을 «컬럼 단위» 로 다뤄야 한다 —
    행 단위로 dropna 하면 멀쩡한 다른 horizon 까지 잃는다.
    """
    if signals.empty or rets.empty:
        return pd.DataFrame()

    df = signals.merge(rets, on=["trade_date", "stock_code"], how="inner")

    for h in HORIZONS:
        col = f"ret_h{h}"
        if col not in df.columns:
            continue
        grp = df.groupby(["trade_date", "window_kind"])[col]
        df[f"excess_h{h}"] = df[col] - grp.transform("mean")

    keep = df[[f"ret_h{h}" for h in HORIZONS]].notna().any(axis=1)
    return df[keep].reset_index(drop=True)
