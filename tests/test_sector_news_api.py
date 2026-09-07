import pytest

pytestmark = pytest.mark.db   # server 모듈 import 가 NewsDatabase() 를 만든다 → 실 DB 필요


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
