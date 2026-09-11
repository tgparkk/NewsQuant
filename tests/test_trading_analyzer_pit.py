"""TradingAnalyzer 를 과거 시점으로 돌릴 수 있는가.

원장은 어제 만들어져 359행뿐이라 과거 신호를 news 에서 재구성해야 한다.
그러려면 시계와 가격 조회를 주입할 수 있어야 한다.

생산 동작이 바뀌면 안 된다 — 그것을 지키는 게 골든 테스트다.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from news_scraper.trading_analyzer import TradingAnalyzer

pytestmark = pytest.mark.db

GOLDEN = Path(__file__).parent / "fixtures" / "analyze_today_golden.json"


class FakePriceFetcher:
    """호출 사실만 기록한다. 가격은 없다고 답한다."""

    def __init__(self):
        self.calls = []

    def get_daily_price(self, stock_code, pages=1):
        self.calls.append(stock_code)
        return None


def _news(news_id, published_at, code, sentiment, overall):
    return {
        "news_id": news_id, "title": f"t{news_id}", "content": "c",
        "published_at": published_at, "related_stocks": code,
        "sentiment_score": sentiment, "overall_score": overall,
    }


def test_뉴스_목록을_직접_받아_집계한다(db):
    a = TradingAnalyzer(price_fetcher=FakePriceFetcher())
    rows = [
        _news("n1", datetime(2026, 6, 15, 8, 0), "005930", 0.8, 0.9),
        _news("n2", datetime(2026, 6, 15, 8, 30), "005930", 0.6, 0.7),
    ]

    result = a.analyze_stocks(rows, as_of=datetime(2026, 6, 15, 9, 0))

    stats = {s["stock_code"]: s for s in result["stock_stats"]}
    assert stats["005930"]["news_count"] == 2
    assert stats["005930"]["avg_sentiment"] == pytest.approx(0.7)


def test_주입한_가격조회기를_쓴다(db):
    fake = FakePriceFetcher()
    a = TradingAnalyzer(price_fetcher=fake)

    a.analyze_stocks(
        [_news("n1", datetime(2026, 6, 15, 8, 0), "005930", 0.8, 0.9)],
        as_of=datetime(2026, 6, 15, 9, 0),
    )

    assert fake.calls == ["005930"]


def test_볼륨_캐시가_인스턴스마다_따로다(db):
    """클래스 속성이면 첫 거래일 캐시가 169일 내내 재사용된다."""
    a = TradingAnalyzer(price_fetcher=FakePriceFetcher())
    b = TradingAnalyzer(price_fetcher=FakePriceFetcher())

    a._volume_cache["ZZZZZZ"] = 99

    assert "ZZZZZZ" not in b._volume_cache


def test_볼륨_기준선이_as_of_이전_뉴스만_쓴다(db):
    """as_of 이후 뉴스로 기준선을 만들면 미래 참조다."""
    a = TradingAnalyzer(price_fetcher=FakePriceFetcher())

    a._load_volume_cache(as_of=datetime(2026, 3, 2))
    early = dict(a._volume_cache)

    b = TradingAnalyzer(price_fetcher=FakePriceFetcher())
    b._load_volume_cache(as_of=datetime(2026, 9, 1))

    assert early != b._volume_cache


PURE_FIELDS = ("news_count", "avg_sentiment", "avg_overall",
               "positive_count", "negative_count", "neutral_count", "positive_ratio")


def test_골든에_뉴스와_종목이_들어있다():
    """비어 있으면 아래 동치성 테스트가 아무것도 지키지 못한다."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert len(golden["news_rows"]) > 0
    assert len(golden["stock_stats"]) > 0


def test_집계_로직이_리팩터링_전과_같다(db):
    """골든에 담아 둔 «그때 그 뉴스» 를 그대로 먹여 비교한다.

    가격에 의존하는 adjusted_sentiment·composite_score·volume_signal 은 뺀다 —
    리팩터링 전 코드가 실시간 HTTP 주가를 타서 재실행마다 달라질 수 있고,
    가격 조회는 이번에 «의도적으로» 주입 가능하게 바꾸는 부분이다.
    """
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rows = [dict(n) for n in golden["news_rows"]]

    result = TradingAnalyzer(price_fetcher=FakePriceFetcher()).analyze_stocks(rows)

    got = sorted(result["stock_stats"], key=lambda s: s["stock_code"])
    want = golden["stock_stats"]
    assert [g["stock_code"] for g in got] == [w["stock_code"] for w in want]
    for g, w in zip(got, want):
        for field in PURE_FIELDS:
            assert g[field] == pytest.approx(w[field]), f"{g['stock_code']}.{field}"


def test_생산_경로가_오류없이_돌고_같은_키를_돌려준다(db):
    """analyze_today_stocks() 를 인자 없이 부르는 경로가 살아 있는가."""
    result = TradingAnalyzer().analyze_today_stocks()

    assert set(result) >= {"total_news", "stocks_mentioned", "buy_candidates",
                           "sell_candidates", "watch_candidates", "stock_stats"}
