"""주가 일봉 조회 — 공유 DB(kis_template) `daily_prices`(KRX 일봉).

2026-09-18 네이버 금융 옛 일별 시세 페이지(finance.naver.com/item/sise_day.naver)가
HTTP 410 Gone 으로 폐기됐다(옛 sise/main 페이지는 stock.naver.com 으로 302). 그 뒤
매 요청이 실패해 선반영 체크(trading_analyzer._adjust_for_price_reaction)가 조용히
무력화됐다. 새 네이버 API(m.stock.naver.com)는 종가가 NXT 애프터마켓 포함이라 KRX
종가와 다르다(2026-10-09 실측 8종목 80일 중 65일 불일치). 그래서 백테스트
(`backtest/price_asof.DailyPriceAsOf`)와 같은 기준인 KRX `daily_prices` 를 읽는다.

장중에는 그날 봉이 아직 없다 — 첫 행은 직전 거래일 종가다(RoboTrader 가 장 마감 뒤 채운다).
메서드·열 이름·pages 의미는 옛 네이버 수집기 그대로라 호출부는 바꾸지 않는다.
"""
import logging
from typing import Optional, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

ROWS_PER_PAGE = 10          # 옛 네이버 페이지 1쪽 = 10거래일 — pages 인자 의미를 유지한다
COLUMNS = ['날짜', '종가', '전일비', '시가', '고가', '저가', '거래량']
# stock_code 를 식으로 감싸지 않는다(trim 등) — PK(stock_code, date) 인덱스를 못 타 324만 행
# 풀스캔이 된다(종목당 0.36초 → 0.1ms). 코드는 호출 전에 strip 하고, 공백 붙은 코드는 0행(2026-10-09 실측).
_SELECT = ("SELECT date, close, open, high, low, volume FROM daily_prices "
           "WHERE stock_code = %s AND close IS NOT NULL AND close > 0 ")


def to_frame(rows: Sequence[tuple]) -> pd.DataFrame:
    """(date, close, open, high, low, volume) 행 → 옛 네이버 표와 같은 열·형(최신순).

    전일비 = 종가 − 바로 앞 거래일 종가(부호 있음). 가장 옛 행은 앞 종가가 없어 NaN.
    거래량은 원값(adj_factor 미적용) — 옛 네이버 표와 같다.
    """
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(list(rows), columns=['날짜', '종가', '시가', '고가', '저가', '거래량'])
    df['날짜'] = pd.to_datetime(df['날짜'].astype(str))
    for col in ['종가', '시가', '고가', '저가', '거래량']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.sort_values('날짜', ascending=False).reset_index(drop=True)
    df['전일비'] = df['종가'] - df['종가'].shift(-1)
    return df[COLUMNS]


class PriceFetcher:
    """주가 일봉 조회기(daily_prices · KRX). db 를 주지 않으면 처음 쓸 때 NewsDatabase 를 연다."""

    def __init__(self, db=None):
        self._db = db

    @property
    def db(self):
        if self._db is None:
            from .database import NewsDatabase
            self._db = NewsDatabase()
        return self._db

    def get_daily_price(self, stock_code: str, pages: int = 1) -> pd.DataFrame:
        """최근 pages×10 거래일 일봉(최신순). 열 = 날짜·종가·전일비·시가·고가·저가·거래량."""
        code = (stock_code or '').strip()
        if not code or pages < 1:
            return pd.DataFrame(columns=COLUMNS)
        n = pages * ROWS_PER_PAGE
        # 한 행 더 읽어 마지막 행의 전일비도 채운다
        rows = self._query(_SELECT + "ORDER BY date DESC LIMIT %s", (code, n + 1))
        return to_frame(rows).head(n)

    def get_price_at_date(self, stock_code: str, target_date: str) -> dict:
        """target_date(YYYY-MM-DD) 그날 일봉. 그날 봉이 없으면(휴장·정지·미수집) {}."""
        code = (stock_code or '').strip()
        if not code:
            return {}
        day = pd.to_datetime(target_date).date().isoformat()
        df = to_frame(self._query(_SELECT + "AND date <= %s ORDER BY date DESC LIMIT 2", (code, day)))
        if df.empty or df['날짜'].iloc[0].date().isoformat() != day:
            return {}
        result = df.iloc[0].to_dict()
        result['날짜'] = day
        return result

    def _query(self, sql: str, args: tuple) -> list:
        conn = self.db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                return cur.fetchall()
        finally:
            # 풀 반환은 rollback 실패로도 생략되면 안 된다(분석기가 종목마다 부른다).
            try:
                conn.rollback()
            except Exception:
                pass
            self.db._put_connection(conn)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(PriceFetcher().get_daily_price("005930").head())
