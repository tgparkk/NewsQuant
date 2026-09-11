"""daily_prices 를 as-of 시점까지만 읽는 가격 어댑터.

TradingAnalyzer 는 지금 PriceFetcher 로 «실시간» HTTP 를 종목당 1회 쏜다
(359종목 27초). 과거 시점으로 돌릴 수도 없고 느리다. 같은 호출 형태를
유지한 채 daily_prices 를 읽는 것으로 갈아끼운다.

핵심 규칙: as_of 날짜 «이전» 종가만 돌려준다. 신호 시각이 D 09:00 이면
그날 종가는 아직 존재하지 않으므로 D 를 포함하면 곧바로 미래 참조가 된다.
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# _adjust_for_price_reaction 이 iloc[3] 까지 보므로 넉넉히 담아 둔다.
LOOKBACK_ROWS = 10


class DailyPriceAsOf:
    """PriceFetcher 와 같은 자리에 꽂히는 as-of 가격 조회기."""

    def __init__(self, db, as_of: datetime):
        self.db = db
        self.as_of_date = as_of.date().isoformat()
        self._cache: Dict[str, pd.DataFrame] = {}
        self.query_count = 0

    def preload(self, stock_codes: List[str]) -> None:
        """여러 종목을 한 번에 담는다. 종목당 왕복을 없애는 것이 목적이다."""
        codes = sorted({c.strip() for c in stock_codes if c and c.strip()})
        if not codes:
            return
        rows = self._fetch(codes)
        self.query_count += 1
        by_code: Dict[str, list] = {c: [] for c in codes}
        for code, date_str, close in rows:
            by_code[code.strip()].append((date_str, close))
        for code, items in by_code.items():
            self._cache[code] = self._to_frame(items)

    def get_daily_price(self, stock_code: str, pages: int = 1) -> Optional[pd.DataFrame]:
        """pages 인자는 PriceFetcher 와 형태를 맞추기 위한 것으로 쓰지 않는다."""
        code = (stock_code or "").strip()
        if not code:
            return None
        if code not in self._cache:
            rows = self._fetch([code])
            self.query_count += 1
            self._cache[code] = self._to_frame([(d, c) for _, d, c in rows])
        df = self._cache[code]
        return None if df.empty else df

    def _fetch(self, codes: List[str]):
        conn = self.db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT stock_code, date, close FROM (
                        SELECT stock_code, date, close,
                               row_number() OVER (PARTITION BY stock_code
                                                  ORDER BY date DESC) rn
                        FROM daily_prices
                        WHERE trim(stock_code) = ANY(%s)
                          AND date < %s
                          AND close IS NOT NULL AND close > 0
                    ) t WHERE rn <= %s
                """, (codes, self.as_of_date, LOOKBACK_ROWS))
                return cur.fetchall()
        finally:
            conn.rollback()
            self.db._put_connection(conn)

    @staticmethod
    def _to_frame(items) -> pd.DataFrame:
        if not items:
            return pd.DataFrame(columns=["날짜", "종가"])
        df = pd.DataFrame(items, columns=["날짜", "종가"])
        df["날짜"] = df["날짜"].astype(str)
        df["종가"] = df["종가"].astype(float)
        return df.sort_values("날짜", ascending=False).reset_index(drop=True)
