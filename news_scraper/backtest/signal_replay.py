"""과거 거래일의 종목 신호를 point-in-time 으로 다시 만든다.

원장(newsquant_signal_ledger)은 2026-09-11 에 만들어져 359행뿐이다.
그래서 과거 신호는 news_reprocessed 에서 재구성한다.

창이 둘이다(스펙 §1 결정 2). as_of 는 둘 다 D 09:00 으로 고정하고
«시작점만» 바꾼다 — 차이는 D-1 장 마감 후 뉴스를 넣느냐 빼느냐 하나다.
봇이 09:00 에 후보를 읽기 때문에 09:00 이 결정 시각이다.
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

TABLE = "backtest_signal"
WINDOW_KINDS = ("prod_calendar", "sector_1530")

DECISION_TIME = time(9, 0)     # 봇이 후보를 읽는 시각
MARKET_CLOSE = time(15, 30)

_CREATE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    trade_date          DATE NOT NULL,
    window_kind         TEXT NOT NULL,
    as_of               TIMESTAMP NOT NULL,
    stock_code          TEXT NOT NULL,
    news_count          INTEGER,
    avg_sentiment       DOUBLE PRECISION,
    adjusted_sentiment  DOUBLE PRECISION,
    avg_overall         DOUBLE PRECISION,
    volume_signal       DOUBLE PRECISION,
    composite_score     DOUBLE PRECISION,
    code_version        TEXT,
    PRIMARY KEY (trade_date, window_kind, stock_code)
)
"""


def prev_weekday(d: date) -> date:
    out = d - timedelta(days=1)
    while out.weekday() >= 5:
        out -= timedelta(days=1)
    return out


def window_bounds(trade_date: date, kind: str) -> Tuple[datetime, datetime]:
    """(창 시작, as_of). as_of 는 언제나 거래일 09:00."""
    as_of = datetime.combine(trade_date, DECISION_TIME)
    if kind == "prod_calendar":
        return datetime.combine(trade_date, time(0, 0)), as_of
    if kind == "sector_1530":
        return datetime.combine(prev_weekday(trade_date), MARKET_CLOSE), as_of
    raise ValueError(f"알 수 없는 창: {kind!r} — {WINDOW_KINDS} 중 하나여야 한다")


def ensure_table(db) -> None:
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_connection(conn)


def trading_days(db, start: date, end: date) -> List[date]:
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT date FROM daily_prices
                           WHERE date >= %s AND date <= %s ORDER BY date""",
                        (start.isoformat(), end.isoformat()))
            return [datetime.strptime(r[0], "%Y-%m-%d").date() for r in cur.fetchall()]
    finally:
        conn.rollback()
        db._put_connection(conn)


def _news_in_window(db, start: datetime, as_of: datetime) -> List[Dict]:
    """창 (start, as_of] 의 재처리된 뉴스. 미래 참조가 여기서 막힌다."""
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT news_id, title, published_at, related_stocks,
                       sentiment_score, overall_score
                FROM news_reprocessed
                WHERE published_at > %s AND published_at <= %s
                  AND related_stocks <> ''
                ORDER BY published_at, news_id
            """, (start, as_of))
            return [{"news_id": r[0], "title": r[1], "content": "",
                     "published_at": r[2], "related_stocks": r[3],
                     "sentiment_score": r[4], "overall_score": r[5]}
                    for r in cur.fetchall()]
    finally:
        conn.rollback()
        db._put_connection(conn)


def replay_day(db, trade_date: date, kind: str) -> List[Dict]:
    """거래일 하나 × 창 하나 → 종목별 신호 행."""
    from news_scraper.backtest.price_asof import DailyPriceAsOf
    from news_scraper.trading_analyzer import TradingAnalyzer

    start, as_of = window_bounds(trade_date, kind)
    rows = _news_in_window(db, start, as_of)
    if not rows:
        return []

    codes = set()
    for r in rows:
        codes.update(c.strip() for c in (r["related_stocks"] or "").split(",") if c.strip())

    prices = DailyPriceAsOf(db, as_of=as_of)
    prices.preload(sorted(codes))

    analyzer = TradingAnalyzer(price_fetcher=prices)
    result = analyzer.analyze_stocks(rows, as_of=as_of)

    out = []
    for s in result.get("stock_stats", []):
        out.append({
            "trade_date": trade_date, "window_kind": kind, "as_of": as_of,
            "stock_code": s["stock_code"], "news_count": s["news_count"],
            "avg_sentiment": s["avg_sentiment"],
            "adjusted_sentiment": s["adjusted_sentiment"],
            "avg_overall": s["avg_overall"], "volume_signal": s["volume_signal"],
            "composite_score": s["composite_score"],
        })
    return out


def replay_range(db, start: date, end: date, apply: bool = False) -> Dict:
    from news_scraper.backtest.reprocess import code_version

    ensure_table(db)
    version = code_version()
    days = trading_days(db, start, end)
    total = 0

    for d in days:
        for kind in WINDOW_KINDS:
            rows = replay_day(db, d, kind)
            total += len(rows)
            if not (apply and rows):
                continue
            conn = db.get_connection()
            try:
                with conn.cursor() as cur:
                    for r in rows:
                        cur.execute(f"""
                            INSERT INTO {TABLE}
                              (trade_date, window_kind, as_of, stock_code, news_count,
                               avg_sentiment, adjusted_sentiment, avg_overall,
                               volume_signal, composite_score, code_version)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (trade_date, window_kind, stock_code)
                            DO UPDATE SET
                              as_of = EXCLUDED.as_of,
                              news_count = EXCLUDED.news_count,
                              avg_sentiment = EXCLUDED.avg_sentiment,
                              adjusted_sentiment = EXCLUDED.adjusted_sentiment,
                              avg_overall = EXCLUDED.avg_overall,
                              volume_signal = EXCLUDED.volume_signal,
                              composite_score = EXCLUDED.composite_score,
                              code_version = EXCLUDED.code_version
                        """, (r["trade_date"], r["window_kind"], r["as_of"],
                              r["stock_code"], r["news_count"], r["avg_sentiment"],
                              r["adjusted_sentiment"], r["avg_overall"],
                              r["volume_signal"], r["composite_score"], version))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                db._put_connection(conn)
        logger.info(f"[백테스트] {d} 재현 완료 (누적 {total}행)")

    return {"days": len(days), "rows": total, "applied": apply}
