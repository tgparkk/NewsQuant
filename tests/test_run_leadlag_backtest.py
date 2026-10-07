# tests/test_run_leadlag_backtest.py
"""run_leadlag_backtest 의 계산 헬퍼 — Holm 보정과 구간 파싱.

출력 조립(표 문자열)은 테스트하지 않는다(run_news_backtest 와 같은 원칙).
"""
from datetime import date

import pytest

from scripts.run_leadlag_backtest import holm_adjust, parse_period


def test_holm_보정은_작은_p부터_역순_배수를_곱하고_단조성을_지킨다():
    """m=3: 정렬 .01(a) .03(c) .04(b) → .01×3=.03, .03×2=.06, .04×1=.04 →
    단조성(앞보다 작아질 수 없음)으로 b 는 .06."""
    adj = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03})

    assert adj["a"] == pytest.approx(0.03)
    assert adj["c"] == pytest.approx(0.06)
    assert adj["b"] == pytest.approx(0.06)


def test_holm_보정은_1을_넘지_않는다():
    adj = holm_adjust({"a": 0.5, "b": 0.6})

    assert adj["a"] == pytest.approx(1.0)
    assert adj["b"] == pytest.approx(1.0)


def test_holm_보정은_NaN을_대상에서_빼고_그대로_돌려준다():
    import math
    adj = holm_adjust({"a": 0.01, "b": float("nan")})

    assert adj["a"] == pytest.approx(0.01)   # m=1
    assert math.isnan(adj["b"])


def test_빈_입력은_빈_출력():
    assert holm_adjust({}) == {}


def test_parse_period():
    assert parse_period("main=2024-01-02:2026-10-07") == (
        "main", date(2024, 1, 2), date(2026, 10, 7))


def test_parse_period는_형식이_틀리면_거부한다():
    with pytest.raises(ValueError):
        parse_period("2024-01-02:2026-10-07")
    with pytest.raises(ValueError):
        parse_period("main=2026-10-07:2024-01-02")  # start > end
