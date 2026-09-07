from datetime import date, datetime, time

from news_scraper.sector_news_aggregator import (
    compute_trade_date, compute_window, is_frozen, next_weekday, prev_weekday,
    split_related_stocks, MARKET_CLOSE, FREEZE_FROM,
)


def test_constants():
    assert MARKET_CLOSE == time(15, 30) and FREEZE_FROM == time(9, 5)


def test_weekday_helpers():
    assert next_weekday(date(2026, 9, 4)) == date(2026, 9, 7)   # 금 → 월
    assert next_weekday(date(2026, 9, 5)) == date(2026, 9, 7)   # 토 → 월
    assert prev_weekday(date(2026, 9, 7)) == date(2026, 9, 4)   # 월 → 금
    assert prev_weekday(date(2026, 9, 8)) == date(2026, 9, 7)   # 화 → 월


def test_trade_date_weekday_before_close_is_today():
    assert compute_trade_date(datetime(2026, 9, 8, 9, 0)) == date(2026, 9, 8)
    assert compute_trade_date(datetime(2026, 9, 8, 15, 29, 59)) == date(2026, 9, 8)


def test_trade_date_after_close_is_next_weekday():
    assert compute_trade_date(datetime(2026, 9, 8, 15, 30)) == date(2026, 9, 9)
    assert compute_trade_date(datetime(2026, 9, 4, 16, 0)) == date(2026, 9, 7)    # 금 저녁 → 월


def test_trade_date_weekend_is_next_monday():
    assert compute_trade_date(datetime(2026, 9, 5, 12, 0)) == date(2026, 9, 7)
    assert compute_trade_date(datetime(2026, 9, 6, 3, 0)) == date(2026, 9, 7)


def test_window_monday_morning_starts_friday_close():
    td, ws, we = compute_window(datetime(2026, 9, 7, 8, 50))
    assert td == date(2026, 9, 7)
    assert ws == datetime(2026, 9, 4, 15, 30) and we == datetime(2026, 9, 7, 8, 50)


def test_window_friday_evening_targets_monday_from_friday_close():
    td, ws, we = compute_window(datetime(2026, 9, 4, 20, 0))
    assert td == date(2026, 9, 7) and ws == datetime(2026, 9, 4, 15, 30)


def test_window_tuesday_starts_monday_close():
    td, ws, _ = compute_window(datetime(2026, 9, 8, 7, 45))
    assert td == date(2026, 9, 8) and ws == datetime(2026, 9, 7, 15, 30)


def test_frozen_window():
    assert not is_frozen(datetime(2026, 9, 8, 9, 4, 59))
    assert is_frozen(datetime(2026, 9, 8, 9, 5))
    assert is_frozen(datetime(2026, 9, 8, 12, 0))
    assert not is_frozen(datetime(2026, 9, 8, 15, 30))
    assert not is_frozen(datetime(2026, 9, 5, 12, 0))   # 주말은 동결 없음


def test_split_related_stocks():
    assert split_related_stocks("005930,000660, 005930 ,12345,ABCDEFG") == ["005930", "000660"]
    assert split_related_stocks("") == [] and split_related_stocks(None) == []
