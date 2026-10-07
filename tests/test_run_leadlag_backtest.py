# tests/test_run_leadlag_backtest.py
"""run_leadlag_backtest 의 계산 헬퍼 — Holm 보정과 구간 파싱.

출력 조립(표 문자열)은 테스트하지 않는다(run_news_backtest 와 같은 원칙).
"""
from datetime import date

import pytest

from scripts.run_leadlag_backtest import _verdict, holm_adjust, parse_period


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


def _primary(p_hac, mean_ic, same_ic, p_hac_r=0.5):
    return {"period": "main", "start": date(2024, 1, 2), "end": date(2026, 10, 7),
            "summary": {"mean_ic": mean_ic}, "p_hac": p_hac, "t_hac": 2.5, "lag": 2,
            "p_hac_r": p_hac_r, "t_hac_r": 1.5, "lag_r": 4, "same_ic": same_ic}


def test_verdict_는_통과이고_강건도_통과면_일치로_적는다():
    out = _verdict(_primary(0.01, 0.01, 0.3, p_hac_r=0.02))

    assert "통과" in out and "선행-후행 있음" in out
    assert "일치" in out and "불일치" not in out


def test_verdict_는_통과인데_강건_p가_크면_불일치_한계적을_적는다():
    out = _verdict(_primary(0.01, 0.01, 0.3, p_hac_r=0.20))

    assert "통과" in out and "불일치(한계적)" in out


def test_verdict_는_p가_크면_실패_동조화뿐이다():
    out = _verdict(_primary(0.40, 0.001, 0.3))

    assert "실패" in out and "동조화뿐" in out


def test_verdict_는_음의_평균IC가_유의하면_익일_되돌림이다():
    assert "익일 되돌림" in _verdict(_primary(0.01, -0.01, 0.3))


def test_verdict_는_당일_IC가_작으면_분류가_그룹을_못_묶는다():
    for p in (0.01, 0.40):
        assert "분류가 그룹을 못 묶는다" in _verdict(_primary(p, 0.01, 0.01))


def test_verdict_는_당일_IC가_NaN이면_측정불가로_적는다():
    assert "당일 IC 측정불가" in _verdict(_primary(0.01, 0.01, float("nan")))
