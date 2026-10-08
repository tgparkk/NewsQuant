"""주가 일봉 조회기 — 공유 DB daily_prices(KRX) 기반.

2026-09-18 네이버 옛 일별 시세 페이지가 HTTP 410 으로 폐기돼 주가 수집이 전부
실패했다(선반영 체크가 조용히 무력화). 이 파일은 PriceFetcher 가 네이버를 더 부르지
않고, 옛 호출 형태(메서드·열 이름·pages 의미) 그대로 KRX 일봉을 돌려주는지 고정한다.
"""
from datetime import date

import pandas as pd
import pytest
import requests

from news_scraper.price_fetcher import COLUMNS, PriceFetcher, to_frame

CODE = "005930"          # 삼성전자 — daily_prices 에 확실히 있다


# ── 순수 함수(DB 없음) ─────────────────────────────────────────────

def test_to_frame_열_순서와_전일비_최신순():
    rows = [("2026-10-07", 269000, 272000, 273000, 268000, 100),
            ("2026-10-08", 263000, 270000, 274000, 262000, 200),
            ("2026-10-06", 272000, 271000, 275000, 270000, 300)]
    df = to_frame(rows)
    assert list(df.columns) == COLUMNS
    assert [d.date() for d in df["날짜"]] == [date(2026, 10, 8), date(2026, 10, 7), date(2026, 10, 6)]
    assert df["전일비"].tolist()[:2] == [-6000, -3000]
    assert pd.isna(df["전일비"].iloc[2])                      # 가장 옛 행은 앞 종가가 없다
    assert pd.api.types.is_datetime64_any_dtype(df["날짜"])


def test_to_frame_빈_입력은_열만_있는_빈_표():
    df = to_frame([])
    assert df.empty and list(df.columns) == COLUMNS


# ── 실 DB 왕복 ────────────────────────────────────────────────────

@pytest.fixture
def no_http(monkeypatch):
    """네이버(또는 어떤 HTTP)도 부르면 실패한다."""
    def boom(*a, **k):
        raise AssertionError("PriceFetcher 가 HTTP 를 불렀다")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests.Session, "get", boom)


@pytest.mark.db
def test_get_daily_price_는_pages_당_10행_KRX_종가를_돌려준다(db, no_http):
    df = PriceFetcher(db).get_daily_price(CODE, pages=2)

    assert list(df.columns) == COLUMNS
    assert len(df) == 20
    assert list(df["날짜"]) == sorted(df["날짜"], reverse=True)
    assert df["전일비"].notna().all()                       # 한 행 더 읽어 마지막 행도 채운다

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT date, close FROM daily_prices WHERE trim(stock_code) = %s "
                        "AND close > 0 ORDER BY date DESC LIMIT 1", (CODE,))
            d, close = cur.fetchone()
    finally:
        conn.rollback()
        db._put_connection(conn)
    assert df["날짜"].iloc[0].date().isoformat() == str(d)
    assert df["종가"].iloc[0] == float(close)


@pytest.mark.db
def test_get_price_at_date_는_그날_행만(db, no_http):
    f = PriceFetcher(db)
    got = f.get_price_at_date(CODE, "2026-10-08")
    assert got["날짜"] == "2026-10-08"
    assert set(got) == set(COLUMNS)
    assert got["종가"] > 0 and got["시가"] > 0
    assert f.get_price_at_date(CODE, "2026-10-04") == {}     # 일요일 — 그날 봉이 없다


@pytest.mark.db
def test_모르는_종목은_빈_결과(db, no_http):
    f = PriceFetcher(db)
    assert f.get_daily_price("999999").empty
    assert f.get_price_at_date("999999", "2026-10-08") == {}


@pytest.mark.db
def test_조회는_PK_인덱스를_탄다(db):
    """daily_prices 는 324만 행 · 인덱스 = PK(stock_code, date) 하나. trim(stock_code) 같은
    식을 쓰면 풀스캔(종목당 0.36초)이 되어 분석기가 수백 종목에서 몇 분씩 걸린다."""
    from news_scraper import price_fetcher as PF
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("EXPLAIN " + PF._SELECT + "ORDER BY date DESC LIMIT %s", (CODE, 11))
            plan = "\n".join(r[0] for r in cur.fetchall())
    finally:
        conn.rollback()
        db._put_connection(conn)
    assert "Index" in plan and "Seq Scan" not in plan, plan


@pytest.mark.db
def test_분석기는_자기_DB_연결을_가격_조회기에_넘긴다(db):
    from news_scraper.trading_analyzer import TradingAnalyzer
    a = TradingAnalyzer()
    assert a.price_fetcher.db is a.db


# ── 조용한 실패 방지(리뷰 반영) — 원래 버그가 «오류 없이 3주» 였다 ──────────

class _Cur:
    def __init__(self, rows=None, exc=None):
        self.rows, self.exc = rows or [], exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args):
        if self.exc:
            raise self.exc

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def rollback(self):
        pass


class _DB:
    def __init__(self, rows=None, exc=None):
        self.conn = _Conn(_Cur(rows, exc))
        self.returned = 0

    def get_connection(self):
        return self.conn

    def _put_connection(self, conn):
        self.returned += 1


@pytest.fixture
def fresh_flags(monkeypatch):
    from news_scraper import price_fetcher as PF
    monkeypatch.setattr(PF, "_warned", set())


def test_빈_결과는_프로세스당_한번_경고(caplog, fresh_flags):
    f = PriceFetcher(_DB(rows=[]))
    with caplog.at_level("WARNING", logger="news_scraper.price_fetcher"):
        assert f.get_daily_price("123456").empty
        assert f.get_daily_price("654321").empty
    warns = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warns) == 1 and "daily_prices" in warns[0].getMessage()


def test_오래된_최신봉은_갱신_멈춤_경고(caplog, fresh_flags):
    rows = [("2020-01-03", 100, 100, 100, 100, 1), ("2020-01-02", 99, 99, 99, 99, 1)]
    f = PriceFetcher(_DB(rows=rows))
    with caplog.at_level("WARNING", logger="news_scraper.price_fetcher"):
        df = f.get_daily_price("005930")
    assert len(df) == 2
    assert any("2020-01-03" in r.getMessage() and r.levelname == "WARNING" for r in caplog.records)


def test_조회_오류는_경고_뒤_다시_던지고_연결은_반환(caplog):
    db = _DB(exc=RuntimeError("db down"))
    with caplog.at_level("WARNING", logger="news_scraper.price_fetcher"), pytest.raises(RuntimeError):
        PriceFetcher(db).get_daily_price("005930")
    assert db.returned == 1
    assert any("db down" in r.getMessage() for r in caplog.records if r.levelname == "WARNING")
