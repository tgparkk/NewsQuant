"""
글로벌 뉴스 크롤러
RSS 피드 기반 해외 금융 뉴스 수집 (Reuters, CNBC, MarketWatch, Investing.com)
한국 시장에 영향을 미치는 글로벌 뉴스를 수집하여 KOSPI/KOSDAQ 지수 예측에 활용
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Dict, Optional
from email.utils import parsedate_to_datetime
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

    def __init__(self):
        super().__init__("global_news")
        # RSS 파싱용 헤더 (영문)
        self.session.headers.update({
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
        })

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
            response = self.session.get(feed_url, timeout=15)
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
        return filtered

    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """상세 페이지 크롤링 (RSS에서 이미 충분한 정보를 제공하므로 기본 구현)"""
        try:
            soup = self.fetch_page(url)
            if not soup:
                return None

            # 본문 추출
            content = ''
            for selector in [
                soup.find('article'),
                soup.find('div', class_=re.compile(r'article.*body|story.*body|content', re.I)),
                soup.find('div', id=re.compile(r'article|story|content', re.I)),
            ]:
                if selector:
                    for tag in selector.find_all(['script', 'style', 'iframe', 'ins', 'aside']):
                        tag.decompose()
                    content = self.extract_text(selector)
                    if len(content) >= 100:
                        break

            return {'content': content} if content else None

        except Exception as e:
            logger.debug(f"[global_news] 상세 크롤링 오류: {url} - {e}")
            return None
