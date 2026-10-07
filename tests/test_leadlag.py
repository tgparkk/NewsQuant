"""섹터 선행-후행 — 점수 생성 로직을 손 계산 픽스처로 고정한다.

설계: docs/superpowers/specs/2026-10-07-sector-leadlag-design.md §4, §10.
실 DB 는 쓰지 않는다. load_panel/load_groups 의 SQL 은 실행기에서 실측한다.
"""
from datetime import date

import pandas as pd
import pytest

from news_scraper.backtest.leadlag import PANEL_COLUMNS, clean_panel


def _raw(rows):
    """(stock_code, date, open, close, returns_1d) 튜플 → daily_prices 모양 프레임."""
    return pd.DataFrame(rows, columns=["stock_code", "date", "open", "close", "returns_1d"])


def test_clean_panel은_문자열_날짜를_date_객체로_바꾼다():
    """daily_prices.date 는 TEXT 다. date 객체로 바꾸지 않으면 load_returns 의
    trade_date(date 객체)와 병합이 조용히 0 행이 된다."""
    out = clean_panel(_raw([("005930", "2026-06-15", 100, 101, 0.01)]))

    assert list(out.columns) == list(PANEL_COLUMNS)
    assert out.loc[0, "date"] == date(2026, 6, 15)
    assert type(out.loc[0, "date"]) is date
    assert out.loc[0, "ret"] == pytest.approx(0.01)


def test_clean_panel은_기업행위_행을_뺀다():
    """±30% 초과, NULL, open/close 0 은 패널에서 빠진다(스펙 §4.1).
    그룹 합·개수 둘 다에서 빠지는 것은 build_scores 가 이 패널만 받으므로 자동이다."""
    out = clean_panel(_raw([
        ("A", "2026-06-15", 100, 135, 0.35),    # +35% → 기업행위
        ("B", "2026-06-15", 100, 69, -0.31),    # −31% → 기업행위
        ("C", "2026-06-15", 100, 101, None),    # NULL → 전일 종가 없음
        ("D", "2026-06-15", 0, 101, 0.01),      # open 0
        ("E", "2026-06-15", 100, 0, 0.01),      # close 0
        ("F", "2026-06-15", 100, 130, 0.30),    # 정확히 30% 는 남는다
        ("G", "2026-06-15", 100, 102, 0.02),
    ]))

    assert sorted(out["stock_code"]) == ["F", "G"]


def test_clean_panel은_코드를_trim_하고_중복_행을_하나만_남긴다():
    """trim 으로 코드가 합쳐져 같은 (date, stock_code) 가 두 번 생기면 그룹 합이
    두 배가 된다. 첫 행만 남긴다."""
    out = clean_panel(_raw([
        ("005930 ", "2026-06-15", 100, 101, 0.01),
        ("005930", "2026-06-15", 100, 101, 0.01),
        ("000660", "2026-06-15", 100, 103, 0.03),
    ]))

    assert len(out) == 2
    assert list(out["stock_code"]) == ["000660", "005930"]  # (date, stock_code) 정렬
