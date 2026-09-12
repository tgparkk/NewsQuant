"""실 DB 왕복 — as-of 가격 어댑터.

백테스트에서 가장 조용히 틀리는 게 미래 참조다. 어댑터가 as_of 이후 종가를
«절대» 돌려주지 않는다는 것이 이 파일의 존재 이유다.
"""
from datetime import datetime

import pytest

from news_scraper.backtest.price_asof import DailyPriceAsOf

pytestmark = pytest.mark.db

CODE = "005930"          # 삼성전자 — daily_prices 에 확실히 있다
AS_OF = datetime(2026, 6, 15, 9, 0, 0)


def test_as_of_이후_날짜를_돌려주지_않는다(db):
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)

    df = fetcher.get_daily_price(CODE)

    assert df is not None and len(df) > 0
    assert df["날짜"].max() < "2026-06-15"


def test_최신_날짜가_맨_앞이다(db):
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)

    df = fetcher.get_daily_price(CODE)

    assert list(df["날짜"]) == sorted(df["날짜"], reverse=True)


def test_선반영_체크에_필요한_행수를_돌려준다(db):
    """_adjust_for_price_reaction 이 iloc[3] 까지 본다."""
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)

    df = fetcher.get_daily_price(CODE)

    assert len(df) >= 4


def test_종가는_숫자다(db):
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)

    df = fetcher.get_daily_price(CODE)

    assert float(df.iloc[0]["종가"]) > 0


def test_없는_종목은_None_이다(db):
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)

    assert fetcher.get_daily_price("000000") is None


def test_preload_후에는_쿼리를_더_하지_않는다(db):
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)
    fetcher.preload([CODE, "000660"])

    before = fetcher.query_count
    fetcher.get_daily_price(CODE)
    fetcher.get_daily_price("000660")

    assert fetcher.query_count == before
