"""
네이버 금융 뉴스 크롤러

finance.naver.com/news/news_list.naver 는 stock.naver.com SPA 로 리다이렉트되어
HTML 에 뉴스가 «하나도» 없다 (링크 36개가 전부 네비게이션). 그래서 이 크롤러는
그 SPA 가 쓰는 내부 JSON API 를 직접 호출한다.

API 응답은 HTML 스크래핑보다 정확하다: 발행시각·제목·요약이 구조화되어 있어
제목 자르기나 날짜 추정 같은 휴리스틱이 필요 없다.

비공식 내부 API 이므로 예고 없이 바뀔 수 있다. 스키마가 어긋나거나 한 건도
못 모으면 «조용히 0건» 대신 경고를 남긴다 - 구 HTML 크롤러가 200 OK 를 받으며
몇 달간 0건을 반환하던 실패를 반복하지 않기 위해서다.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from ..base_crawler import BaseCrawler

logger = logging.getLogger(__name__)


class NaverFinanceCrawler(BaseCrawler):
    """네이버 금융 뉴스 크롤러 (stock.naver.com 내부 JSON API 사용)"""

    LIST_API = "https://stock.naver.com/api/domestic/news/list"
    FOCUS_API = "https://stock.naver.com/api/domestic/news/focus"
    ARTICLE_URL = "https://n.news.naver.com/mnews/article/{office_id}/{article_id}"
    REFERER = "https://stock.naver.com/news/flashnews"

    # 실시간 속보(전체) + 국내증시 핵심 섹션.
    # 403(해외증시)·406(공시)·429(환율)은 글로벌/DART 크롤러와 겹쳐 제외한다.
    SECTIONS = [
        {"api": "list", "key": "FLASHNEWS", "name": "실시간속보"},
        {"api": "focus", "key": 401, "name": "시황·전망"},
        {"api": "focus", "key": 402, "name": "기업·종목분석"},
        {"api": "focus", "key": 404, "name": "채권·선물"},
    ]

    PAGE_SIZE = 100
    DEFAULT_DETAIL_FETCH_LIMIT = 30

    def __init__(self, detail_fetch_limit: int = DEFAULT_DETAIL_FETCH_LIMIT, **kwargs):
        """
        Args:
            detail_fetch_limit: 전문을 추가로 받아올 최신 기사 수.
                                나머지는 API 요약(subcontent)을 본문으로 쓴다.
        """
        super().__init__("naver_finance", **kwargs)
        self.detail_fetch_limit = detail_fetch_limit
        self.session.headers.update({
            "Accept": "application/json",
            "Referer": self.REFERER,
        })

    # ------------------------------------------------------------------ 목록
    def crawl_news_list(self, max_pages: int = 5) -> List[Dict]:
        """섹션별로 JSON API 를 훑어 뉴스 목록을 모은다."""
        date = datetime.now().strftime("%Y%m%d")
        collected: Dict[str, Dict] = {}  # articleId -> news

        for section in self.SECTIONS:
            collected.update(self._crawl_section(section, max_pages, date))

        news_list = list(collected.values())
        if not news_list:
            # 구 HTML 크롤러는 여기서 조용히 빈 리스트를 돌려주며 몇 달을 보냈다.
            logger.warning(
                f"[{self.source_name}] 0건 수집 - API 응답 형식이 바뀌었을 수 있다"
            )
            return []

        self._enrich_with_bodies(news_list)
        logger.info(f"[{self.source_name}] 목록 수집 완료: {len(news_list)}건")
        return news_list

    def _crawl_section(self, section: Dict, max_pages: int, date: str) -> Dict[str, Dict]:
        """한 섹션을 페이지 단위로 훑는다.

        page 를 계속 늘려도 같은 데이터가 돌아오는 구간이 있어(실측: page=10 과
        page=50 이 동일), 새 기사가 하나도 없는 페이지를 만나면 멈춘다.
        """
        found: Dict[str, Dict] = {}

        for page in range(1, max_pages + 1):
            articles = self._fetch_articles(section, page, date)
            if not articles:
                break

            fresh = 0
            for raw in articles:
                news = self._to_news(raw, section["name"])
                if news is None:
                    continue
                if news["_article_id"] in found:
                    continue
                found[news["_article_id"]] = news
                fresh += 1

            if fresh == 0:
                # 이 페이지가 통째로 중복이다 - 더 넘겨도 새 기사는 없다.
                break

        return found

    def _fetch_articles(self, section: Dict, page: int, date: str) -> List[Dict]:
        """API 를 한 번 호출해 기사 배열을 꺼낸다."""
        if section["api"] == "list":
            url = self.LIST_API
            params = {"category": section["key"]}
        else:
            url = self.FOCUS_API
            params = {"sid": section["key"], "enableFallback": "true"}

        params.update({"page": page, "pageSize": self.PAGE_SIZE, "date": date})
        payload = self.fetch_json(url, params=params)

        if payload is None:
            # fetch_json 이 이미 경고를 남겼다 (차단·오류·비 JSON).
            return []

        if not isinstance(payload, dict) or "articles" not in payload:
            logger.warning(
                f"[{self.source_name}] 응답에 articles 키가 없다 "
                f"(섹션={section['name']}, 키={list(payload)[:5] if isinstance(payload, dict) else type(payload).__name__})"
            )
            return []

        return payload["articles"] or []

    def _to_news(self, raw: Dict, section_name: str) -> Optional[Dict]:
        """API 기사 한 건을 news 레코드로 옮긴다. 필수 필드가 없으면 None."""
        office_id = raw.get("officeId")
        article_id = raw.get("articleId")
        title = (raw.get("title") or "").strip()
        published_at = self._parse_api_datetime(raw.get("datetime"))

        if not (office_id and article_id and title and published_at):
            logger.debug(f"[{self.source_name}] 필수 필드 누락으로 건너뜀: {raw.get('articleId')}")
            return None

        url = self.ARTICLE_URL.format(office_id=office_id, article_id=article_id)
        summary = (raw.get("subcontent") or "").strip()

        return {
            "news_id": self.generate_news_id(url, title),
            "title": title,
            "content": summary,
            "published_at": published_at,
            "source": self.source_name,
            "category": section_name,
            "url": url,
            "related_stocks": self.extract_stock_codes(f"{title} {summary}"),
            "sentiment_score": None,
            # 내부용: 섹션 간 중복 제거와 본문 수집 정렬에 쓰고 저장 전에 뺀다.
            "_article_id": article_id,
        }

    @staticmethod
    def _parse_api_datetime(value: Optional[str]) -> Optional[str]:
        """'2026-09-10 23:45:09' -> ISO 형식. 형식이 다르면 None."""
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").isoformat()
        except (ValueError, TypeError):
            logger.debug(f"[naver_finance] 발행시각 형식을 모르겠다: {value!r}")
            return None

    # ------------------------------------------------------------------ 본문
    def _enrich_with_bodies(self, news_list: List[Dict]) -> None:
        """최신 N 건만 전문을 받아 본문을 채운다.

        나머지는 API 요약(~300자)을 그대로 쓴다. 사이클당 수백 건의 상세 요청은
        시간 예산을 통째로 잡아먹는다 - 구 크롤러가 정확히 그랬다.
        """
        news_list.sort(key=lambda n: n["published_at"], reverse=True)

        for news in news_list[: self.detail_fetch_limit]:
            try:
                detail = self.crawl_news_detail(news["url"])
            except Exception as e:
                logger.debug(f"[{self.source_name}] 본문 수집 오류 {news['url']}: {e}")
                continue

            body = (detail or {}).get("content") or ""
            # 전문이 요약보다 짧으면 잘린 것이다 - 요약을 지키는 편이 낫다.
            if len(body) > len(news["content"]):
                news["content"] = body

        for news in news_list:
            news.pop("_article_id", None)

    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """기사 페이지에서 본문을 뽑는다."""
        soup = self.fetch_page(url)
        if soup is None:
            return None

        body = soup.select_one("#dic_area") or soup.select_one("#newsct_article")
        if body is None:
            logger.debug(f"[{self.source_name}] 본문 영역을 못 찾음: {url}")
            return None

        return {"content": body.get_text(separator=" ", strip=True)}
