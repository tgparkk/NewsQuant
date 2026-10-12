"""글로벌 RSS 크롤러의 본문 보강 테스트.

RSS 는 요약(또는 빈 문자열) 만 준다 - 최근 14일 실측으로 cnbc·marketwatch·
investing_com 은 본문 200자 미만이 95~100% 였다 (2026-10-12). 상세 요청으로
본문을 채우되, 한국경제가 2026-09-11 에 하루 720건 요청으로 Cloudflare 24시간
차단을 당한 전례가 있으므로 상한이 두 겹이다:
  1. 사이클당 최대 N 건
  2. 한 번 시도한 URL 은 프로세스가 사는 동안 다시 두드리지 않는다
네트워크는 타지 않는다 - _parse_rss_feed / crawl_news_detail 을 가짜로 갈아끼운다.
"""
import logging

from bs4 import BeautifulSoup

from news_scraper.crawlers.global_news_crawler import GlobalNewsCrawler

CNBC = "https://www.cnbc.com/2026/10/12/article-{index:04d}.html"
MARKETWATCH = "https://www.marketwatch.com/story/article-{index:04d}"
GOOGLE = "https://news.google.com/rss/articles/CBMi{index:04d}?oc=5"

LONG_SUMMARY = "Korea semiconductor export summary sentence. " * 6  # ≥ 200자
SHORT_SUMMARY = "Korea chip stocks rally."


def item(index, url=CNBC, source="cnbc", summary=SHORT_SUMMARY):
    """RSS 항목 한 건. index 가 클수록 최신이다. 제목에 korea 가 있어 관련도 필터를 넘는다."""
    return {
        "news_id": f"global_news_{source}_{index:04d}",
        "title": f"Korea market story number {index:04d}",
        "content": summary,
        "published_at": f"2026-10-12T{8 + index // 60:02d}:{index % 60:02d}:00",
        "source": source,
        "category": "us_market",
        "url": url.format(index=index),
        "related_stocks": "",
        "sentiment_score": None,
        "korea_relevance": 0.3,
        "language": "en",
    }


class FakeDetail:
    """상세 요청을 기록하고 미리 정해둔 본문을 돌려준다."""

    def __init__(self, bodies=None):
        self.bodies = bodies or {}
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        body = self.bodies.get(url)
        return {"content": body} if body else None


def make_crawler(items, bodies=None, warmed=True, **kwargs):
    """첫 피드에만 항목을 물린 크롤러. 나머지 피드는 빈 목록.

    warmed=True 면 «프로세스 시작 뒤 첫 사이클(예열)» 은 지난 것으로 둔다 - 예열은
    별도 테스트에서 본다.
    """
    crawler = GlobalNewsCrawler(**kwargs)
    if warmed:
        crawler._warmed_up = True
    first_feed = crawler.RSS_FEEDS[0]["url"]
    crawler._parse_rss_feed = lambda feed_url, source, category: (
        list(items) if feed_url == first_feed else []
    )
    detail = FakeDetail(bodies)
    crawler.crawl_news_detail = detail
    return crawler, detail


# --------------------------------------------------------------------------
# 상한 1 - 사이클당 N 건
# --------------------------------------------------------------------------

def test_100건을_물려도_상세_요청은_한도만큼만_간다():
    crawler, detail = make_crawler([item(i) for i in range(100)])

    news = crawler.crawl_news_list(max_pages=1)

    assert len(news) == 100
    assert len(detail.calls) == crawler.detail_fetch_limit
    assert crawler.detail_fetch_limit == GlobalNewsCrawler.DEFAULT_DETAIL_FETCH_LIMIT
    assert len(set(detail.calls)) == len(detail.calls), "같은 URL 을 두 번 불렀다"


def test_상세_요청은_최신순_상위_N건에만_간다():
    crawler, detail = make_crawler([item(i) for i in range(10)], detail_fetch_limit=3)

    crawler.crawl_news_list(max_pages=1)

    assert detail.calls == [CNBC.format(index=9), CNBC.format(index=8), CNBC.format(index=7)]


def test_한도가_0이면_상세_요청을_하지_않는다():
    crawler, detail = make_crawler([item(i) for i in range(5)], detail_fetch_limit=0)

    news = crawler.crawl_news_list(max_pages=1)

    assert detail.calls == []
    assert len(news) == 5


# --------------------------------------------------------------------------
# 상한 2 - 한 번 시도한 URL 은 다시 두드리지 않는다
# --------------------------------------------------------------------------

def test_다음_사이클에_같은_URL은_다시_요청하지_않는다():
    """RSS 는 사이클마다 같은 30건을 되돌려준다. 매 사이클 재요청하면 한경 720건 꼴이 난다."""
    items = [item(i) for i in range(5)]
    crawler, detail = make_crawler(items, bodies={CNBC.format(index=4): "body " * 60})

    crawler.begin_cycle()
    crawler.crawl_news_list(max_pages=1)
    first_cycle = list(detail.calls)
    crawler.begin_cycle()
    crawler.crawl_news_list(max_pages=1)

    assert len(first_cycle) == 5
    assert detail.calls == first_cycle, "두 번째 사이클에서 상세 요청이 또 나갔다"


def test_실패한_URL도_재시도하지_않는다():
    crawler, detail = make_crawler([item(0)])  # bodies 없음 → 실패

    crawler.crawl_news_list(max_pages=1)
    crawler.crawl_news_list(max_pages=1)

    assert detail.calls == [CNBC.format(index=0)]


def test_시도_기록은_상한에서_오래된_것부터_밀려난다():
    """한 번에 비우면 피드에 남아 있는 최근 URL 을 전부 다시 두드린다 - 오래된 것만 잊는다."""
    crawler, _ = make_crawler([])
    cap = GlobalNewsCrawler.DETAIL_TRIED_CAP
    for i in range(cap + 5):
        crawler._remember_tried(f"https://www.cnbc.com/x/{i}")

    assert len(crawler._detail_tried) == cap
    assert crawler._was_tried(f"https://www.cnbc.com/x/{cap + 4}")
    assert not crawler._was_tried("https://www.cnbc.com/x/0")


def test_같은_기사의_추적_쿼리가_달라도_한_번만_시도한다():
    crawler, detail = make_crawler([
        item(0, url="https://www.cnbc.com/2026/a.html?__source=rss"),
        item(1, url="https://www.cnbc.com/2026/a.html?__source=newsletter"),
    ])

    crawler.crawl_news_list(max_pages=1)

    assert len(detail.calls) == 1


# --------------------------------------------------------------------------
# 예열 - 프로세스 시작 뒤 첫 사이클은 «이미 저장돼 있던» 기사라 본문을 받지 않는다
# --------------------------------------------------------------------------

def test_첫_사이클은_피드에_있던_URL을_시도한_것으로만_기록하고_요청하지_않는다():
    """재시작 때 피드 창(30건)의 기사는 거의 모두 요약으로 저장돼 있다. 본문을 받으면
    UPSERT 「더 긴 쪽」 규칙으로 기존 행이 덮어써진다 - 과거 행은 그대로 둔다는 약속 위반."""
    crawler, detail = make_crawler([item(i) for i in range(5)], warmed=False)

    crawler.begin_cycle()
    news = crawler.crawl_news_list(max_pages=1)

    assert detail.calls == []
    assert len(news) == 5
    assert all(crawler._was_tried(n["url"]) for n in news)


def test_둘째_사이클부터_새로_나타난_URL에만_본문을_받는다():
    crawler, detail = make_crawler([item(i) for i in range(5)], warmed=False)
    crawler.begin_cycle(); crawler.crawl_news_list(max_pages=1)

    crawler._parse_rss_feed = lambda feed_url, source, category: (
        [item(i) for i in range(7)] if feed_url == crawler.RSS_FEEDS[0]["url"] else []
    )
    crawler.begin_cycle(); crawler.crawl_news_list(max_pages=1)

    assert detail.calls == [CNBC.format(index=6), CNBC.format(index=5)]


# --------------------------------------------------------------------------
# 대상 선별 - 어느 기사에 본문 요청을 보내는가
# --------------------------------------------------------------------------

def test_구글뉴스_중계_링크는_본문_요청을_보내지_않는다():
    """news.google.com 주소는 JS 리다이렉트라 본문 페이지가 아니다."""
    items = [item(i, url=GOOGLE, source="google_news_finance") for i in range(5)]
    crawler, detail = make_crawler(items)

    news = crawler.crawl_news_list(max_pages=1)

    assert detail.calls == []
    assert len(news) == 5


def test_허용_호스트는_cnbc_marketwatch_둘이다():
    """investing.com 은 2026-10-12 실측 Cloudflare 403 - 막힌 문을 두드리면 차단만 부른다."""
    assert GlobalNewsCrawler._detail_host("https://www.cnbc.com/2026/a.html") == "cnbc.com"
    assert GlobalNewsCrawler._detail_host("https://www.marketwatch.com/story/x") == "marketwatch.com"
    assert GlobalNewsCrawler._detail_host("https://www.investing.com/news/x-123") is None
    assert GlobalNewsCrawler._detail_host("https://news.google.com/rss/articles/x") is None
    assert GlobalNewsCrawler._detail_host("https://cnbc.com.evil.example/x") is None


def test_요약이_이미_200자_이상이면_본문_요청을_생략한다():
    items = [item(0, summary=LONG_SUMMARY), item(1, summary=SHORT_SUMMARY)]
    crawler, detail = make_crawler(items)

    crawler.crawl_news_list(max_pages=1)

    assert detail.calls == [CNBC.format(index=1)]


def test_관련도_필터에_걸린_기사에는_본문_요청을_보내지_않는다():
    """저장되지 않을 기사에 요청을 쓰면 상한만 갉아먹는다."""
    irrelevant = item(0)
    irrelevant["title"] = "Local bake sale raises funds"
    irrelevant["content"] = "Cupcakes."
    irrelevant["korea_relevance"] = 0.0
    crawler, detail = make_crawler([irrelevant, item(1)])

    news = crawler.crawl_news_list(max_pages=1)

    assert [n["url"] for n in news] == [CNBC.format(index=1)]
    assert detail.calls == [CNBC.format(index=1)]


def test_시간_예산이_다_떨어지면_남은_본문_요청을_접는다():
    clock = {"now": 0.0}
    crawler, detail = make_crawler(
        [item(i) for i in range(5)], time_budget=10, clock=lambda: clock["now"]
    )
    crawler.begin_cycle()

    def tick(url):
        clock["now"] += 6  # 두 번째 요청 뒤 예산(10초) 초과
        detail.calls.append(url)

    crawler.crawl_news_detail = tick
    crawler.crawl_news_list(max_pages=1)

    assert len(detail.calls) == 2


# --------------------------------------------------------------------------
# 본문 반영 - 더 긴 쪽을 남긴다 (DB UPSERT 규칙과 같은 방향)
# --------------------------------------------------------------------------

def test_본문이_요약보다_길면_본문으로_바꾼다():
    body = "CNBC article body text. " * 20
    crawler, _ = make_crawler([item(0)], bodies={CNBC.format(index=0): body})

    news = crawler.crawl_news_list(max_pages=1)

    assert news[0]["content"] == body


def test_본문이_없거나_요약보다_짧으면_요약을_유지한다():
    items = [item(0), item(1)]
    crawler, _ = make_crawler(items, bodies={CNBC.format(index=1): "Short."})

    news = crawler.crawl_news_list(max_pages=1)

    by_url = {n["url"]: n for n in news}
    assert by_url[CNBC.format(index=0)]["content"] == SHORT_SUMMARY
    assert by_url[CNBC.format(index=1)]["content"] == SHORT_SUMMARY


def test_본문_요청이_예외를_던져도_수집은_계속되고_요약은_남는다():
    crawler, _ = make_crawler([item(0), item(1)])

    def boom(url):
        raise RuntimeError("connection reset")

    crawler.crawl_news_detail = boom
    news = crawler.crawl_news_list(max_pages=1)

    assert len(news) == 2
    assert all(n["content"] == SHORT_SUMMARY for n in news)


# --------------------------------------------------------------------------
# 조용한 실패 방지 - 호스트가 계속 막히면 프로세스당 한 번 WARNING
# --------------------------------------------------------------------------

def test_호스트가_연속_실패하면_프로세스당_한_번만_WARNING(caplog):
    threshold = GlobalNewsCrawler.DETAIL_WARN_AFTER
    items = [item(i) for i in range(threshold + 5)]
    crawler, _ = make_crawler(items, detail_fetch_limit=threshold + 5)

    with caplog.at_level(logging.WARNING, logger="news_scraper.crawlers.global_news_crawler"):
        crawler.crawl_news_list(max_pages=1)
        # 다음 사이클에 새 URL 이 더 와도 경고는 다시 나지 않는다
        crawler._parse_rss_feed = lambda feed_url, source, category: (
            [item(i, url="https://www.cnbc.com/late/{index}.html") for i in range(3)]
            if feed_url == crawler.RSS_FEEDS[0]["url"] else []
        )
        crawler.crawl_news_list(max_pages=1)

    warnings = [r for r in caplog.records if "cnbc.com" in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING


def test_성공_직후_실패_수가_임계_미만이면_WARNING이_나지_않는다(caplog):
    threshold = GlobalNewsCrawler.DETAIL_WARN_AFTER
    items = [item(i) for i in range(threshold + 2)]
    body = "Body text. " * 40
    # 최신순이므로 index 가 큰 쪽이 먼저 시도된다: 실패 2 → 성공 → 실패 threshold-1
    crawler, _ = make_crawler(
        items, bodies={CNBC.format(index=threshold - 1): body}, detail_fetch_limit=threshold + 2
    )

    with caplog.at_level(logging.WARNING, logger="news_scraper.crawlers.global_news_crawler"):
        crawler.crawl_news_list(max_pages=1)

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_잘_되던_호스트가_연속_실패로_돌아서면_WARNING이_난다(caplog):
    """누적 성공이 있다고 영원히 침묵하면 9/18~10/09 주가 조회처럼 조용히 죽는다."""
    threshold = GlobalNewsCrawler.DETAIL_WARN_AFTER
    body = "Body text. " * 40
    crawler, detail = make_crawler([item(0)], bodies={CNBC.format(index=0): body})
    crawler.crawl_news_list(max_pages=1)  # 성공 1

    detail.bodies = {}
    crawler._parse_rss_feed = lambda feed_url, source, category: (
        [item(i, url="https://www.cnbc.com/later/{index}.html") for i in range(threshold)]
        if feed_url == crawler.RSS_FEEDS[0]["url"] else []
    )
    with caplog.at_level(logging.WARNING, logger="news_scraper.crawlers.global_news_crawler"):
        crawler.crawl_news_list(max_pages=1)

    assert len([r for r in caplog.records if "cnbc.com" in r.getMessage()]) == 1


def test_회로가_열려_요청이_나가지_않으면_URL을_소모하지_않고_루프를_접는다():
    """fetch_page 가 회로 열림으로 None 을 주면 «시도» 도 «실패» 도 아니다."""
    crawler, _ = make_crawler([item(i) for i in range(5)])
    sent = []

    def detail_without_request(url):
        sent.append(url)
        crawler._stats['skipped'] += 1  # fetch_page 가드가 생략했을 때의 계약
        return None

    crawler.crawl_news_detail = detail_without_request
    crawler.begin_cycle()
    crawler._breaker._state = "open"
    crawler.crawl_news_list(max_pages=1)

    assert len(sent) == 1
    assert not any(crawler._was_tried(CNBC.format(index=i)) for i in range(5))
    assert crawler._detail_failstreak["cnbc.com"] == 0


def test_본문_보강_중_예외가_나도_RSS_결과는_그대로_돌려준다(caplog):
    crawler, _ = make_crawler([item(0), item(1)])

    def boom(news_list):
        raise RuntimeError("boom")

    crawler._enrich_with_details = boom
    with caplog.at_level(logging.WARNING, logger="news_scraper.crawlers.global_news_crawler"):
        news = crawler.crawl_news_list(max_pages=1)

    assert len(news) == 2
    assert any("boom" in r.getMessage() for r in caplog.records)


def test_최신순_정렬은_시간대가_섞여도_실제_시각_기준이다():
    """문자열 정렬이면 '…T09:00:00-04:00'(=KST 22:00) 가 '…T20:00:00+09:00' 보다 앞선다."""
    a = item(0); a["published_at"] = "2026-10-12T09:00:00-04:00"   # 22:00 KST
    b = item(1); b["published_at"] = "2026-10-12T20:00:00+09:00"   # 20:00 KST
    c = item(2); c["published_at"] = "2026-10-12T21:30:00"          # naive → KST 21:30
    d = item(3); d["published_at"] = None
    crawler, detail = make_crawler([a, b, c, d], detail_fetch_limit=4)

    crawler.crawl_news_list(max_pages=1)

    assert detail.calls == [a["url"], c["url"], b["url"], d["url"]]


def test_사이클_요약에_본문_요청_결과가_실린다():
    """fetch_page 를 안 쓰던 크롤러라 요약이 비어 있었다. 이제 본문 요청 성과를 한 줄로 남긴다."""
    body = "Body text. " * 40
    crawler, _ = make_crawler([item(0), item(1)], bodies={CNBC.format(index=1): body})
    crawler.begin_cycle()

    crawler.crawl_news_list(max_pages=1)

    summary = crawler.cycle_summary()
    assert "본문 요청 2" in summary
    assert "본문 성공 1" in summary


# --------------------------------------------------------------------------
# 요청 헤더 - RSS 용 Accept 를 본문 페이지에 보내면 MarketWatch 가 401 로 답한다 (2026-10-12 실측)
# --------------------------------------------------------------------------

class RecordingSession:
    def __init__(self):
        self.calls = []
        self.headers = {}

    def get(self, url, timeout=None, **kwargs):
        self.calls.append((url, kwargs.get("headers")))

        class R:
            status_code = 500
            content = b""
        return R()


def test_세션_기본_Accept는_HTML을_받는_값이다():
    crawler = GlobalNewsCrawler()
    assert "text/html" in crawler.session.headers["Accept"]
    assert crawler.session.headers["Accept-Language"].startswith("en-US")


def test_세션에_Upgrade_Insecure_Requests_헤더가_없다():
    """MarketWatch 는 이 헤더가 있으면 401 (2026-10-12 실측 A/B)."""
    assert "Upgrade-Insecure-Requests" not in GlobalNewsCrawler().session.headers


def test_RSS_피드_요청에만_RSS용_Accept를_붙인다():
    crawler = GlobalNewsCrawler()
    crawler.session = RecordingSession()

    crawler._parse_rss_feed("https://feeds.example/rss", "cnbc", "us_market")

    (_url, headers), = crawler.session.calls
    assert "application/rss+xml" in headers["Accept"]


# --------------------------------------------------------------------------
# 본문 추출 - 문단 텍스트만 모은다 (내비게이션·광고 텍스트 제외)
# --------------------------------------------------------------------------

CNBC_HTML = (
    "<html><body><nav>Markets Tech Politics</nav>"
    "<article><p>Oil prices fell on Monday after the ceasefire. </p>"
    "<p>Brent crude dropped 2% to $61 a barrel while WTI slid to $57. </p>"
    "<p>Analysts said Korean refiners may benefit from the lower input cost. </p>"
    "<aside>Related: Top stories</aside></article></body></html>"
)

MARKETWATCH_HTML = (
    "<html><body><header>Home Personal Finance The Moneyist</header>"
    '<div id="maincontent" class="css-mk4x1h"><div class="css-nav">Latest Watchlist Markets</div>'
    "<p>(8 min) I'm frustrated with the stock market. One day my ETFs go up, the next day they crash. </p>"
    "<p>Is this a bad sign? Should I sell everything and move to bonds before the next downturn? </p>"
    "</div><footer>Copyright MarketWatch</footer></body></html>"
)


def make_detail_crawler(html):
    crawler = GlobalNewsCrawler()
    crawler.fetch_page = lambda url, **kw: BeautifulSoup(html, "lxml")
    return crawler


def test_CNBC_article의_문단만_모아_본문으로_쓴다():
    detail = make_detail_crawler(CNBC_HTML).crawl_news_detail("https://www.cnbc.com/x.html")

    body = detail["content"]
    assert body.startswith("Oil prices fell on Monday")
    assert "Korean refiners" in body
    assert "Markets Tech Politics" not in body
    assert "Related: Top stories" not in body


def test_MarketWatch_maincontent의_문단만_모은다():
    detail = make_detail_crawler(MARKETWATCH_HTML).crawl_news_detail("https://www.marketwatch.com/story/x")

    body = detail["content"]
    assert body.startswith("(8 min) I'm frustrated")
    assert "Latest Watchlist Markets" not in body
    assert "Copyright MarketWatch" not in body


def test_문단이_100자_미만이면_None을_돌려준다():
    html = '<html><body><article><p>Too short.</p></article></body></html>'
    assert make_detail_crawler(html).crawl_news_detail("https://www.cnbc.com/x.html") is None


DECOY_HTML = (
    "<html><body>"
    '<div id="content-nav"><p>Markets Economy Tech Politics Watchlist Newsletters Sign up now for our daily brief. </p>'
    "<p>Trending: five stocks to watch this week according to analysts. </p></div>"
    '<article class="promo"><p>Related story teaser that is long enough to pass a hundred characters easily, yes it is. </p></article>'
    '<div id="maincontent"><p>Oil prices fell on Monday after the ceasefire announcement rattled traders. </p>'
    "<p>Brent crude dropped 2% to $61 a barrel while WTI slid to $57 in afternoon trade. </p>"
    "<p>Analysts said Korean refiners may benefit from the lower input cost over the coming quarter. </p></div>"
    "</body></html>"
)


def test_문단이_가장_긴_컨테이너를_본문으로_고른다():
    """첫 매치가 아니라 가장 긴 문단 묶음 - 앞에 있는 내비게이션·관련기사 카드에 속지 않는다."""
    body = make_detail_crawler(DECOY_HTML).crawl_news_detail("https://www.cnbc.com/x.html")["content"]

    assert body.startswith("Oil prices fell on Monday")
    assert "Sign up now" not in body
    assert "Related story teaser" not in body


def test_id_정규식은_정확히_일치하는_id만_받는다():
    rx = GlobalNewsCrawler._BODY_ID_RE
    assert rx.match("maincontent") and rx.match("main-content") and rx.match("article-body")
    assert not rx.match("content-nav") and not rx.match("articleList") and not rx.match("story-sidebar")


def test_본문_요청은_재시도_1회로_보낸다():
    """상세 요청 20건이 재시도 3회면 60건이 된다 - 상한의 뜻을 지킨다."""
    crawler = GlobalNewsCrawler()
    seen = {}
    crawler.fetch_page = lambda url, **kw: seen.update(kw)

    crawler.crawl_news_detail("https://www.cnbc.com/x.html")

    assert seen.get("retries") == 1
