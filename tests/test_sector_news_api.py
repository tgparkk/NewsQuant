from datetime import date, datetime

import pytest

pytestmark = pytest.mark.db   # server 모듈 import 가 NewsDatabase() 를 만든다 → 실 DB 필요

TD = date(1999, 1, 5)   # 실데이터와 겹치지 않는 센티널 거래일 (test_sector_news_db.py 의 1999-01-04 와 별개)


def _score(key="261", signed=0.4):
    return {"trade_date": TD, "sector_key": key, "sector_name": "반도체 제조업",
            "window_start": datetime(1999, 1, 2, 15, 30), "window_end": datetime(1999, 1, 5, 8, 50),
            "n_news": 4, "n_dir": 3, "n_kw": 2, "n_stock": 2, "n_pos": 2, "n_neg": 1,
            "score_raw": 0.684, "score_norm": 0.395, "score_signed": signed,
            "top_news": [{"news_id": "t1", "title": "x", "c": 0.45, "route": "kw_title"}],
            "dict_version": "test"}


@pytest.fixture(scope="module")
def client(db):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from news_scraper.api.server import app
    return TestClient(app)


def test_sector_news_score_default_today(client):
    r = client.get("/api/sector/news-score")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and "trade_date" in body and body["count"] == len(body["data"])


def test_sector_news_score_explicit_empty_day(client):
    r = client.get("/api/sector/news-score", params={"trade_date": "1998-01-01"})
    assert r.status_code == 200
    assert r.json() == {"success": True, "trade_date": "1998-01-01", "count": 0, "computed_at_max": None, "data": []}


def test_sector_news_score_bad_date_400(client):
    r = client.get("/api/sector/news-score", params={"trade_date": "2026/09/08"})
    assert r.status_code == 400


def test_sector_news_score_sorted_desc(client, db):
    try:
        db.write_sector_news_result(TD, [_score(key="261", signed=0.2), _score(key="641", signed=0.9)], [])
        r = client.get("/api/sector/news-score", params={"trade_date": TD.isoformat()})
        assert r.status_code == 200
        body = r.json()
        assert [row["sector_key"] for row in body["data"]] == ["641", "261"]
        assert body["computed_at_max"] == max(row["computed_at"] for row in body["data"])
    finally:
        conn = db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM news_sector_hit WHERE trade_date = %s", (TD,))
                cur.execute("DELETE FROM sector_news_score WHERE trade_date = %s", (TD,))
            conn.commit()
        finally:
            db._put_connection(conn)
