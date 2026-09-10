"""네이버 금융 크롤러 테스트.

finance.naver.com 의 HTML 목록은 stock.naver.com SPA 로 대체되어 뉴스가
없다. 크롤러는 그 SPA 가 쓰는 내부 JSON API 를 직접 호출한다.
네트워크는 타지 않는다 - fetch_json / fetch_page 를 가짜로 갈아끼운다.
"""
import logging

import pytest

from news_scraper.crawlers.naver_finance_crawler import NaverFinanceCrawler


def article(article_id="0005733654", office_id="009", title="스페이스X 락업물량 풀려도 걱정없는 이유",
            datetime_="2026-09-10 23:45:09", subcontent="내년 6월까지 락업해제 12차례"):
    """API 가 돌려주는 기사 한 건의 모양."""
    return {
        "officeId": office_id,
        "officeHname": "매일경제",
        "articleId": article_id,
        "title": title,
        "datetime": datetime_,
        "type": "1",
        "subcontent": subcontent,
        "thumbUrl": None,
    }


class FakeApi:
    """호출을 기록하고 미리 정해둔 응답을 순서대로 돌려준다."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, params=None, **kwargs):
        self.calls.append((url, dict(params or {})))
        if not self._responses:
            return {"articles": []}
        item = self._responses.pop(0)
        return item


def make_crawler(responses, bodies=None, **kwargs):
    """API 응답 목록을 물린 크롤러. bodies 는 url -> 본문 문자열."""
    crawler = NaverFinanceCrawler(**kwargs)
    crawler.fetch_json = FakeApi(responses)
    bodies = bodies or {}
    crawler.crawl_news_detail = lambda url: (
        {"content": bodies[url]} if url in bodies else None
    )
    return crawler


def page(articles):
    return {"articles": articles, "articleTotal": len(articles)}


# --------------------------------------------------------------------------
# API 응답 -> news 레코드 매핑
# --------------------------------------------------------------------------

def test_API_기사_한_건이_news_레코드로_매핑된다():
    crawler = make_crawler([page([article()])], detail_fetch_limit=0)

    news = crawler.crawl_news_list(max_pages=1)

    assert len(news) == 1
    assert news[0]["title"] == "스페이스X 락업물량 풀려도 걱정없는 이유"
    assert news[0]["source"] == "naver_finance"


def test_published_at은_API의_발행시각이지_수집시각이_아니다():
    """구 HTML 크롤러는 날짜를 못 찾으면 now() 를 넣어 발행시각을 위조했다."""
    crawler = make_crawler(
        [page([article(datetime_="2026-09-10 23:45:09")])], detail_fetch_limit=0
    )

    news = crawler.crawl_news_list(max_pages=1)

    assert news[0]["published_at"].startswith("2026-09-10T23:45:09")


def test_url은_기사_페이지_주소로_조립된다():
    crawler = make_crawler(
        [page([article(office_id="009", article_id="0005733654")])], detail_fetch_limit=0
    )

    news = crawler.crawl_news_list(max_pages=1)

    assert news[0]["url"] == "https://n.news.naver.com/mnews/article/009/0005733654"


def test_요약이_content로_들어간다():
    crawler = make_crawler(
        [page([article(subcontent="락업해제 12차례")])], detail_fetch_limit=0
    )

    news = crawler.crawl_news_list(max_pages=1)

    assert news[0]["content"] == "락업해제 12차례"


def test_news_id가_부여된다():
    crawler = make_crawler([page([article()])], detail_fetch_limit=0)

    news = crawler.crawl_news_list(max_pages=1)

    assert news[0]["news_id"].startswith("naver_finance_")


def test_제목과_요약에서_종목코드를_뽑는다():
    crawler = make_crawler(
        [page([article(title="삼성전자 4분기 실적 전망", subcontent="반도체 업황")])],
        detail_fetch_limit=0,
    )

    news = crawler.crawl_news_list(max_pages=1)

    assert "005930" in news[0]["related_stocks"]


# --------------------------------------------------------------------------
# 불량 응답 - 조용히 0건을 반환하는 실패를 반복하지 않는다
# --------------------------------------------------------------------------

def test_필수_필드가_없는_기사는_건너뛴다():
    bad = article()
    del bad["datetime"]
    crawler = make_crawler([page([bad, article(article_id="0000000002")])],
                           detail_fetch_limit=0)

    news = crawler.crawl_news_list(max_pages=1)

    assert len(news) == 1


def test_articles_키가_없으면_경고를_남긴다(caplog):
    """API 스키마가 바뀌면 조용히 0건이 아니라 시끄럽게 실패해야 한다."""
    crawler = make_crawler([{"unexpected": []}], detail_fetch_limit=0)

    with caplog.at_level(logging.WARNING, logger="news_scraper.crawlers.naver_finance_crawler"):
        crawler.crawl_news_list(max_pages=1)

    assert any("articles" in r.getMessage() for r in caplog.records)


def test_한_건도_못_모으면_경고를_남긴다(caplog):
    """이 크롤러가 몇 달간 0건을 조용히 반환하던 버그를 다시 겪지 않게."""
    crawler = make_crawler([page([])], detail_fetch_limit=0)

    with caplog.at_level(logging.WARNING, logger="news_scraper.crawlers.naver_finance_crawler"):
        news = crawler.crawl_news_list(max_pages=1)

    assert news == []
    assert any("0건" in r.getMessage() for r in caplog.records)


def test_API가_None을_주면_그_구간만_건너뛴다():
    """fetch_json 이 None (차단/오류) 이어도 다른 섹션은 계속 수집한다."""
    crawler = make_crawler([None, page([article()])], detail_fetch_limit=0)

    news = crawler.crawl_news_list(max_pages=1)

    assert len(news) == 1


# --------------------------------------------------------------------------
# 페이지네이션 - page 를 넘겨도 같은 데이터가 오므로 중단 조건이 필요하다
# --------------------------------------------------------------------------

def test_새_기사가_없는_페이지를_만나면_그_섹션을_멈춘다():
    """실측상 page=10 과 page=50 이 같은 데이터를 준다. 무한 수집을 막는다."""
    same = article(article_id="0000000001")
    crawler = make_crawler(
        [page([same]), page([same]), page([same]), page([same])],
        detail_fetch_limit=0,
    )

    crawler.crawl_news_list(max_pages=5)

    # 섹션 4개 x (새 기사 있는 1페이지 + 중복 확인 1페이지) = 8 이하
    assert len(crawler.fetch_json.calls) <= 8


def test_같은_기사가_여러_섹션에_나와도_한_번만_담긴다():
    same = article(article_id="0000000001")
    crawler = make_crawler([page([same])] * 8, detail_fetch_limit=0)

    news = crawler.crawl_news_list(max_pages=2)

    assert len(news) == 1


def test_max_pages를_넘겨_요청하지_않는다():
    crawler = make_crawler(
        [page([article(article_id=f"{i:010d}")]) for i in range(50)],
        detail_fetch_limit=0,
    )

    crawler.crawl_news_list(max_pages=2)

    pages = [p.get("page") for _, p in crawler.fetch_json.calls]
    assert max(pages) == 2


def test_pageSize_100으로_요청한다():
    crawler = make_crawler([page([article()])], detail_fetch_limit=0)

    crawler.crawl_news_list(max_pages=1)

    assert crawler.fetch_json.calls[0][1]["pageSize"] == 100


def test_속보와_주요_섹션을_모두_호출한다():
    crawler = make_crawler([page([article()])] * 8, detail_fetch_limit=0)

    crawler.crawl_news_list(max_pages=1)

    urls = {url for url, _ in crawler.fetch_json.calls}
    assert any("news/list" in u for u in urls)
    assert any("news/focus" in u for u in urls)


def test_섹션_이름이_category에_담긴다():
    crawler = make_crawler([page([article()])], detail_fetch_limit=0)

    news = crawler.crawl_news_list(max_pages=1)

    assert news[0]["category"]


# --------------------------------------------------------------------------
# 본문 수집 - 요약은 전부, 전문은 상위 N 건만
# --------------------------------------------------------------------------

def test_상위_N건만_본문을_가져온다():
    arts = [article(article_id=f"{i:010d}", subcontent="요약") for i in range(5)]
    bodies = {
        f"https://n.news.naver.com/mnews/article/009/{i:010d}": "전문 " * 60
        for i in range(5)
    }
    crawler = make_crawler([page(arts)], bodies=bodies, detail_fetch_limit=2)

    news = crawler.crawl_news_list(max_pages=1)

    full = [n for n in news if n["content"].startswith("전문")]
    assert len(full) == 2


def test_본문을_못_가져온_기사는_요약을_유지한다():
    crawler = make_crawler([page([article(subcontent="요약문")])], bodies={},
                           detail_fetch_limit=5)

    news = crawler.crawl_news_list(max_pages=1)

    assert news[0]["content"] == "요약문"


def test_본문이_요약보다_짧으면_요약을_유지한다():
    url = "https://n.news.naver.com/mnews/article/009/0005733654"
    crawler = make_crawler(
        [page([article(subcontent="이 요약문은 본문보다 훨씬 길고 자세한 내용을 담고 있다")])],
        bodies={url: "짧음"},
        detail_fetch_limit=5,
    )

    news = crawler.crawl_news_list(max_pages=1)

    assert news[0]["content"].startswith("이 요약문은")


def test_본문_수집_한도가_0이면_상세_요청을_하지_않는다():
    calls = []
    crawler = make_crawler([page([article()])], detail_fetch_limit=0)
    crawler.crawl_news_detail = lambda url: calls.append(url)

    crawler.crawl_news_list(max_pages=1)

    assert calls == []


def test_최신순으로_본문_수집_대상을_고른다():
    arts = [
        article(article_id="0000000001", datetime_="2026-09-10 09:00:00"),
        article(article_id="0000000002", datetime_="2026-09-10 23:00:00"),
    ]
    bodies = {
        "https://n.news.naver.com/mnews/article/009/0000000002": "전문 " * 60,
    }
    crawler = make_crawler([page(arts)], bodies=bodies, detail_fetch_limit=1)

    news = crawler.crawl_news_list(max_pages=1)

    newest = next(n for n in news if n["url"].endswith("0000000002"))
    assert newest["content"].startswith("전문")


# --------------------------------------------------------------------------
# 본문 파싱 - 기사 페이지 셀렉터
# --------------------------------------------------------------------------

def test_기사_본문을_dic_area에서_뽑는다():
    from bs4 import BeautifulSoup

    crawler = NaverFinanceCrawler()
    html = '<html><body><div id="dic_area">기사 본문 내용이다</div></body></html>'
    crawler.fetch_page = lambda url, **kw: BeautifulSoup(html, "lxml")

    detail = crawler.crawl_news_detail("https://n.news.naver.com/mnews/article/009/1")

    assert detail["content"] == "기사 본문 내용이다"


def test_본문_영역이_없으면_None을_돌려준다():
    from bs4 import BeautifulSoup

    crawler = NaverFinanceCrawler()
    crawler.fetch_page = lambda url, **kw: BeautifulSoup("<html></html>", "lxml")

    assert crawler.crawl_news_detail("https://n.news.naver.com/mnews/article/009/1") is None


def test_페이지를_못_받으면_None을_돌려준다():
    crawler = NaverFinanceCrawler()
    crawler.fetch_page = lambda url, **kw: None

    assert crawler.crawl_news_detail("https://n.news.naver.com/mnews/article/009/1") is None
