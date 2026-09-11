"""수익 결합 — 신호에 이후 수익을 붙인다.

returns_1d 는 수정주가가 아니다. 거래소 가격제한폭이 ±30% 이므로 그걸
넘는 값은 정의상 수익이 아니라 기업행위다(액면분할 등).
"""
from datetime import date

import pandas as pd
import pytest

from news_scraper.backtest.returns import CORPORATE_ACTION_LIMIT, attach_returns


def _signals():
    return pd.DataFrame([
        {"trade_date": date(2026, 6, 15), "window_kind": "sector_1530",
         "stock_code": "A", "composite_score": 0.9},
        {"trade_date": date(2026, 6, 15), "window_kind": "sector_1530",
         "stock_code": "B", "composite_score": 0.1},
    ])


def _rets(a_h1, b_h1):
    return pd.DataFrame([
        {"trade_date": date(2026, 6, 15), "stock_code": "A",
         "ret_h0": 0.0, "ret_h1": a_h1, "ret_h5": 0.0},
        {"trade_date": date(2026, 6, 15), "stock_code": "B",
         "ret_h0": 0.0, "ret_h1": b_h1, "ret_h5": 0.0},
    ])


def test_횡단면_평균을_뺀다():
    out = attach_returns(_signals(), _rets(0.04, 0.02))

    got = dict(zip(out["stock_code"], out["excess_h1"]))
    assert got["A"] == pytest.approx(0.01)    # 0.04 - 평균 0.03
    assert got["B"] == pytest.approx(-0.01)


def test_초과수익의_합은_0이다():
    out = attach_returns(_signals(), _rets(0.04, 0.02))

    assert out["excess_h1"].sum() == pytest.approx(0.0)


def test_기업행위_관측은_버린다():
    """±30% 를 넘으면 수익이 아니라 액면분할이다."""
    out = attach_returns(_signals(), _rets(0.55, 0.02))

    assert "A" not in set(out["stock_code"])
    assert "B" in set(out["stock_code"])


def test_제한폭_경계값은_남긴다():
    out = attach_returns(_signals(), _rets(CORPORATE_ACTION_LIMIT, 0.02))

    assert "A" in set(out["stock_code"])


def test_수익이_없는_신호는_빠진다():
    rets = _rets(0.04, 0.02)
    rets = rets[rets["stock_code"] == "A"]

    out = attach_returns(_signals(), rets)

    assert set(out["stock_code"]) == {"A"}


def test_창이_다르면_따로_평균낸다():
    sig = _signals()
    other = sig.copy()
    other["window_kind"] = "prod_calendar"
    other = other[other["stock_code"] == "A"]

    out = attach_returns(pd.concat([sig, other]), _rets(0.04, 0.02))

    prod = out[out["window_kind"] == "prod_calendar"]
    assert prod["excess_h1"].iloc[0] == pytest.approx(0.0)   # 혼자면 초과수익 0


@pytest.mark.db
def test_실DB_조인이_0행을_내지_않는다(db):
    """daily_prices.date 는 TEXT 'YYYY-MM-DD', stock_code 는 character(6) 다.
    형식을 틀리면 조인 결과가 «조용히» 0행이 된다 — 설계 중 실제로 겪었다."""
    from news_scraper.backtest.returns import load_returns

    out = load_returns(db, date(2026, 6, 1), date(2026, 6, 30))

    assert len(out) > 0
    assert out["ret_h0"].notna().sum() > 0
    assert out["ret_h1"].notna().sum() > 0
    assert isinstance(out["trade_date"].iloc[0], date)


@pytest.mark.db
def test_실DB_수익에_기업행위가_남아있지_않다(db):
    """±30% 를 넘는 일간 변동 구간은 load_returns 가 이미 뺐어야 한다."""
    from news_scraper.backtest.returns import load_returns

    out = load_returns(db, date(2026, 6, 1), date(2026, 6, 30))

    assert out["ret_h0"].abs().max() <= CORPORATE_ACTION_LIMIT + 1e-9
