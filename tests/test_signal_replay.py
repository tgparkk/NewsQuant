"""신호 재현 — 과거 거래일의 신호를 point-in-time 으로 다시 만든다.

미래 참조가 이 파일의 주제다. 창 경계를 한 칸 잘못 잡으면 백테스트는
조용히 훌륭한 성과를 낸다.
"""
from datetime import date, datetime

import pytest

from news_scraper.backtest.signal_replay import WINDOW_KINDS, window_bounds

pytestmark = pytest.mark.db

D = date(2026, 6, 15)      # 월요일


def test_as_of_는_언제나_거래일_09시다():
    for kind in WINDOW_KINDS:
        _, as_of = window_bounds(D, kind)

        assert as_of == datetime(2026, 6, 15, 9, 0)


def test_생산_창은_그날_자정부터다():
    start, _ = window_bounds(D, "prod_calendar")

    assert start == datetime(2026, 6, 15, 0, 0)


def test_섹터_창은_직전_평일_1530_부터다():
    start, _ = window_bounds(D, "sector_1530")

    assert start == datetime(2026, 6, 12, 15, 30)   # 금요일


def test_두_창의_차이는_시작점_하나뿐이다():
    prod_start, prod_as_of = window_bounds(D, "prod_calendar")
    sect_start, sect_as_of = window_bounds(D, "sector_1530")

    assert prod_as_of == sect_as_of
    assert sect_start < prod_start


def test_알_수_없는_창은_거부한다():
    with pytest.raises(ValueError):
        window_bounds(D, "made_up")


def test_재현된_신호에_as_of_이후_뉴스가_섞이지_않는다(db):
    """news_reprocessed 를 직접 조회해 창 밖 뉴스가 없음을 확인한다."""
    from news_scraper.backtest.signal_replay import _news_in_window

    start, as_of = window_bounds(D, "sector_1530")
    rows = _news_in_window(db, start, as_of)

    assert all(start < r["published_at"] <= as_of for r in rows)
