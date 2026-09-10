"""BaseCrawler.fetch_page 의 가드 통합 테스트.

네트워크·sleep 없이 돈다. session 은 가짜로 갈아끼우고 sleep 은 기록만 한다.
"""
import logging
from typing import List, Optional

import pytest
import requests

from news_scraper.base_crawler import BaseCrawler

HTML = "<html><body><p>한글 본문</p></body></html>"


class FakeResponse:
    def __init__(self, status_code: int = 200, body: str = HTML):
        self.status_code = status_code
        self.content = body.encode("utf-8")
        self.encoding = "utf-8"
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.exceptions.HTTPError(
                f"{self.status_code} Client Error", response=self
            )
            raise error


class FakeSession:
    """호출된 URL 을 기록하고, 미리 정해둔 상태코드를 순서대로 돌려준다."""

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.requested: List[str] = []
        self.headers = {}

    def close(self):
        pass

    def get(self, url, timeout=None, **kwargs):
        self.requested.append(url)
        status = self._statuses.pop(0) if self._statuses else 200
        if isinstance(status, Exception):
            raise status
        return FakeResponse(status)


class StubCrawler(BaseCrawler):
    """추상 메서드만 채운 최소 크롤러."""

    def crawl_news_list(self, max_pages: int = 5):
        return []

    def crawl_news_detail(self, url: str):
        return None


@pytest.fixture
def sleeps(monkeypatch) -> List[float]:
    """실제로 자지 않고, 잠들려던 시간만 모아둔다."""
    recorded: List[float] = []
    monkeypatch.setattr(
        "news_scraper.base_crawler.time.sleep", lambda s: recorded.append(s)
    )
    return recorded


def make_crawler(statuses, **kwargs) -> StubCrawler:
    crawler = StubCrawler("hankyung", **kwargs)
    crawler.session = FakeSession(statuses)
    return crawler


# --------------------------------------------------------------------------
# 상태코드별 재시도 정책
# --------------------------------------------------------------------------

def test_403은_재시도하지_않고_한_번만_요청한다(sleeps):
    crawler = make_crawler([403, 403, 403])

    assert crawler.fetch_page("https://www.hankyung.com/premium9/0101003") is None
    assert len(crawler.session.requested) == 1


def test_404도_재시도하지_않는다(sleeps):
    crawler = make_crawler([404, 404, 404])

    crawler.fetch_page("https://www.hankyung.com/article/none")

    assert len(crawler.session.requested) == 1


def test_429는_백오프하며_재시도한다(sleeps):
    crawler = make_crawler([429, 429, 200])

    assert crawler.fetch_page("https://www.hankyung.com/economy?page=1") is not None
    assert len(crawler.session.requested) == 3


def test_5xx도_재시도한다(sleeps):
    crawler = make_crawler([503, 200])

    assert crawler.fetch_page("https://www.hankyung.com/economy?page=1") is not None
    assert len(crawler.session.requested) == 2


def test_성공하면_파싱된_soup을_돌려준다(sleeps):
    crawler = make_crawler([200])

    soup = crawler.fetch_page("https://www.hankyung.com/economy?page=1")

    assert soup is not None
    assert "한글 본문" in soup.get_text()


# --------------------------------------------------------------------------
# 실패 URL 캐시 - 영구 실패한 URL 은 다시 두드리지 않는다
# --------------------------------------------------------------------------

def test_403난_URL은_다음_호출에서_요청조차_나가지_않는다(sleeps):
    """premium9 처럼 목록마다 다시 나타나는 유료 기사 링크를 끊는 장치."""
    crawler = make_crawler([403, 200])
    url = "https://www.hankyung.com/premium9/0101003"
    crawler.fetch_page(url)

    crawler.fetch_page(url)

    assert crawler.session.requested == [url]


def test_403난_URL이라도_다른_URL은_정상_요청된다(sleeps):
    crawler = make_crawler([403, 200])
    crawler.fetch_page("https://www.hankyung.com/premium9/0101003")

    result = crawler.fetch_page("https://www.hankyung.com/economy?page=1")

    assert result is not None


def test_429는_실패_URL_캐시에_담기지_않는다(sleeps):
    """일시적 제한이라 영구 차단하면 안 된다."""
    crawler = make_crawler([429, 429, 429, 200])
    url = "https://www.hankyung.com/economy?page=1"
    crawler.fetch_page(url)

    assert crawler.fetch_page(url) is not None


# --------------------------------------------------------------------------
# 회로 차단기 - 연속 실패가 쌓이면 남은 요청을 즉시 포기한다
# --------------------------------------------------------------------------

def test_연속_실패가_임계에_닿으면_이후_요청이_나가지_않는다(sleeps):
    crawler = make_crawler([403] * 10, failure_threshold=3)
    for i in range(3):
        crawler.fetch_page(f"https://www.hankyung.com/premium9/{i}")
    before = len(crawler.session.requested)

    crawler.fetch_page("https://www.hankyung.com/economy?page=1")

    assert len(crawler.session.requested) == before == 3


def test_중간에_성공하면_회로가_열리지_않는다(sleeps):
    """부분적으로만 막힌 소스의 정상 수집분을 죽이지 않는다."""
    crawler = make_crawler([403, 403, 200, 403, 403, 200], failure_threshold=3)

    for i in range(6):
        crawler.fetch_page(f"https://www.hankyung.com/a/{i}")

    assert len(crawler.session.requested) == 6


def test_회로가_열려도_다음_사이클에서_초기화된다(sleeps):
    """사이클 경계에서 새 기회를 준다 - 쿨다운을 기다리며 소스를 통째로 잃지 않게."""
    crawler = make_crawler([403] * 20, failure_threshold=3)
    for i in range(4):
        crawler.fetch_page(f"https://www.hankyung.com/premium9/{i}")

    crawler.begin_cycle()
    crawler.fetch_page("https://www.hankyung.com/economy?page=1")

    assert crawler.session.requested[-1] == "https://www.hankyung.com/economy?page=1"


# --------------------------------------------------------------------------
# 적응형 딜레이 - 429 를 맞으면 물러선다
# --------------------------------------------------------------------------

def test_429를_맞으면_다음_요청_간격이_늘어난다(sleeps):
    crawler = make_crawler([200])
    before = crawler.request_delay()

    crawler.fetch_page("https://www.hankyung.com/e?page=1")
    crawler.session = FakeSession([429, 429, 429])
    crawler.fetch_page("https://www.hankyung.com/e?page=2")

    assert crawler.request_delay() > before


def test_요청_간격은_상한을_넘지_않는다(sleeps):
    crawler = make_crawler([429] * 60, max_request_delay=8.0)

    for i in range(20):
        crawler.fetch_page(f"https://www.hankyung.com/e?page={i}")

    assert crawler.request_delay() <= 8.0


# --------------------------------------------------------------------------
# 시간 예산 - 스케줄러 타임아웃에 걸리기 «전에» 스스로 접는다
# --------------------------------------------------------------------------

def test_예산을_다_쓰면_요청이_나가지_않는다(sleeps):
    clock = iter([0.0, 0.0, 500.0, 500.0, 500.0, 500.0])
    crawler = make_crawler([200] * 5, time_budget=240, clock=lambda: next(clock))
    crawler.begin_cycle()
    crawler.fetch_page("https://www.hankyung.com/e?page=1")
    before = len(crawler.session.requested)

    crawler.fetch_page("https://www.hankyung.com/e?page=2")

    assert len(crawler.session.requested) == before


def test_예산이_남아있으면_계속_요청한다(sleeps):
    crawler = make_crawler([200] * 5, time_budget=240, clock=lambda: 0.0)
    crawler.begin_cycle()

    crawler.fetch_page("https://www.hankyung.com/e?page=1")
    crawler.fetch_page("https://www.hankyung.com/e?page=2")

    assert len(crawler.session.requested) == 2


# --------------------------------------------------------------------------
# 사이클 요약 - 143만 줄을 grep 하지 않고 «어디가 아픈지» 한 줄로 본다
# --------------------------------------------------------------------------

def test_사이클_요약에_요청_성공_상태코드별_건수가_담긴다(sleeps):
    crawler = make_crawler([200, 403, 429, 429, 429])
    crawler.begin_cycle()
    crawler.fetch_page("https://www.hankyung.com/e?page=1")
    crawler.fetch_page("https://www.hankyung.com/premium9/1")
    crawler.fetch_page("https://www.hankyung.com/e?page=2")

    summary = crawler.cycle_summary()

    assert "요청 3" in summary
    assert "성공 1" in summary
    assert "403 1" in summary
    assert "429 1" in summary


def test_사이클_요약에_건너뛴_요청_수가_담긴다(sleeps):
    crawler = make_crawler([403, 200])
    crawler.begin_cycle()
    url = "https://www.hankyung.com/premium9/1"
    crawler.fetch_page(url)
    crawler.fetch_page(url)

    assert "생략 1" in crawler.cycle_summary()


def test_begin_cycle은_통계를_초기화한다(sleeps):
    crawler = make_crawler([200] * 4)
    crawler.begin_cycle()
    crawler.fetch_page("https://www.hankyung.com/e?page=1")
    crawler.fetch_page("https://www.hankyung.com/e?page=2")

    crawler.begin_cycle()
    crawler.fetch_page("https://www.hankyung.com/e?page=3")

    assert "요청 1" in crawler.cycle_summary()


def test_회로가_열리면_요약에_표시된다(sleeps):
    crawler = make_crawler([403] * 10, failure_threshold=2)
    crawler.begin_cycle()
    for i in range(2):
        crawler.fetch_page(f"https://www.hankyung.com/premium9/{i}")

    assert "차단기 OPEN" in crawler.cycle_summary()


# --------------------------------------------------------------------------
# 로그 볼륨 - 이 작업의 실제 목적
# --------------------------------------------------------------------------

def test_403_URL_반복_요청이_로그를_한_줄만_남긴다(sleeps, caplog):
    crawler = make_crawler([403] + [200] * 50)
    url = "https://www.hankyung.com/premium9/0101003"

    with caplog.at_level(logging.WARNING, logger="news_scraper.base_crawler"):
        for _ in range(50):
            crawler.fetch_page(url)

    assert len(caplog.records) == 1


def test_네트워크_예외도_재시도_후_포기한다(sleeps):
    boom = requests.exceptions.ConnectionError("연결 실패")
    crawler = make_crawler([boom, boom, boom])

    assert crawler.fetch_page("https://www.hankyung.com/e?page=1") is None
    assert len(crawler.session.requested) == 3


def test_fetch_page를_쓰지_않은_크롤러는_요약을_내지_않는다(sleeps):
    """dart·global_news 는 자체 HTTP/RSS 를 쓴다.
    이들에게 '요청 0 · 성공 0' 을 찍으면 «아무것도 안 했다»로 오해된다."""
    crawler = make_crawler([200])
    crawler.begin_cycle()

    assert crawler.cycle_summary() == ""


def test_생략만_있어도_요약은_나온다(sleeps):
    """요청이 0이어도 생략이 있으면 «막혀서 못 갔다»는 뜻이라 남겨야 한다."""
    crawler = make_crawler([403, 200])
    crawler.begin_cycle()
    url = "https://www.hankyung.com/premium9/1"
    crawler.fetch_page(url)
    crawler.begin_cycle()
    crawler.fetch_page(url)

    assert "생략 1" in crawler.cycle_summary()


# --------------------------------------------------------------------------
# fetch_json - JSON API 요청에도 같은 가드가 걸려야 한다
# --------------------------------------------------------------------------

class FakeJsonResponse(FakeResponse):
    def __init__(self, status_code=200, payload=None, body=None):
        text = body if body is not None else __import__("json").dumps(
            payload if payload is not None else {"articles": []}, ensure_ascii=False
        )
        super().__init__(status_code, text)
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        return __import__("json").loads(self.content.decode("utf-8"))


class FakeJsonSession(FakeSession):
    def __init__(self, responses):
        super().__init__([])
        self._responses = list(responses)
        self.params = []

    def get(self, url, timeout=None, params=None, **kwargs):
        self.requested.append(url)
        self.params.append(params)
        item = self._responses.pop(0) if self._responses else FakeJsonResponse()
        if isinstance(item, Exception):
            raise item
        return item


def make_json_crawler(responses, **kwargs) -> StubCrawler:
    crawler = StubCrawler("naver_finance", **kwargs)
    crawler.session = FakeJsonSession(responses)
    return crawler


def test_fetch_json은_파싱된_dict를_돌려준다(sleeps):
    crawler = make_json_crawler([FakeJsonResponse(payload={"articles": [{"title": "제목"}]})])

    data = crawler.fetch_json("https://stock.naver.com/api/domestic/news/list")

    assert data["articles"][0]["title"] == "제목"


def test_fetch_json은_쿼리_파라미터를_전달한다(sleeps):
    crawler = make_json_crawler([FakeJsonResponse()])

    crawler.fetch_json("https://stock.naver.com/api/x", params={"page": 2})

    assert crawler.session.params[0] == {"page": 2}


def test_fetch_json도_403이면_재시도하지_않는다(sleeps):
    crawler = make_json_crawler([FakeJsonResponse(403), FakeJsonResponse(403)])

    assert crawler.fetch_json("https://stock.naver.com/api/x") is None
    assert len(crawler.session.requested) == 1


def test_fetch_json도_실패_URL_캐시를_공유한다(sleeps):
    crawler = make_json_crawler([FakeJsonResponse(404), FakeJsonResponse()])
    url = "https://stock.naver.com/api/x"
    crawler.fetch_json(url)

    crawler.fetch_json(url)

    assert len(crawler.session.requested) == 1


def test_fetch_json도_429면_백오프_재시도한다(sleeps):
    crawler = make_json_crawler(
        [FakeJsonResponse(429), FakeJsonResponse(payload={"ok": 1})]
    )

    assert crawler.fetch_json("https://stock.naver.com/api/x") == {"ok": 1}
    assert len(crawler.session.requested) == 2


def test_fetch_json도_사이클_통계에_잡힌다(sleeps):
    crawler = make_json_crawler([FakeJsonResponse()])
    crawler.begin_cycle()

    crawler.fetch_json("https://stock.naver.com/api/x")

    assert "요청 1 · 성공 1" in crawler.cycle_summary()


def test_JSON이_아니면_None을_돌려준다(sleeps):
    """API 가 바뀌어 HTML 오류 페이지를 주면 조용히 통과시키면 안 된다."""
    crawler = make_json_crawler([FakeJsonResponse(body="<html>오류</html>")])

    assert crawler.fetch_json("https://stock.naver.com/api/x") is None


def test_JSON_파싱_실패도_사이클_요약에_잡힌다(sleeps):
    crawler = make_json_crawler([FakeJsonResponse(body="<html>오류</html>")])
    crawler.begin_cycle()

    crawler.fetch_json("https://stock.naver.com/api/x")

    assert "응답형식오류 1" in crawler.cycle_summary()
