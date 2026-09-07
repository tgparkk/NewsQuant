import math
from datetime import date, datetime, time

from news_scraper.sector_keywords import parse_sector_keywords
from news_scraper.sector_news_aggregator import (
    compute_trade_date, compute_window, is_frozen, next_weekday, prev_weekday,
    split_related_stocks, MARKET_CLOSE, FREEZE_FROM,
    attribute_news, aggregate, SectorHit, ROUTE_STOCK, W_KW_TITLE, W_KW_BODY, W_STOCK,
    MIN_N, K_SCALE, DEFAULT_W_SRC, MAX_CODES_PER_NEWS,
)
from news_scraper.sector_keywords import ROUTE_KW_TITLE, ROUTE_KW_BODY


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


def _kw():
    return parse_sector_keywords({"version": "t", "sectors": {
        "261": {"name": "반도체", "ko": ["반도체"], "en": ["chip"]},
        "641": {"name": "은행", "ko": ["은행"]},
    }})


def _news(**kw):
    base = {"news_id": "n1", "title": "", "content": "", "source": "naver_finance",
            "sentiment_score": 0.5, "related_stocks": ""}
    base.update(kw)
    return base


NOW = datetime(2026, 9, 8, 8, 50)
MAP = {"005930": "261", "000660": "261", "105560": "641"}


def test_attribute_title_kw():
    s = {}
    hits = attribute_news(_news(title="반도체 호황"), _kw(), MAP, stock_route_enabled=True, summary=s)
    assert hits["261"] == SectorHit(ROUTE_KW_TITLE, [ROUTE_KW_TITLE], "반도체", W_KW_TITLE)


def test_attribute_stock_route_only():
    hits = attribute_news(_news(title="실적", related_stocks="105560"), _kw(), MAP, stock_route_enabled=True, summary={})
    assert hits == {"641": SectorHit(ROUTE_STOCK, [ROUTE_STOCK], "105560", W_STOCK)}


def test_attribute_both_routes_take_max_weight_once():
    h = attribute_news(_news(title="반도체", related_stocks="005930"), _kw(), MAP, stock_route_enabled=True, summary={})["261"]
    assert h.w_match == W_KW_TITLE and h.route == ROUTE_KW_TITLE and h.routes == [ROUTE_KW_TITLE, ROUTE_STOCK]
    h2 = attribute_news(_news(content="반도체", related_stocks="005930"), _kw(), MAP, stock_route_enabled=True, summary={})["261"]
    assert h2.w_match == W_STOCK and h2.route == ROUTE_STOCK and h2.routes == [ROUTE_KW_BODY, ROUTE_STOCK]


def test_attribute_stock_route_disabled():
    hits = attribute_news(_news(related_stocks="105560"), _kw(), MAP, stock_route_enabled=False, summary={})
    assert hits == {}


def test_attribute_too_many_codes_skips_stock_route_and_counts():
    s = {}
    many = ",".join(["005930", "000660", "105560", "111111", "222222", "333333"])
    hits = attribute_news(_news(title="[인사] 국토교통부", related_stocks=many), _kw(), MAP, stock_route_enabled=True, summary=s)
    assert hits == {} and s["stock_route_skipped"] == 1


def test_aggregate_formula_and_min_n():
    rows = [
        _news(news_id="a", title="반도체 훈풍", sentiment_score=0.5),           # c = 0.5*1.0*0.9 = 0.45
        _news(news_id="b", content="chip demand", sentiment_score=0.8),        # c = 0.8*0.5*0.9 = 0.36
        _news(news_id="c", related_stocks="000660", sentiment_score=-0.2),     # c = -0.2*0.7*0.9 = -0.126
        _news(news_id="d", related_stocks="005930", sentiment_score=0.0),      # 중립: n_news 에만
        _news(news_id="e", title="은행 실적", sentiment_score=1.0),             # 641: n_dir 1 < MIN_N → 0
    ]
    r = aggregate(rows, _kw(), MAP, {"641": "은행 및 저축기관"}, NOW)
    by = {s["sector_key"]: s for s in r.scores}
    s261 = by["261"]
    assert (s261["n_news"], s261["n_dir"], s261["n_kw"], s261["n_stock"], s261["n_pos"], s261["n_neg"]) == (4, 3, 2, 2, 2, 1)
    raw = 0.45 + 0.36 - 0.126
    assert math.isclose(s261["score_raw"], raw, rel_tol=1e-9)
    assert math.isclose(s261["score_norm"], raw / math.sqrt(3), rel_tol=1e-9)
    assert math.isclose(s261["score_signed"], raw / math.sqrt(3) / K_SCALE, rel_tol=1e-9)
    assert by["641"]["n_dir"] == 1 and by["641"]["score_signed"] == 0.0
    assert by["641"]["sector_name"] == "은행"          # 사전 name 우선
    assert s261["trade_date"] == date(2026, 9, 8) and s261["window_start"] == datetime(2026, 9, 7, 15, 30)
    assert len(r.hits) == 5 and r.summary["n_input"] == 5


def test_aggregate_clips_to_plus_minus_one():
    rows = [_news(news_id=str(i), title="반도체", sentiment_score=1.0, source="krx_disclosure") for i in range(20)]
    r = aggregate(rows, _kw(), {}, {}, NOW)
    assert r.scores[0]["score_signed"] == 1.0
    rows = [_news(news_id=str(i), title="반도체", sentiment_score=-1.0) for i in range(20)]
    assert aggregate(rows, _kw(), {}, {}, NOW).scores[0]["score_signed"] == -1.0


def test_aggregate_unknown_source_uses_default_weight():
    rows = [_news(news_id=str(i), title="반도체", sentiment_score=0.5, source="unknown_src") for i in range(3)]
    s = aggregate(rows, _kw(), {}, {}, NOW).scores[0]
    assert math.isclose(s["score_raw"], 3 * 0.5 * DEFAULT_W_SRC)


def test_aggregate_top_news_sorted_by_abs_c_and_capped():
    rows = [_news(news_id=str(i), title="반도체", sentiment_score=(i - 3) / 3) for i in range(7)]
    top = aggregate(rows, _kw(), {}, {}, NOW).scores[0]["top_news"]
    assert len(top) == 5 and [abs(t["c"]) for t in top] == sorted([abs(t["c"]) for t in top], reverse=True)
    assert set(top[0]) == {"news_id", "title", "c", "route"}


def test_aggregate_name_falls_back_to_sector_names_then_none():
    rows = [_news(news_id="x", related_stocks="105560", sentiment_score=0.3)]
    kw = parse_sector_keywords({"version": "t", "sectors": {"261": {"name": "반도체", "ko": ["반도체"]}}})
    assert aggregate(rows, kw, MAP, {"641": "은행 및 저축기관"}, NOW).scores[0]["sector_name"] == "은행 및 저축기관"
    assert aggregate(rows, kw, MAP, {}, NOW).scores[0]["sector_name"] is None


def test_aggregate_none_sentiment_counts_as_neutral():
    rows = [_news(news_id="x", title="반도체", sentiment_score=None)]
    s = aggregate(rows, _kw(), {}, {}, NOW).scores[0]
    assert s["n_news"] == 1 and s["n_dir"] == 0 and s["score_raw"] == 0.0


def test_aggregate_is_deterministic():
    rows = [_news(news_id=str(i), title="반도체", sentiment_score=0.3 * (i % 3 - 1)) for i in range(9)]
    a = aggregate(rows, _kw(), {}, {}, NOW)
    b = aggregate(rows, _kw(), {}, {}, NOW)
    assert a.scores == b.scores and a.hits == b.hits
