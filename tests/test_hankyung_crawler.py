"""한국경제 크롤러 테스트.

목록에서 모은 ~720건 «전부» 에 상세 요청을 보내던 탓에 Cloudflare 가
(IP + User-Agent) 단위로 24시간 차단을 걸었다. 상세 요청은 최신 N 건에만
간다는 것을 못 박는다.
네트워크는 타지 않는다 - fetch_page / crawl_news_detail 을 가짜로 갈아끼운다.
"""
from bs4 import BeautifulSoup

from news_scraper.crawlers.hankyung_crawler import HankyungCrawler

LIST_URL = "https://www.hankyung.com/economy?page=1"


def item(index, summary="목록에서 뽑은 요약문이다"):
    """목록 페이지에 실리는 기사 한 건의 모양. index 가 클수록 최신이다."""
    return {
        "href": f"/article/{index:04d}",
        "title": f"한국경제 기사 제목 {index:04d}",
        "date": f"2026-09-11 {8 + index // 60:02d}:{index % 60:02d}",
        "summary": summary,
    }


def nav_item(href, title="한국경제 프리미엄 섹션 안내"):
    """기사가 아닌 내비게이션 링크. 날짜 태그가 없어 now() 폴백을 유발한다."""
    return {"href": href, "title": title, "date": None, "summary": ""}


def list_html(items):
    rows = "".join(
        '<div class="news-item">'
        f'<a href="{it["href"]}">{it["title"]}</a>'
        + (f'<span class="date">{it["date"]}</span>' if it["date"] else "")
        + f'<p class="summary">{it["summary"]}</p>'
        "</div>"
        for it in items
    )
    return f'<html><body><section class="wrap">{rows}</section></body></html>'


def article_url(index):
    return f"https://www.hankyung.com/article/{index:04d}"


class FakeDetail:
    """상세 요청을 기록하고 미리 정해둔 본문을 돌려준다."""

    def __init__(self, bodies=None):
        self.bodies = bodies or {}
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        body = self.bodies.get(url)
        if body is None:
            return None
        return {
            "content": body,
            "published_at": "2026-09-11T00:00:00",
            "related_stocks": "",
        }


def make_crawler(items, bodies=None, **kwargs):
    """첫 섹션 1페이지에만 목록을 물린 크롤러. 나머지 URL 은 None."""
    crawler = HankyungCrawler(**kwargs)
    html = list_html(items)
    crawler.fetch_page = lambda url, **kw: (
        BeautifulSoup(html, "lxml") if url == LIST_URL else None
    )
    detail = FakeDetail(bodies)
    crawler.crawl_news_detail = detail
    return crawler, detail


# --------------------------------------------------------------------------
# 상세 요청 상한 - Cloudflare 차단을 부른 회귀를 막는다
# --------------------------------------------------------------------------

def test_100건을_물려도_상세_요청은_한도만큼만_간다():
    """수정 전에는 목록 전건(100회) 에 상세 요청을 보냈다."""
    crawler, detail = make_crawler([item(i) for i in range(100)])

    news = crawler.crawl_news_list(max_pages=1)

    assert len(news) == 100
    assert len(detail.calls) == crawler.detail_fetch_limit
    assert len(set(detail.calls)) == len(detail.calls), "같은 URL 을 두 번 불렀다"
    assert crawler.detail_fetch_limit == HankyungCrawler.DEFAULT_DETAIL_FETCH_LIMIT


def test_상세_요청은_최신순_상위_N건에만_간다():
    crawler, detail = make_crawler([item(i) for i in range(10)], detail_fetch_limit=3)

    crawler.crawl_news_list(max_pages=1)

    assert detail.calls == [article_url(9), article_url(8), article_url(7)]


def test_한도를_넘는_항목은_목록_요약을_content로_유지한다():
    crawler, _ = make_crawler(
        [item(i, summary=f"요약 {i:04d} 이다") for i in range(10)],
        bodies={article_url(9): "본문 " * 40},
        detail_fetch_limit=1,
    )

    news = crawler.crawl_news_list(max_pages=1)

    oldest = next(n for n in news if n["url"] == article_url(0))
    assert oldest["content"] == "요약 0000 이다"


def test_본문이_50자_이상이면_요약_대신_본문을_쓴다():
    body = "한국경제 기사 본문이다. " * 10
    crawler, _ = make_crawler(
        [item(0, summary="짧은 요약문이다")],
        bodies={article_url(0): body},
        detail_fetch_limit=5,
    )

    news = crawler.crawl_news_list(max_pages=1)

    assert len(body) >= 50
    assert news[0]["content"] == body


def test_본문_수집_한도가_0이면_상세_요청을_하지_않는다():
    crawler, detail = make_crawler([item(i) for i in range(5)], detail_fetch_limit=0)

    news = crawler.crawl_news_list(max_pages=1)

    assert detail.calls == []
    assert len(news) == 5


# --------------------------------------------------------------------------
# 중복 제거 - 목록 파서가 중첩 div 를 전부 잡아 같은 기사가 거듭 실린다
# --------------------------------------------------------------------------

def test_같은_기사가_목록에_여러_번_실려도_한_번만_담긴다():
    """실측: 항목 717건이 distinct 176건이었다 (중복 4.07배)."""
    items = [item(i) for i in range(10)]
    crawler, detail = make_crawler(items + items[:5] + items, detail_fetch_limit=3)

    news = crawler.crawl_news_list(max_pages=1)

    assert len(news) == 10
    assert len({n["url"] for n in news}) == 10
    assert detail.calls == [article_url(9), article_url(8), article_url(7)]


def test_중복이_섞여도_상세_예산을_distinct_기사에_쓴다():
    """예산 30건이 중복 URL 3개에 쓰이던 결함을 막는다."""
    items = [item(i) for i in range(10)]
    crawler, detail = make_crawler(items * 4, detail_fetch_limit=5)

    crawler.crawl_news_list(max_pages=1)

    assert len(detail.calls) == 5
    assert len(set(detail.calls)) == 5


# --------------------------------------------------------------------------
# 기사 URL 필터 - 내비게이션 링크가 now() 폴백으로 정렬 1등을 점거했다
# --------------------------------------------------------------------------

def test_기사가_아닌_URL은_수집하지_않는다():
    navs = [
        nav_item("https://www.hankyung.com"),
        nav_item("/premium9/0101003"),
        nav_item("/premium9/0107002"),
    ]
    crawler, detail = make_crawler(navs + [item(i) for i in range(3)],
                                  detail_fetch_limit=10)

    news = crawler.crawl_news_list(max_pages=1)

    urls = {n["url"] for n in news}
    assert urls == {article_url(0), article_url(1), article_url(2)}
    assert not any("premium9" in u for u in detail.calls)
    assert "https://www.hankyung.com" not in detail.calls


def test_날짜없는_내비링크가_최신순_상위를_점거하지_못한다():
    """날짜 태그가 없으면 parse_date_string 이 now() 를 준다 - 실제 기사보다 최신이 된다."""
    navs = [nav_item("https://www.hankyung.com"), nav_item("/premium9/0101003")]
    crawler, detail = make_crawler(navs + [item(i) for i in range(5)],
                                  detail_fetch_limit=2)

    crawler.crawl_news_list(max_pages=1)

    assert detail.calls == [article_url(4), article_url(3)]


# --------------------------------------------------------------------------
# 섹션 목록 - 개편으로 사라진 URL 은 매 사이클 404 를 만든다
# --------------------------------------------------------------------------

def test_죽은_섹션은_더_이상_요청하지_않는다():
    requested = []
    crawler = HankyungCrawler(detail_fetch_limit=0)
    crawler.fetch_page = lambda url, **kw: requested.append(url)

    crawler.crawl_news_list(max_pages=1)

    assert requested, "섹션을 하나도 요청하지 않았다"
    assert not any("financial-market" in u for u in requested)
    assert not any("distribution" in u for u in requested)
    assert any("/economy" in u for u in requested)


# --------------------------------------------------------------------------
# User-Agent - 무작위 풀은 차단 범위를 넓히고 신호를 가렸다
# --------------------------------------------------------------------------

def test_base_crawler는_고정_UA를_쓴다():
    crawlers = [HankyungCrawler() for _ in range(10)]

    agents = {c.session.headers["User-Agent"] for c in crawlers}
    assert len(agents) == 1
    assert "Chrome/" in agents.pop()
    assert not any(hasattr(c, "user_agents") for c in crawlers)
