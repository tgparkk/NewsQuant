"""DART 공시의 접수 시각.

Open DART list.json 은 rcept_dt(YYYYMMDD)만 주고 «시각을 주지 않는다».
그래서 공시가 전부 자정으로 저장됐고 — DB 기준 149,996건 100% —
섹터 집계 창([직전 평일 15:30, now])의 시작보다 앞서서 통째로 빠졌다.
15:30 이후 접수분이 40.5%(60,709건)다. 장 마감 뒤 공시가 가장 크게
움직이는 재료라 이 구멍이 제일 아프다.
"""
from datetime import datetime, time

import pytest

from news_scraper.crawlers.dart_crawler import DARTCrawler
from news_scraper.sector_news_aggregator import compute_window


@pytest.fixture
def crawler():
    return DARTCrawler(api_key="테스트용")


def test_접수일이_오늘이면_수집_시각을_쓴다(crawler):
    """API 가 시각을 안 주므로 '방금 본 시점'이 우리가 아는 가장 정확한 값이다."""
    now = datetime(2026, 9, 11, 18, 43, 6)

    got = crawler.parse_datetime("20260911", now=now)

    assert got == now.isoformat()


def test_접수_시각이_자정이_아니다(crawler):
    now = datetime(2026, 9, 11, 17, 46, 0)

    got = datetime.fromisoformat(crawler.parse_datetime("20260911", now=now))

    assert got.time() != time(0, 0, 0)


def test_장_마감_후_공시가_섹터_집계_창에_들어온다(crawler):
    """이게 원래 고치려던 것이다. 자정으로 찍히면 창 시작(15:30) 보다 앞서
    다음 거래일 집계에서 통째로 빠졌다."""
    now = datetime(2026, 9, 11, 17, 46, 0)   # 금요일 장 마감 후
    published_at = datetime.fromisoformat(crawler.parse_datetime("20260911", now=now))

    _, window_start, window_end = compute_window(now)

    assert window_start < published_at <= window_end


def test_자정으로_찍으면_창에서_빠진다(crawler):
    """고치기 전 동작이 왜 틀렸는지 못 박는다."""
    now = datetime(2026, 9, 11, 17, 46, 0)
    midnight = datetime(2026, 9, 11, 0, 0, 0)

    _, window_start, _ = compute_window(now)

    assert midnight < window_start


def test_접수일이_오늘이_아니면_경고를_남기고도_자정을_쓰지_않는다(crawler, caplog):
    """자정 전후로 어제자 공시가 딸려 오는 경우. 시각을 알 길이 없다."""
    now = datetime(2026, 9, 12, 0, 3, 0)

    with caplog.at_level("WARNING"):
        got = datetime.fromisoformat(crawler.parse_datetime("20260911", now=now))

    assert got.time() != time(0, 0, 0)
    assert "20260911" in caplog.text


def test_형식이_깨져도_자정을_쓰지_않는다(crawler):
    now = datetime(2026, 9, 11, 17, 46, 0)

    got = datetime.fromisoformat(crawler.parse_datetime("", now=now))

    assert got.time() != time(0, 0, 0)


def test_now_를_안_넘기면_현재_시각을_쓴다(crawler):
    before = datetime.now()

    got = datetime.fromisoformat(crawler.parse_datetime(datetime.now().strftime("%Y%m%d")))

    assert before <= got <= datetime.now()
