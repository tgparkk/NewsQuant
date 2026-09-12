"""실 DB(kis_template) 왕복 - news upsert 의 content 갱신 규칙.

DB 없으면 conftest.db 픽스처가 skip 한다.

한경 크롤러는 사이클당 최신 30건만 전문을 받는다. 예산 밖이던 기사가 다음
사이클에 전문과 함께 다시 들어오면 빈 content 가 채워져야 한다. 구 upsert 는
duplicate_count 만 올리고 content 를 건드리지 않아 한 번 비면 영구히 비었다.
"""
from datetime import datetime

import pytest

pytestmark = pytest.mark.db

SENTINEL = "test-upsert-content-0001"   # 실데이터와 겹치지 않는 센티널


@pytest.fixture
def clean(db):
    yield
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news WHERE news_id = %s", (SENTINEL,))
        conn.commit()
    finally:
        db._put_connection(conn)


def _news(content):
    return {
        "news_id": SENTINEL,
        "title": "업서트 본문 갱신 테스트",
        "content": content,
        "published_at": datetime(1999, 1, 4, 9, 0).isoformat(),
        "source": "hankyung",
        "category": "경제",
        "url": "https://www.hankyung.com/article/1999010400001",
        "related_stocks": "",
        "sentiment_score": None,
    }


def _row(db):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content, duplicate_count FROM news WHERE news_id = %s",
                (SENTINEL,),
            )
            return cur.fetchone()
    finally:
        db._put_connection(conn)


def test_빈_본문이_나중에_들어온_전문으로_채워진다(db, clean):
    body = "가" * 1200

    assert db.insert_news(_news("")) is True
    assert _row(db)[0] == ""

    assert db.insert_news(_news(body)) is True
    content, dup = _row(db)
    assert content == body, "예산 밖이던 기사의 빈 본문이 채워지지 않았다"
    assert dup == 2, "duplicate_count 증가는 그대로 유지돼야 한다"


def test_더_짧은_본문은_기존_전문을_덮어쓰지_않는다(db, clean):
    body = "나" * 1200

    assert db.insert_news(_news(body)) is True
    assert db.insert_news(_news("150자 티저…")) is True

    content, dup = _row(db)
    assert content == body, "짧은 목록 요약이 이미 받아둔 전문을 밀어냈다"
    assert dup == 2


def test_배치_삽입도_같은_규칙을_따른다(db, clean):
    body = "다" * 900

    assert db.insert_news_batch([_news("")]) == 1
    assert db.insert_news_batch([_news(body)]) == 1

    content, dup = _row(db)
    assert content == body, "배치 경로에서 빈 본문이 채워지지 않았다"
    assert dup == 2
