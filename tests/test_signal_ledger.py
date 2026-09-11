"""신호 원장(newsquant_signal_ledger) 테스트.

적재/조회는 실 DB(kis_template) 왕복 — DB 없으면 conftest.db 픽스처가 skip 한다.
trading_analyzer 쪽 검증은 뉴스 조회를 가짜로 갈아끼워 DB/네트워크를 타지 않는다.
"""
from datetime import date, datetime

import pytest

from news_scraper.trading_analyzer import TradingAnalyzer

pytestmark = pytest.mark.db

SD = date(1999, 1, 4)                    # 실데이터와 겹치지 않는 센티널 영업일
AS_OF = datetime(1999, 1, 4, 15, 40)     # 「결정 시각」 스냅샷
AS_OF_2 = datetime(1999, 1, 4, 9, 5)     # 같은 날 다른 스냅샷
CODE = 'T99999'                          # 센티널 종목


@pytest.fixture
def clean(db):
    yield
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM newsquant_signal_ledger WHERE signal_date = %s", (SD,))
        conn.commit()
    finally:
        db._put_connection(conn)


def _row(as_of=AS_OF, stock_code=CODE, side='buy', evidence=('n1', 'n2', 'n3')):
    return {
        'as_of': as_of,
        'signal_date': SD,
        'stock_code': stock_code,
        'side': side,
        'news_count': 12,
        'avg_sentiment': 0.42,
        'avg_overall': 0.61,
        'adjusted_sentiment': 0.126,
        'volume_signal': -0.2,
        'composite_score': 0.3145,
        'positive_count': 11,
        'negative_count': 1,
        'neutral_count': 0,
        'positive_ratio': 11 / 12,
        'evidence_news_ids': list(evidence),
    }


# ── 적재 왕복 ────────────────────────────────────────────────

def test_table_exists(db):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('newsquant_signal_ledger')")
            assert cur.fetchone()[0] is not None
    finally:
        db._put_connection(conn)


def test_init_is_idempotent(db):
    db.init_signal_ledger_table()
    db.init_signal_ledger_table()


def test_insert_then_read_roundtrip(db, clean):
    assert db.insert_signal_ledger([_row()]) == 1

    rows = db.get_signal_ledger(signal_date=SD)
    assert len(rows) == 1
    r = rows[0]
    assert r['as_of'] == AS_OF and r['signal_date'] == SD
    assert r['stock_code'] == CODE and r['side'] == 'buy'
    assert r['news_count'] == 12
    assert r['avg_sentiment'] == pytest.approx(0.42)
    assert r['avg_overall'] == pytest.approx(0.61)
    assert r['adjusted_sentiment'] == pytest.approx(0.126)
    assert r['volume_signal'] == pytest.approx(-0.2)
    assert r['composite_score'] == pytest.approx(0.3145)
    assert (r['positive_count'], r['negative_count'], r['neutral_count']) == (11, 1, 0)
    assert r['positive_ratio'] == pytest.approx(11 / 12)
    # jsonb 는 파이썬 리스트로 그대로 돌아온다
    assert r['evidence_news_ids'] == ['n1', 'n2', 'n3']
    assert isinstance(r['created_at'], datetime)


def test_empty_batch_inserts_nothing(db):
    assert db.insert_signal_ledger([]) == 0


# ── append-only / 멱등성 ─────────────────────────────────────

def test_same_as_of_and_code_is_ignored_on_reinsert(db, clean):
    assert db.insert_signal_ledger([_row()]) == 1
    # 같은 (as_of, stock_code) 재적재 → 두 번째는 무시된다(적재 0건, 행 수 그대로)
    assert db.insert_signal_ledger([_row(side='sell', evidence=('x9',))]) == 0

    rows = db.get_signal_ledger(signal_date=SD)
    assert len(rows) == 1
    # UPDATE 경로가 없으므로 첫 값이 그대로 남아 있다
    assert rows[0]['side'] == 'buy' and rows[0]['evidence_news_ids'] == ['n1', 'n2', 'n3']


def test_duplicate_inside_one_batch_counts_once(db, clean):
    inserted = db.insert_signal_ledger([_row(), _row(side='sell')])
    assert inserted == 1
    assert len(db.get_signal_ledger(signal_date=SD)) == 1


def test_different_as_of_accumulates(db, clean):
    assert db.insert_signal_ledger([_row(as_of=AS_OF_2, side=None)]) == 1
    assert db.insert_signal_ledger([_row(as_of=AS_OF, side='buy')]) == 1

    rows = db.get_signal_ledger(signal_date=SD, stock_code=CODE)
    assert len(rows) == 2
    # as_of 오름차순: 09:05 → 15:40
    assert [r['as_of'] for r in rows] == [AS_OF_2, AS_OF]
    assert [r['side'] for r in rows] == [None, 'buy']


def test_null_side_row_is_stored(db, clean):
    """후보가 아닌 종목(side NULL)도 적재된다 — 임계값 재평가에 필요하다."""
    assert db.insert_signal_ledger([
        _row(stock_code='T99998', side=None, evidence=()),
        _row(stock_code=CODE, side='watch'),
    ]) == 2

    rows = {r['stock_code']: r for r in db.get_signal_ledger(signal_date=SD)}
    assert rows['T99998']['side'] is None
    assert rows['T99998']['evidence_news_ids'] == []
    assert rows[CODE]['side'] == 'watch'


# ── trading_analyzer 가 side / evidence_news_ids 를 채우는지 ──

def _news(news_id, code, sentiment, overall, title='센티널 뉴스'):
    return {
        'news_id': news_id,
        'title': title,
        'content': '',
        'published_at': '1999-01-04T09:00:00',
        'source': 'test',
        'related_stocks': code,
        'sentiment_score': sentiment,
        'overall_score': overall,
    }


class FakeNewsDb:
    """get_news_by_date_range 만 흉내내는 대역. 조회 범위는 무시한다."""

    def __init__(self, news_list):
        self.news_list = news_list
        self.calls = []

    def get_news_by_date_range(self, start_date, end_date, source=None):
        self.calls.append((start_date, end_date, source))
        return list(self.news_list)


def make_analyzer(news_list):
    """DB/네트워크를 타지 않는 분석기.

    주가 선반영 조정과 볼륨 시그널은 각각 HTTP/DB 를 타므로 무력화한다
    (여기서 보려는 것은 evidence_news_ids 와 side 뿐이다).
    """
    analyzer = TradingAnalyzer.__new__(TradingAnalyzer)
    analyzer.db = FakeNewsDb(news_list)
    analyzer.price_fetcher = None
    analyzer._adjust_for_price_reaction = lambda sentiment, stock_code, days=3: sentiment
    analyzer._volume_signal = lambda stock_code, today_count: 0.0
    return analyzer


def _sample_news():
    news = []
    # 매수 후보: 긍정 10건 (sent 0.5 > 0.30, overall 0.6 > 0.3, ratio 1.0)
    news += [_news(f'buy{i}', '000001', 0.5, 0.6) for i in range(10)]
    # 매도 후보: 부정 7건 (sent -0.5 < -0.25, overall 0.1 < 0.25, neg_ratio 1.0)
    news += [_news(f'sell{i}', '000002', -0.5, 0.1) for i in range(7)]
    # 관찰 후보: 5건, 평균 0.0, 긍/부정 공존
    for i, sent in enumerate((0.05, -0.05, 0.05, -0.05, 0.0)):
        news.append(_news(f'watch{i}', '000003', sent, 0.4))
    # 후보 아님: 1건
    news.append(_news('none0', '000004', 0.5, 0.6))
    return news


def test_stock_stats_carry_evidence_news_ids():
    analyzer = make_analyzer(_sample_news())
    result = analyzer.analyze_today_stocks()

    stats = {s['stock_code']: s for s in result['stock_stats']}
    assert set(stats) == {'000001', '000002', '000003', '000004'}
    assert stats['000001']['evidence_news_ids'] == [f'buy{i}' for i in range(10)]
    assert stats['000002']['evidence_news_ids'] == [f'sell{i}' for i in range(7)]
    assert stats['000004']['evidence_news_ids'] == ['none0']
    # 근거 개수는 집계 뉴스 수와 일치한다
    for s in result['stock_stats']:
        assert len(s['evidence_news_ids']) == s['news_count']


def test_side_matches_candidate_membership():
    analyzer = make_analyzer(_sample_news())
    result = analyzer.analyze_today_stocks()

    stats = {s['stock_code']: s for s in result['stock_stats']}
    assert [s['stock_code'] for s in result['buy_candidates']] == ['000001']
    assert [s['stock_code'] for s in result['sell_candidates']] == ['000002']
    assert [s['stock_code'] for s in result['watch_candidates']] == ['000003']

    assert stats['000001']['side'] == 'buy'
    assert stats['000002']['side'] == 'sell'
    assert stats['000003']['side'] == 'watch'
    assert stats['000004']['side'] is None   # 후보 아님

    # 후보 리스트와 stock_stats 는 같은 dict 를 가리킨다 — side 가 양쪽에서 일치한다
    for side, candidates in (('buy', result['buy_candidates']),
                             ('sell', result['sell_candidates']),
                             ('watch', result['watch_candidates'])):
        for c in candidates:
            assert c['side'] == side


def test_no_news_returns_empty_stats():
    result = make_analyzer([]).analyze_today_stocks()
    assert result['stock_stats'] == [] and result['total_news'] == 0


# ── 스케줄러 잡: stock_stats → 원장 행 변환 ──────────────────

def test_scheduler_row_conversion_keeps_side_and_evidence():
    from news_scraper.scheduler import NewsScheduler

    stat = {
        'stock_code': '000001', 'side': 'buy', 'evidence_news_ids': ['a', 'b'],
        'news_count': 2, 'avg_sentiment': 0.5, 'avg_overall': 0.6,
        'adjusted_sentiment': 0.5, 'volume_signal': 0.0, 'composite_score': 0.415,
        'positive_count': 2, 'negative_count': 0, 'neutral_count': 0, 'positive_ratio': 1.0,
    }
    row = NewsScheduler._to_ledger_row(stat, AS_OF, SD)
    assert row['as_of'] == AS_OF and row['signal_date'] == SD
    assert row['stock_code'] == '000001' and row['side'] == 'buy'
    assert row['evidence_news_ids'] == ['a', 'b']
    assert row['composite_score'] == pytest.approx(0.415)


def test_scheduler_snapshot_times():
    from news_scraper.scheduler import NewsScheduler

    assert NewsScheduler.SIGNAL_LEDGER_TIMES == ((9, 5), (10, 0), (14, 0), (15, 20), (15, 40))
