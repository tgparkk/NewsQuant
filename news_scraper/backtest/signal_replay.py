"""과거 거래일의 종목 신호를 point-in-time 으로 다시 만든다.

원장(newsquant_signal_ledger)은 2026-09-11 에 만들어져 359행뿐이다.
그래서 과거 신호는 news_reprocessed 에서 재구성한다.

창이 둘이다(스펙 §1 결정 2). as_of 는 둘 다 D 09:00 으로 고정하고
«시작점만» 바꾼다 — 차이는 D-1 장 마감 후 뉴스를 넣느냐 빼느냐 하나다.
봇이 09:00 에 후보를 읽기 때문에 09:00 이 결정 시각이다.
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TABLE = "backtest_signal"
WINDOW_KINDS = ("prod_calendar", "sector_1530")

DECISION_TIME = time(9, 0)     # 봇이 후보를 읽는 시각
MARKET_CLOSE = time(15, 30)

# daily_prices 는 거래소 캘린더가 아니다 — 주말에도 잡음성 1~2행이 섞일 수
# 있다(실측: 2026-01-11 일요일, 1행). 정상 거래일은 종목 수백~수천 개가
# 한꺼번에 찍히므로 이 아래는 거래일로 보지 않는다.
MIN_ROWS_PER_DAY = 100

# «진짜» 직전 거래일을 찾을 때 얼마나 과거까지 거슬러 올라가는지. 설·추석처럼
# 공휴일이 주말과 겹쳐 며칠씩 이어지는 경우를 덮을 여유를 둔다.
CALENDAR_LOOKBACK_DAYS = 21

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


def window_bounds(trade_date: date, kind: str,
                   prev_session: Optional[date] = None) -> Tuple[datetime, datetime]:
    """(창 시작, as_of). as_of 는 언제나 거래일 09:00.

    prev_session: sector_1530 창의 시작에 쓸 «실제 이전 거래일». 공휴일이
    평일에 끼면(예: 대체공휴일) prev_weekday() 의 달력 계산이 틀린다 —
    직전 거래일이 아니라 그 전전 거래일이어야 하는데 하루를 더 들고 간다.
    생략하면 기존처럼 prev_weekday() 로 근사한다 — 순수 경계 테스트와
    이 함수를 직접 부르는 다른 코드가 그대로 동작하게 하기 위해서다.
    실제 재현(replay_day/replay_range)은 trading_days() 로 구한 진짜
    이전 거래일을 넘긴다.
    """
    as_of = datetime.combine(trade_date, DECISION_TIME)
    if kind == "prod_calendar":
        return datetime.combine(trade_date, time(0, 0)), as_of
    if kind == "sector_1530":
        session = prev_session if prev_session is not None else prev_weekday(trade_date)
        return datetime.combine(session, MARKET_CLOSE), as_of
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
    """daily_prices 에서 «실제 거래일» 만 골라낸다.

    daily_prices 는 거래소 캘린더가 아니다. 주말(요일) 과 잡음성 소수
    행(하루 행 수 < MIN_ROWS_PER_DAY) 을 둘 다 걸러낸다 — 둘 중 하나만
    쓰면 «주말인데 행이 많은» 경우나 «평일인데 잡음뿐인» 경우를 놓친다.

    daily_prices 는 이 저장소가 아니라 다른 저장소(kis-trading-template)가
    소유한다(I2) — 지금은 date 컬럼이 TEXT 'YYYY-MM-DD' 지만, 그쪽이 언젠가
    DATE 로 마이그레이션하면 psycopg2 가 datetime.date 를 그대로 돌려준다.
    그 값을 strptime(str, ...) 에 넣으면 TypeError 가 나는데, 예전 코드는
    그것도 «형식이 이상한 값» 으로 잡아 건너뛰었다 — 그러면 모든 날이
    조용히 스킵되어 이 함수가 빈 리스트를 돌려주고, 백테스트 전체가
    아무 경고 없이 결과 0행을 낸다. 그래서 값이 이미 date(datetime 포함)면
    그대로 쓰고, strptime·TypeError 캐치는 «진짜 문자열» 경로에만 남긴다 —
    정말로 깨진 텍스트만 여기서 걸러진다.
    """
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT date, count(*) FROM daily_prices
                           WHERE date >= %s AND date <= %s
                           GROUP BY date ORDER BY date""",
                        (start.isoformat(), end.isoformat()))
            out = []
            for date_val, cnt in cur.fetchall():
                if isinstance(date_val, date):
                    d = date_val
                else:
                    try:
                        d = datetime.strptime(date_val, "%Y-%m-%d").date()
                    except ValueError as e:
                        # 172일치를 도는 배치가 행 하나 때문에 죽으면 안 된다 — 건너뛴다.
                        logger.warning(f"[백테스트] daily_prices.date 형식이 이상해 건너뜀: {date_val!r} ({e})")
                        continue
                if d.weekday() >= 5:
                    continue
                if cnt < MIN_ROWS_PER_DAY:
                    logger.warning(f"[백테스트] {d} 는 거래일로 보지 않음 — daily_prices 행 {cnt}개뿐")
                    continue
                out.append(d)
            return out
    finally:
        conn.rollback()
        db._put_connection(conn)


def _news_in_window(db, start: datetime, as_of: datetime) -> List[Dict]:
    """창 (start, as_of] 의 재처리된 뉴스. 미래 참조가 여기서 막힌다.

    as_of 경계는 <= (포함) 을 쓴다. TradingAnalyzer._load_volume_cache 의
    볼륨 기준선도 같은 <= 로 맞춰 뒀다 — 그러지 않으면 정각에 찍힌 기사가
    분자(오늘 카운트)에는 잡히고 분모(기준선)에서는 빠진다.
    """
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


def replay_day(db, trade_date: date, kind: str,
                prev_session: Optional[date] = None) -> List[Dict]:
    """거래일 하나 × 창 하나 → 종목별 신호 행.

    prev_session: sector_1530 창의 실제 이전 거래일(공휴일 보정). replay_range 가
    trading_days() 로 구해 넘긴다 — 생략하면 window_bounds() 가 prev_weekday() 로
    근사한다.
    """
    from news_scraper.backtest.price_asof import DailyPriceAsOf
    from news_scraper.trading_analyzer import TradingAnalyzer

    start, as_of = window_bounds(trade_date, kind, prev_session=prev_session)
    rows = _news_in_window(db, start, as_of)
    if not rows:
        return []

    codes = set()
    for r in rows:
        codes.update(c.strip() for c in (r["related_stocks"] or "").split(",") if c.strip())

    prices = DailyPriceAsOf(db, as_of=as_of)
    prices.preload(sorted(codes))

    # 볼륨 기준선(분모)도 news_reprocessed(분자와 같은 재추출기)에서 읽는다 —
    # 안 그러면 분자·분모가 다른 코드의 산출물이 되어 volume_signal 이 어긋난다.
    analyzer = TradingAnalyzer(price_fetcher=prices, volume_table="news_reprocessed")
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
    # start 이전으로 여유 있게 캘린더를 읽어 둔다 — range 첫 거래일도 «진짜»
    # 이전 거래일(공휴일 보정)을 찾을 수 있어야 한다.
    calendar = trading_days(db, start - timedelta(days=CALENDAR_LOOKBACK_DAYS), end)
    offset = sum(1 for d in calendar if d < start)
    days = calendar[offset:]
    total = 0

    for i, d in enumerate(days):
        idx = offset + i
        prev_session = calendar[idx - 1] if idx > 0 else None
        for kind in WINDOW_KINDS:
            rows = replay_day(db, d, kind, prev_session=prev_session)
            total += len(rows)
            if not apply:
                continue
            conn = db.get_connection()
            try:
                with conn.cursor() as cur:
                    # 이번 재실행에서 사라진 종목의 이전 행이 남지 않도록, 같은
                    # 트랜잭션에서 그날·그 창을 먼저 비우고 다시 쓴다. news_reprocessed
                    # 가 바뀐 뒤 재실행하면 code_version 이 뒤섞인 채 남는 문제였다.
                    cur.execute(f"DELETE FROM {TABLE} WHERE trade_date = %s AND window_kind = %s",
                                (d, kind))
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
