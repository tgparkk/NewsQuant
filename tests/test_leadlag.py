"""섹터 선행-후행 — 점수 생성 로직을 손 계산 픽스처로 고정한다.

설계: docs/superpowers/specs/2026-10-07-sector-leadlag-design.md §4, §10.
실 DB 는 쓰지 않는다. load_panel/load_groups 의 SQL 은 실행기에서 실측한다.
"""
from datetime import date

import pandas as pd
import pytest

from news_scraper.backtest.leadlag import PANEL_COLUMNS, clean_panel, next_trading_day_map


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


def test_다음_거래일은_주말과_연휴를_건너뛴다():
    """금 06-12 → 월 06-15, 화 06-16 → 목 06-18(수 휴장). 달력 +1 이 아니라
    «패널에 있는 다음 날짜» 다."""
    days = [date(2026, 6, 16), date(2026, 6, 12), date(2026, 6, 18), date(2026, 6, 15),
            date(2026, 6, 15)]  # 순서 무관·중복 허용

    m = next_trading_day_map(days)

    assert m[date(2026, 6, 12)] == date(2026, 6, 15)
    assert m[date(2026, 6, 15)] == date(2026, 6, 16)
    assert m[date(2026, 6, 16)] == date(2026, 6, 18)


def test_마지막_날짜는_다음_거래일이_없어_맵에_없다():
    m = next_trading_day_map([date(2026, 6, 15), date(2026, 6, 16)])

    assert date(2026, 6, 16) not in m
    assert len(m) == 1


def test_날짜가_하나거나_없으면_빈_맵이다():
    assert next_trading_day_map([date(2026, 6, 15)]) == {}
    assert next_trading_day_map([]) == {}


from news_scraper.backtest.leadlag import MIN_MEMBERS, SCORE_COLUMNS, build_scores

D1, D2 = date(2026, 6, 15), date(2026, 6, 16)


def _panel(day, rets):
    """{"A": 0.10, ...} → 패널 프레임(한 날짜)."""
    return pd.DataFrame([{"date": day, "stock_code": c, "ret": r} for c, r in rets.items()])


def _groups(mapping):
    """{"g1": ["A","B"], ...} → groups 프레임."""
    return pd.DataFrame([{"stock_code": c, "group_id": g}
                         for g, codes in mapping.items() for c in codes])


# 손 계산 픽스처. g1 = {A,B,C,D,E}(5), g2 = {A,F,G,H,I,J}(6), K 는 무소속.
RETS_D1 = {"A": 0.10, "B": 0.02, "C": 0.00, "D": -0.02, "E": 0.04,
           "F": 0.01, "G": 0.03, "H": -0.01, "I": 0.05, "J": 0.02, "K": -0.03}
GROUPS = {"g1": ["A", "B", "C", "D", "E"], "g2": ["A", "F", "G", "H", "I", "J"]}


def _two_day_panel():
    """D2 는 D1 과 같은 수익으로 한 번 더 — trade_date 가 생기려면 다음 거래일이 필요하다."""
    return pd.concat([_panel(D1, RETS_D1), _panel(D2, RETS_D1)], ignore_index=True)


def _d1_scores():
    s = build_scores(_two_day_panel(), _groups(GROUPS), kind="theme")
    return s[s["score_date"] == D1].set_index("stock_code")


def test_자기_제외_평균이_멤버_루프와_같다():
    """구현은 (sum − r_i)/(n − 1) 로 하지만, 정의는 «i 를 뺀 멤버 평균» 이다.
    B 는 g1 에만 속하므로 score_B = mean(g1 without B) − m."""
    m = sum(RETS_D1.values()) / len(RETS_D1)
    others = [RETS_D1[c] for c in GROUPS["g1"] if c != "B"]
    expected = sum(others) / len(others) - m

    assert _d1_scores().loc["B", "score"] == pytest.approx(expected)


def test_시장_평균은_무소속_종목까지_포함한_전체_평균이다():
    """m(D) 에 K(무소속, −0.03) 가 들어가야 한다(스펙 §4.1). K 를 빼고 계산한 값과
    달라야 한다."""
    m_all = sum(RETS_D1.values()) / len(RETS_D1)
    m_wo_k = sum(v for c, v in RETS_D1.items() if c != "K") / (len(RETS_D1) - 1)
    others = [RETS_D1[c] for c in GROUPS["g1"] if c != "B"]
    loo = sum(others) / len(others)

    got = _d1_scores().loc["B", "score"]
    assert got == pytest.approx(loo - m_all)
    assert got != pytest.approx(loo - m_wo_k)


def test_다중_소속_종목의_점수는_그룹별_잔차의_평균이다():
    """A 는 g1·g2 둘 다. score_A = mean(resid_A,g1, resid_A,g2)."""
    m = sum(RETS_D1.values()) / len(RETS_D1)
    g1 = [RETS_D1[c] for c in GROUPS["g1"] if c != "A"]
    g2 = [RETS_D1[c] for c in GROUPS["g2"] if c != "A"]
    r1 = sum(g1) / len(g1) - m
    r2 = sum(g2) / len(g2) - m

    assert _d1_scores().loc["A", "score"] == pytest.approx((r1 + r2) / 2)


def test_그룹_크기가_MIN_MEMBERS_미만이면_그날_신호가_없다():
    """g3 = {L,M,N,O}(4) → L~O 는 유효 그룹이 없으니 S 에 없다. g1 종목은 그대로."""
    rets = dict(RETS_D1, L=0.01, M=0.02, N=0.03, O=0.04)
    panel = pd.concat([_panel(D1, rets), _panel(D2, rets)], ignore_index=True)
    groups = _groups(dict(GROUPS, g3=["L", "M", "N", "O"]))

    s = build_scores(panel, groups, kind="theme")
    codes = set(s[s["score_date"] == D1]["stock_code"])

    assert MIN_MEMBERS == 5
    assert {"L", "M", "N", "O"}.isdisjoint(codes)
    assert {"A", "B", "F"} <= codes


def test_패널에_없는_멤버는_그룹_크기에_세지_않는다():
    """g1 에 P 를 더하지만 P 는 패널에 없다(상장폐지 등). n_g 는 여전히 5 이고
    B 의 점수는 변하지 않는다. 반대로 g3 = {L,M,N,O,P} 는 패널 기준 4 라 신호 없음."""
    rets = dict(RETS_D1, L=0.01, M=0.02, N=0.03, O=0.04)
    panel = pd.concat([_panel(D1, rets), _panel(D2, rets)], ignore_index=True)
    groups = _groups({"g1": GROUPS["g1"] + ["P"], "g2": GROUPS["g2"],
                      "g3": ["L", "M", "N", "O", "P"]})

    s = build_scores(panel, groups, kind="theme")
    d1 = s[s["score_date"] == D1].set_index("stock_code")

    m = sum(rets.values()) / len(rets)
    others = [rets[c] for c in GROUPS["g1"] if c != "B"]
    assert d1.loc["B", "score"] == pytest.approx(sum(others) / len(others) - m)
    assert "L" not in d1.index


def test_same_excess는_그날_자기_수익에서_시장_평균을_뺀_값이다():
    m = sum(RETS_D1.values()) / len(RETS_D1)

    assert _d1_scores().loc["A", "same_excess"] == pytest.approx(0.10 - m)


def test_window_kind와_컬럼_순서():
    s = build_scores(_two_day_panel(), _groups(GROUPS), kind="wics")

    assert list(s.columns) == list(SCORE_COLUMNS)
    assert set(s["window_kind"]) == {"wics"}


def test_입력이_비면_빈_프레임을_같은_컬럼으로_돌려준다():
    empty_panel = pd.DataFrame(columns=["date", "stock_code", "ret"])
    empty_groups = pd.DataFrame(columns=["stock_code", "group_id"])

    a = build_scores(empty_panel, _groups(GROUPS), kind="theme")
    b = build_scores(_two_day_panel(), empty_groups, kind="theme")

    assert a.empty and list(a.columns) == list(SCORE_COLUMNS)
    assert b.empty and list(b.columns) == list(SCORE_COLUMNS)
