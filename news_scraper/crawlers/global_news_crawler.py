"""
글로벌 뉴스 크롤러
RSS 피드 기반 해외 금융 뉴스 수집 (Reuters, CNBC, MarketWatch, Investing.com)
한국 시장에 영향을 미치는 글로벌 뉴스를 수집하여 KOSPI/KOSDAQ 지수 예측에 활용
"""

import re
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Set
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import logging

from ..base_crawler import BaseCrawler

logger = logging.getLogger(__name__)


# 한국 시장에 영향을 미치는 글로벌 키워드
KOREA_IMPACT_KEYWORDS = [
    # 직접적 한국 관련
    'korea', 'korean', 'kospi', 'kosdaq', 'samsung', 'hyundai', 'sk hynix',
    'lg', 'kia', 'posco', 'naver', 'kakao', 'seoul',
    # 반도체/기술
    'semiconductor', 'chip', 'memory', 'dram', 'nand', 'ai chip',
    'nvidia', 'tsmc', 'intel', 'amd', 'artificial intelligence',
    # 미국 시장 (KOSPI 선행 지표)
    'wall street', 'dow jones', 'nasdaq', 'sp 500', 's&p 500',
    'fed', 'federal reserve', 'interest rate', 'rate cut', 'rate hike',
    'treasury', 'bond yield', 'inflation', 'cpi', 'ppi', 'jobs report',
    'nonfarm', 'unemployment', 'gdp',
    # 중국 (한국 최대 교역국)
    'china', 'chinese', 'beijing', 'shanghai', 'hang seng', 'csi',
    'pboc', 'yuan', 'renminbi',
    # 무역/관세
    'tariff', 'trade war', 'trade deal', 'sanctions', 'export control',
    'import duty', 'trade deficit', 'trade surplus', 'protectionism',
    # 원자재/에너지
    'oil', 'crude', 'brent', 'wti', 'opec', 'natural gas',
    'copper', 'lithium', 'battery', 'ev', 'electric vehicle',
    # 환율
    'dollar', 'won', 'yen', 'euro', 'currency', 'forex', 'exchange rate',
    # 글로벌 리스크
    'recession', 'crisis', 'crash', 'bear market', 'bull market',
    'volatility', 'vix', 'risk', 'geopolitical', 'war', 'conflict',
    'pandemic', 'supply chain', 'disruption',
    # 아시아 시장
    'asia', 'asian', 'nikkei', 'topix', 'japan', 'taiwan',
    # 글로벌 경제
    'global economy', 'world economy', 'imf', 'world bank',
    'central bank', 'monetary policy', 'quantitative',
    # 기업/산업
    'earnings', 'revenue', 'profit', 'ipo', 'merger', 'acquisition',
    'tech', 'technology', 'biotech', 'pharmaceutical',
    'shipbuilding', 'steel', 'automotive', 'display',
]


class GlobalNewsCrawler(BaseCrawler):
    """글로벌 뉴스 RSS 크롤러"""

    # RSS 피드 소스 목록
    RSS_FEEDS = [
        # Reuters
        {
            'url': 'https://news.google.com/rss/search?q=stock+market+OR+wall+street+OR+federal+reserve+OR+tariff+OR+semiconductor&hl=en-US&gl=US&ceid=US:en',
            'source': 'google_news_finance',
            'category': 'global_market',
            'name': 'Google News Finance',
        },
        # 아시아 시장 관련
        {
            'url': 'https://news.google.com/rss/search?q=asia+stock+market+OR+kospi+OR+korea+economy+OR+samsung+semiconductor&hl=en-US&gl=US&ceid=US:en',
            'source': 'google_news_asia',
            'category': 'asia_market',
            'name': 'Google News Asia',
        },
        # 무역/관세 관련 (현 정세 반영)
        {
            'url': 'https://news.google.com/rss/search?q=trade+war+OR+tariff+OR+sanctions+OR+china+trade+OR+korea+trade&hl=en-US&gl=US&ceid=US:en',
            'source': 'google_news_trade',
            'category': 'trade_policy',
            'name': 'Google News Trade',
        },
        # 반도체/기술 산업
        {
            'url': 'https://news.google.com/rss/search?q=semiconductor+chip+OR+nvidia+OR+AI+chip+OR+DRAM+OR+memory+chip&hl=en-US&gl=US&ceid=US:en',
            'source': 'google_news_tech',
            'category': 'technology',
            'name': 'Google News Tech',
        },
        # CNBC
        {
            'url': 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114',
            'source': 'cnbc',
            'category': 'us_market',
            'name': 'CNBC Finance',
        },
        # MarketWatch
        {
            'url': 'https://feeds.marketwatch.com/marketwatch/topstories/',
            'source': 'marketwatch',
            'category': 'global_market',
            'name': 'MarketWatch Top Stories',
        },
        # Investing.com
        {
            'url': 'https://www.investing.com/rss/news.rss',
            'source': 'investing_com',
            'category': 'global_market',
            'name': 'Investing.com News',
        },
    ]

    # ------------------------------------------------------------------ 본문 보강
    # RSS 는 요약(또는 빈 문자열)만 준다. 2026-10-12 실측: 최근 14일 cnbc·marketwatch·
    # investing_com 은 본문 200자 미만이 95~100%. 상세 요청으로 채우되 한국경제가
    # 2026-09-11 에 하루 720건 요청으로 Cloudflare 24시간 차단을 당한 전례가 있어
    # 상한을 두 겹으로 둔다: ① 사이클당 N 건 ② 한 번 시도한 URL 은 다시 두드리지 않음.
    # 해외 신규 뉴스는 하루 100~380건, 그중 직접 주소는 ~150건. 본문 요청은 재시도 없이
    # (retries=1) 보내므로 HTTP 요청 수도 그 안에 머문다.
    # 프로세스 시작 뒤 첫 사이클은 «예열» - 피드에 이미 있던 기사는 거의 모두 요약으로
    # 저장돼 있고, 본문을 받으면 UPSERT 「더 긴 쪽」 규칙으로 기존 행이 덮어써진다.
    # 과거 행은 그대로 둔다는 약속(2026-10-12)에 따라 그 URL 들은 시도한 것으로만 기록한다.
    DEFAULT_DETAIL_FETCH_LIMIT = 20
    # 요약이 이미 이 길이면 본문 요청을 생략한다 (DB 실측의 «본문 부족» 기준과 같다).
    DETAIL_MIN_CONTENT = 200
    # 본문 페이지로 바로 갈 수 있는 호스트. news.google.com 은 JS 리다이렉트 중계라 제외.
    # investing.com 은 2026-10-12 실측 Cloudflare 403 - 막힌 문을 두드리면 차단만 부른다.
    # marketwatch.com 은 유료벽이라 도입부 문단(~500자)만 온다. 요약(~125자)보다는 길다.
    DETAIL_HOSTS = ('cnbc.com', 'marketwatch.com')
    # RSS 피드 요청에만 붙이는 Accept. 본문 페이지에 이 값을 보내면 MarketWatch 가
    # 401 로 답했다 (2026-10-12 실측) - 세션 기본값은 BaseCrawler 의 HTML 용으로 둔다.
    RSS_ACCEPT = 'application/rss+xml, application/xml, text/xml, */*'
    # 본문으로 인정하는 최소 문단 합계 길이
    DETAIL_MIN_BODY = 100
    # 시도한 URL 기억의 상한 - 넘으면 오래된 것부터 밀어낸다 (하루 ~150건이라 수십 일 분량).
    DETAIL_TRIED_CAP = 5000
    # 한 호스트가 이만큼 «연속» 실패하면 WARNING 한 번. 성공하면 다시 셀 수 있다
    # (누적 성공이 있다고 영원히 침묵하면 9/18~10/09 주가 조회처럼 조용히 죽는다).
    DETAIL_WARN_AFTER = 10

    def __init__(self, detail_fetch_limit: int = DEFAULT_DETAIL_FETCH_LIMIT, **kwargs):
        """
        Args:
            detail_fetch_limit: 사이클당 본문을 추가로 받아올 최대 기사 수.
                                0 이면 본문 요청을 하지 않는다.
            **kwargs:           BaseCrawler 인자 (time_budget·clock 등, 테스트 주입용)
        """
        super().__init__("global_news", **kwargs)
        self.detail_fetch_limit = detail_fetch_limit
        self._warmed_up = False
        self._detail_tried: "OrderedDict[str, None]" = OrderedDict()  # 삽입순 → FIFO 퇴출
        self._detail_failstreak: Counter = Counter()  # host -> 연속 실패 수 (성공 시 0)
        self._detail_warned: Set[str] = set()
        self._cycle_detail = {'requests': 0, 'success': 0}
        # 영문 사이트 - Accept 는 BaseCrawler 의 HTML 용 그대로, RSS 요청만 RSS_ACCEPT 를 덧붙인다
        self.session.headers.update({'Accept-Language': 'en-US,en;q=0.9'})
        # MarketWatch 는 이 헤더가 있으면 401 로 답한다 (2026-10-12 헤더 하나씩 빼며 실측).
        self.session.headers.pop('Upgrade-Insecure-Requests', None)

    def begin_cycle(self) -> None:
        super().begin_cycle()
        self._cycle_detail = {'requests': 0, 'success': 0}

    def cycle_summary(self) -> str:
        """기본 요약(fetch_page 통계) 뒤에 본문 요청 성과를 덧붙인다."""
        base = super().cycle_summary()
        detail = self._cycle_detail
        if not detail['requests']:
            return base
        extra = f"본문 요청 {detail['requests']} · 본문 성공 {detail['success']}"
        return f"{base} · {extra}" if base else f"[{self.source_name}] {extra}"

    def _parse_rss_date(self, date_str: str) -> str:
        """RSS 날짜 문자열을 ISO 형식으로 변환"""
        if not date_str:
            return datetime.now().isoformat()

        try:
            # RFC 2822 형식 (RSS 표준): "Mon, 15 Jan 2024 14:30:00 GMT"
            dt = parsedate_to_datetime(date_str)
            return dt.isoformat()
        except Exception:
            pass

        try:
            # ISO 형식
            if 'T' in date_str:
                return date_str.split('.')[0]
        except Exception:
            pass

        return datetime.now().isoformat()

    def _calculate_korea_relevance(self, title: str, content: str) -> float:
        """한국 시장 관련도 점수 계산 (0.0 ~ 1.0)"""
        text = f"{title} {content}".lower()
        matched = sum(1 for kw in KOREA_IMPACT_KEYWORDS if kw in text)
        # 최대 10개 매칭으로 1.0
        return min(1.0, matched / 10.0)

    def _parse_rss_feed(self, feed_url: str, source: str, category: str) -> List[Dict]:
        """단일 RSS 피드 파싱"""
        news_list = []

        try:
            response = self.session.get(feed_url, timeout=15, headers={'Accept': self.RSS_ACCEPT})
            if response.status_code != 200:
                logger.warning(f"[{source}] RSS 피드 응답 오류: {response.status_code}")
                return []

            # XML 파싱
            root = ET.fromstring(response.content)

            # RSS 2.0 네임스페이스 처리
            ns = {}
            if root.tag.startswith('{'):
                ns_uri = root.tag.split('}')[0].strip('{')
                ns = {'ns': ns_uri}

            # channel > item 또는 entry (Atom) 찾기
            items = root.findall('.//item')
            if not items:
                items = root.findall('.//{http://www.w3.org/2005/Atom}entry')

            for item in items[:30]:  # 피드당 최대 30개
                try:
                    # 제목
                    title_elem = item.find('title')
                    if title_elem is None:
                        title_elem = item.find('{http://www.w3.org/2005/Atom}title')
                    title = (title_elem.text or '').strip() if title_elem is not None else ''

                    if not title or len(title) < 10:
                        continue

                    # 링크
                    link_elem = item.find('link')
                    if link_elem is None:
                        link_elem = item.find('{http://www.w3.org/2005/Atom}link')
                    if link_elem is not None:
                        url = link_elem.text or link_elem.get('href', '')
                    else:
                        url = ''
                    url = url.strip()

                    if not url:
                        continue

                    # 날짜
                    pub_date_elem = item.find('pubDate')
                    if pub_date_elem is None:
                        pub_date_elem = item.find('{http://www.w3.org/2005/Atom}published')
                    if pub_date_elem is None:
                        pub_date_elem = item.find('{http://www.w3.org/2005/Atom}updated')
                    date_str = (pub_date_elem.text or '').strip() if pub_date_elem is not None else ''
                    published_at = self._parse_rss_date(date_str)

                    # 설명/본문
                    desc_elem = item.find('description')
                    if desc_elem is None:
                        desc_elem = item.find('{http://www.w3.org/2005/Atom}summary')
                    if desc_elem is None:
                        desc_elem = item.find('{http://www.w3.org/2005/Atom}content')
                    raw_desc = (desc_elem.text or '').strip() if desc_elem is not None else ''

                    # HTML 태그 제거
                    content = re.sub(r'<[^>]+>', '', raw_desc).strip()
                    content = re.sub(r'\s+', ' ', content)

                    # 한국 시장 관련도 계산
                    korea_relevance = self._calculate_korea_relevance(title, content)

                    news_data = {
                        'news_id': self.generate_news_id(url, title),
                        'title': title,
                        'content': content,
                        'published_at': published_at,
                        'source': source,
                        'category': category,
                        'url': url,
                        'related_stocks': '',  # 외국 뉴스는 종목 코드 없음
                        'sentiment_score': None,
                        'korea_relevance': korea_relevance,
                        'language': 'en',
                    }

                    news_list.append(news_data)

                except Exception as e:
                    logger.debug(f"[{source}] RSS 항목 파싱 오류: {e}")
                    continue

            logger.info(f"[{source}] RSS 피드 파싱 완료: {len(news_list)}건")

        except ET.ParseError as e:
            logger.warning(f"[{source}] XML 파싱 오류: {e}")
        except Exception as e:
            logger.error(f"[{source}] RSS 피드 수집 오류: {e}")

        return news_list

    def crawl_news_list(self, max_pages: int = 3) -> List[Dict]:
        """모든 RSS 피드에서 뉴스 수집"""
        all_news = []
        seen_urls = set()

        for feed in self.RSS_FEEDS:
            try:
                news_list = self._parse_rss_feed(
                    feed_url=feed['url'],
                    source=feed['source'],
                    category=feed['category'],
                )

                # URL 중복 제거
                for news in news_list:
                    if news['url'] not in seen_urls:
                        seen_urls.add(news['url'])
                        all_news.append(news)

            except Exception as e:
                logger.error(f"[{feed['source']}] 피드 수집 실패: {e}")
                continue

        # 한국 관련도 0.1 이상인 뉴스만 유지 (노이즈 필터링)
        filtered = [n for n in all_news if n.get('korea_relevance', 0) >= 0.1]

        logger.info(f"[global_news] 전체 수집: {len(all_news)}건, 한국 관련 필터링 후: {len(filtered)}건")

        # 저장될 기사에만 본문 요청을 쓴다 - 필터에 걸린 기사에 쓰면 상한만 갉아먹는다.
        # 본문 보강이 터져도 RSS 결과는 돌려준다 - 보강은 덤이고 수집이 본체다.
        try:
            self._enrich_with_details(filtered)
        except Exception as e:
            logger.warning(f"[global_news] 본문 보강 실패, 요약만 저장: {e}", exc_info=True)
        return filtered

    # ------------------------------------------------------------------ 본문 보강
    @classmethod
    def _detail_host(cls, url: str) -> Optional[str]:
        """본문 요청을 보낼 수 있는 호스트면 그 이름을, 아니면 None."""
        try:
            netloc = urlsplit(url).hostname or ''
        except ValueError:
            return None
        netloc = netloc.lower()
        for host in cls.DETAIL_HOSTS:
            if netloc == host or netloc.endswith('.' + host):
                return host
        return None

    @staticmethod
    def _tried_key(url: str) -> str:
        """같은 기사가 추적 쿼리만 다르게 와도 한 번만 시도하도록 쿼리·프래그먼트를 뗀다."""
        try:
            return urlsplit(url)._replace(query='', fragment='').geturl()
        except ValueError:
            return url

    def _remember_tried(self, url: str) -> None:
        key = self._tried_key(url)
        self._detail_tried[key] = None
        self._detail_tried.move_to_end(key)
        while len(self._detail_tried) > self.DETAIL_TRIED_CAP:
            self._detail_tried.popitem(last=False)

    def _forget_tried(self, url: str) -> None:
        self._detail_tried.pop(self._tried_key(url), None)

    def _was_tried(self, url: str) -> bool:
        return self._tried_key(url) in self._detail_tried

    def _wants_detail(self, news: Dict) -> bool:
        if len(news.get('content') or '') >= self.DETAIL_MIN_CONTENT:
            return False
        if self._was_tried(news['url']):
            return False
        return self._detail_host(news['url']) is not None

    _KST = timezone(timedelta(hours=9))

    @classmethod
    def _recency_key(cls, news: Dict) -> datetime:
        """최신순 정렬 키. 시간대가 섞인 ISO 문자열을 문자열로 비교하면 몇 시간씩 틀린다."""
        raw = news.get('published_at') or ''
        try:
            dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except (ValueError, TypeError, AttributeError):
            return datetime.min.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=cls._KST)  # datetime.now() 폴백은 로컬(KST)
        return dt

    def _enrich_with_details(self, news_list: List[Dict]) -> None:
        """최신순으로 상한만큼 본문을 받아 요약보다 길면 바꿔 넣는다. 실패해도 요약은 남는다."""
        if self.detail_fetch_limit <= 0:
            return
        candidates = sorted(
            (n for n in news_list if self._wants_detail(n)),
            key=self._recency_key, reverse=True,
        )
        if not self._warmed_up:
            # 예열: 지금 피드에 있는 기사는 저장돼 있던 것으로 보고 요청 없이 기록만 한다.
            for news in candidates:
                self._remember_tried(news['url'])
            self._warmed_up = True
            logger.info(f"[global_news] 예열 - 피드에 있던 {len(candidates)}건은 본문 요청 없이 기록")
            return
        fetched = 0
        for news in candidates:
            if fetched >= self.detail_fetch_limit:
                break
            if self.budget_exhausted():
                logger.info(f"[global_news] 시간 예산 소진 - 본문 요청 {fetched}건에서 접는다")
                break
            url = news['url']
            if self._was_tried(url):
                continue  # 같은 기사가 추적 쿼리만 다르게 이 사이클에 두 번 왔다
            host = self._detail_host(url)
            self._remember_tried(url)
            fetched += 1
            skipped_before = self._stats['skipped']
            try:
                detail = self.crawl_news_detail(url)
            except Exception as e:  # 본문 하나 때문에 사이클을 잃지 않는다
                logger.debug(f"[global_news] 본문 요청 예외: {url} - {e}")
                detail = None
            if self._stats['skipped'] > skipped_before:
                # fetch_page 가드가 요청을 내보내지 않았다 (회로 열림·실패 URL 캐시·예산).
                # 시도도 실패도 아니다.
                self._forget_tried(url)
                if self._breaker.state == "open":
                    logger.info("[global_news] 회로 열림 - 남은 본문 요청을 접는다")
                    break
                continue
            self._cycle_detail['requests'] += 1
            body = (detail or {}).get('content') or ''
            if len(body) > len(news.get('content') or ''):
                news['content'] = body
                self._cycle_detail['success'] += 1
                self._detail_failstreak[host] = 0
                self._detail_warned.discard(host)
            else:
                self._detail_failstreak[host] += 1
                self._warn_if_host_dead(host)

    def _warn_if_host_dead(self, host: str) -> None:
        """호스트가 N 번 연속 실패하면 한 번 경고한다 - 조용히 무력화되지 않게."""
        if host in self._detail_warned:
            return
        if self._detail_failstreak[host] >= self.DETAIL_WARN_AFTER:
            self._detail_warned.add(host)
            logger.warning(
                f"[global_news] {host} 본문 요청 {self._detail_failstreak[host]}건 연속 실패 - "
                f"차단 또는 페이지 구조 변경 의심. 요약만 저장되고 있다"
            )

    # 본문 컨테이너 후보. id 는 정확히 일치해야 한다 - '^content' 식이면 content-nav 가 걸린다.
    _BODY_CLASS_RE = re.compile(r'article.?body|story.?body|articlebody', re.IGNORECASE)
    _BODY_ID_RE = re.compile(
        r'^(maincontent|main-content|article|article-body|story|story-body|content)$', re.IGNORECASE
    )
    _NOISE_TAGS = ['script', 'style', 'iframe', 'ins', 'aside', 'nav', 'figure']

    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """기사 본문 페이지에서 문단(<p>) 텍스트만 모은다.

        _enrich_with_details 가 상한 안에서 부른다. 컨테이너 전체 텍스트를 쓰면
        내비게이션·광고 문구가 섞이므로 (MarketWatch #maincontent 실측) 문단만 잇고,
        후보 중 «첫 매치» 가 아니라 «문단이 가장 긴» 것을 고른다 - 앞에 놓인
        관련기사 카드나 메뉴 컨테이너에 속지 않도록.
        재시도는 1회: 상한 20건이 재시도 3회면 HTTP 60건이 된다.
        """
        try:
            soup = self.fetch_page(url, retries=1)
            if not soup:
                return None

            containers = (
                soup.find_all('article')
                + soup.find_all('div', class_=self._BODY_CLASS_RE)
                + soup.find_all('div', id=self._BODY_ID_RE)
            )
            best = ''
            for container in containers:
                for tag in container.find_all(self._NOISE_TAGS):
                    tag.decompose()
                paragraphs = [self.extract_text(p) for p in container.find_all('p')]
                body = ' '.join(p for p in paragraphs if p)
                if len(body) > len(best):
                    best = body
            if len(best) >= self.DETAIL_MIN_BODY:
                return {'content': best}
            return None

        except Exception as e:
            logger.debug(f"[global_news] 상세 크롤링 오류: {url} - {e}")
            return None
