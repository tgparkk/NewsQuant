"""실 DB(kis_template) 왕복. DB 없으면 conftest.db 픽스처가 skip 한다."""
from datetime import date, datetime

import pytest

pytestmark = pytest.mark.db

TD = date(1999, 1, 4)   # 실데이터와 겹치지 않는 센티널 거래일


@pytest.fixture
def clean(db):
    yield
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news_sector_hit WHERE trade_date = %s", (TD,))
            cur.execute("DELETE FROM sector_news_score WHERE trade_date = %s", (TD,))
        conn.commit()
    finally:
        db._put_connection(conn)


def _score(key="261", signed=0.4):
    return {"trade_date": TD, "sector_key": key, "sector_name": "반도체 제조업",
            "window_start": datetime(1999, 1, 1, 15, 30), "window_end": datetime(1999, 1, 4, 8, 50),
            "n_news": 4, "n_dir": 3, "n_kw": 2, "n_stock": 2, "n_pos": 2, "n_neg": 1,
            "score_raw": 0.684, "score_norm": 0.395, "score_signed": signed,
            "top_news": [{"news_id": "t1", "title": "x", "c": 0.45, "route": "kw_title"}],
            "dict_version": "test"}


def _hit(news_id="t1", key="261"):
    return {"trade_date": TD, "news_id": news_id, "sector_key": key, "route": "kw_title",
            "routes": "kw_title,stock", "matched": "반도체,005930", "w_match": 1.0, "contribution": 0.45}


def test_tables_exist_and_owned_by_robotrader(db):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tablename, tableowner FROM pg_tables WHERE tablename IN ('sector_news_score','news_sector_hit')")
            rows = dict(cur.fetchall())
    finally:
        db._put_connection(conn)
    assert set(rows) == {"sector_news_score", "news_sector_hit"}
    assert set(rows.values()) == {"robotrader"}


def test_init_is_idempotent(db):
    db.init_sector_news_tables()
    db.init_sector_news_tables()


def test_write_then_read_roundtrip_and_upsert(db, clean):
    assert db.write_sector_news_result(TD, [_score()], [_hit()]) == (1, 1)
    rows = db.get_sector_news_scores(TD)
    assert len(rows) == 1 and rows[0]["sector_key"] == "261" and rows[0]["score_signed"] == 0.4
    assert rows[0]["trade_date"] == "1999-01-04" and isinstance(rows[0]["computed_at"], str)
    assert rows[0]["top_news"][0]["news_id"] == "t1"
    first_computed = rows[0]["computed_at"]

    # 같은 키 재쓰기 → 1행 유지 · 값 갱신 · computed_at 갱신 · hit 는 교체
    assert db.write_sector_news_result(TD, [_score(signed=-0.2)], [_hit("t2")]) == (1, 1)
    rows = db.get_sector_news_scores(TD)
    assert len(rows) == 1 and rows[0]["score_signed"] == -0.2 and rows[0]["computed_at"] >= first_computed
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT news_id FROM news_sector_hit WHERE trade_date = %s", (TD,))
            assert [r[0] for r in cur.fetchall()] == ["t2"]
    finally:
        db._put_connection(conn)


def test_read_empty_day_returns_empty_list(db):
    assert db.get_sector_news_scores(date(1998, 1, 1)) == []


def test_get_news_in_window_shape(db):
    rows = db.get_news_in_window(datetime(2026, 9, 3, 15, 30), datetime(2026, 9, 4, 9, 0))
    assert isinstance(rows, list)
    if rows:
        assert {"news_id", "title", "content", "source", "sentiment_score", "related_stocks", "published_at"} <= set(rows[0])


def test_get_sector_map_as_of_roundtrip(db):
    """스펙 A 함수가 있으면 dict 두 개(0행이어도 OK). 없으면 예외가 그대로 올라온다(잡이 경로 B 를 끈다)."""
    try:
        code_map, names = db.get_sector_map_as_of(date(2026, 9, 4), ["005930", "000660"])
    except Exception as e:
        assert type(e).__name__ == "UndefinedFunction"
        return
    assert isinstance(code_map, dict) and isinstance(names, dict)
    for k, v in code_map.items():
        assert len(k) == 6 and len(v) == 3
    assert db.get_sector_map_as_of(date(2026, 9, 4), []) == ({}, {})
