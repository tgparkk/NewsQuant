"""스케줄러가 크롤러의 사이클 경계를 열고 요약을 남기는지 검증한다."""
import logging

import pytest

from news_scraper.scheduler import NewsScheduler


class SpyCrawler:
    """사이클 경계 호출을 기록하는 크롤러 대역."""

    def __init__(self, source_name="hankyung", news=None, raises=None):
        self.source_name = source_name
        self._news = news if news is not None else [{"title": "t"}]
        self._raises = raises
        self.calls = []

    def begin_cycle(self):
        self.calls.append("begin_cycle")

    def cycle_summary(self):
        self.calls.append("cycle_summary")
        return f"[{self.source_name}] 요청 45 · 성공 12 · 403 6 · 생략 27 · 소요 31s"

    def crawl_news_list(self, max_pages=5):
        self.calls.append("crawl")
        if self._raises:
            raise self._raises
        return self._news


@pytest.fixture
def scheduler():
    """DB·크롤러 초기화를 건너뛴 빈 스케줄러."""
    return NewsScheduler.__new__(NewsScheduler)


def test_크롤링_전에_begin_cycle이_호출된다(scheduler):
    crawler = SpyCrawler()

    scheduler._run_single_crawler(crawler)

    assert crawler.calls[0] == "begin_cycle"


def test_크롤링_후에_사이클_요약이_INFO로_남는다(scheduler, caplog):
    crawler = SpyCrawler()

    with caplog.at_level(logging.INFO, logger="news_scraper.scheduler"):
        scheduler._run_single_crawler(crawler)

    assert any("요청 45 · 성공 12" in r.getMessage() for r in caplog.records)


def test_크롤러가_예외를_던져도_요약이_남는다(scheduler, caplog):
    """터진 사이클이야말로 «무슨 일이 있었는지»가 필요하다."""
    crawler = SpyCrawler(raises=RuntimeError("파싱 실패"))

    with caplog.at_level(logging.INFO, logger="news_scraper.scheduler"):
        scheduler._run_single_crawler(crawler)

    assert "cycle_summary" in crawler.calls


def test_예외가_나도_결과_튜플_형식은_유지된다(scheduler):
    crawler = SpyCrawler(raises=RuntimeError("파싱 실패"))

    source, news_list, error = scheduler._run_single_crawler(crawler)

    assert (source, news_list) == ("hankyung", [])
    assert "파싱 실패" in error


def test_사이클_경계를_모르는_크롤러도_그대로_동작한다(scheduler):
    """begin_cycle/cycle_summary 가 없는 크롤러(예: RSS 기반)를 깨뜨리지 않는다."""

    class LegacyCrawler:
        source_name = "google_news_tech"

        def crawl_news_list(self, max_pages=5):
            return [{"title": "t"}]

    source, news_list, error = scheduler._run_single_crawler(LegacyCrawler())

    assert (source, len(news_list), error) == ("google_news_tech", 1, None)


def test_빈_요약은_로그에_남기지_않는다(scheduler, caplog):
    class QuietCrawler(SpyCrawler):
        def cycle_summary(self):
            return ""

    with caplog.at_level(logging.INFO, logger="news_scraper.scheduler"):
        scheduler._run_single_crawler(QuietCrawler("dart"))

    assert not any(r.getMessage() == "" for r in caplog.records)
