"""
매일경제 뉴스 크롤러
매일경제 증시/경제 뉴스 수집
"""

import re
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import urljoin
import logging

from ..base_crawler import BaseCrawler

logger = logging.getLogger(__name__)


class MKNewsCrawler(BaseCrawler):
    """매일경제 뉴스 크롤러"""
    
    BASE_URL = "https://www.mk.co.kr"
    NEWS_LIST_URL = "https://www.mk.co.kr/news/economy"
    
    def __init__(self):
        super().__init__("mk_news")
    
    def crawl_news_list(self, max_pages: int = 5) -> List[Dict]:
        """뉴스 목록 크롤링"""
        news_list = []
        
        # 경제/증시 섹션 URL들
        sections = [
            {'url': 'https://www.mk.co.kr/news/economy', 'name': '경제'},
            {'url': 'https://www.mk.co.kr/news/finance', 'name': '금융'},
            {'url': 'https://www.mk.co.kr/news/stock', 'name': '증시'}
        ]
        
        for section in sections:
            for page in range(1, max_pages + 1):
                try:
                    url = f"{section['url']}?page={page}"
                    soup = self.fetch_page(url)
                    
                    if not soup:
                        continue
                    
                    # 뉴스 목록 추출
                    news_items = soup.find_all('div', class_=re.compile(r'article|news|item|list')) or \
                                soup.find_all('li', class_=re.compile(r'article|news|item')) or \
                                soup.find_all('article') or \
                                soup.find_all('a', href=re.compile(r'/news/'))
                    
                    for item in news_items:
                        try:
                            # 제목과 링크
                            if item.name == 'a':
                                title_tag = item
                                title = self.extract_text(item)
                            else:
                                title_tag = item.find('a')
                                if not title_tag:
                                    continue
                                title = self.extract_text(title_tag)
                            
                            if not title or len(title) < 10:
                                continue
                            
                            relative_url = title_tag.get('href', '')
                            if not relative_url:
                                continue
                            
                            news_url = urljoin(self.BASE_URL, relative_url)
                            
                            # 날짜 정보
                            date_tag = item.find(class_=re.compile(r'date|time|pub|reg|time')) or \
                                      item.find('time')
                            
                            date_str = self.extract_text(date_tag) if date_tag else ""
                            if date_tag and date_tag.get('datetime'):
                                date_str = date_tag.get('datetime')
                            
                            published_at = self.parse_date_string(date_str)
                            
                            # 요약
                            summary_tag = item.find(class_=re.compile(r'summary|desc|lead|preview|intro'))
                            summary = self.extract_text(summary_tag) if summary_tag else ""
                            
                            news_data = {
                                'news_id': self.generate_news_id(news_url, title),
                                'title': title,
                                'content': summary,
                                'published_at': published_at,
                                'source': self.source_name,
                                'category': section['name'],
                                'url': news_url,
                                'related_stocks': self.extract_stock_codes(title + " " + summary),
                                'sentiment_score': None
                            }
                            
                            news_list.append(news_data)
                            
                        except Exception as e:
                            logger.debug(f"뉴스 항목 파싱 오류: {e}")
                            continue
                    
                    logger.info(f"[{self.source_name}] {section['name']} 섹션 {page}페이지 크롤링 완료")
                    
                except Exception as e:
                    logger.error(f"[{self.source_name}] 페이지 {page} 크롤링 오류: {e}")
                    continue
        
        # 상세 내용 크롤링 (모든 뉴스에 대해 수행)
        for news in news_list:
            detail = self.crawl_news_detail(news['url'])
            summary = news.get('content') or ""

            if detail:
                content = detail.get('content') or ""
                merged = (content + " " + summary).strip()

                # 본문/요약/병합본 중 의미 있는 텍스트를 우선순위에 따라 선택
                if len(content) >= 10:
                    news['content'] = content
                elif len(merged) >= 10:
                    news['content'] = merged
                elif len(summary) >= 10:
                    news['content'] = summary
                else:
                    news['content'] = content or summary
            else:
                # 상세 페이지 크롤링 실패 시에도 요약이 충분히 길면 사용
                if len(summary) >= 10:
                    news['content'] = summary
                else:
                    news['content'] = summary or ""
        
        return news_list
    
    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """뉴스 상세 내용 크롤링"""
        soup = self.fetch_page(url)
        
        if not soup:
            return None
        
        try:
            content = ""
            article_body = None
            
            # 매일경제 본문 추출 - 다양한 선택자 순차 시도
            selectors = [
                # 1순위: 매일경제 특정 클래스
                lambda s: s.find('div', class_='news_cnt_detail_wrap'),
                lambda s: s.find('div', class_=re.compile(r'article|content|body|text|news_body', re.I)),
                lambda s: s.find('div', id=re.compile(r'article|content|body', re.I)),
                # 2순위: 일반적인 본문 패턴
                lambda s: s.find('article', class_=re.compile(r'article|content|body', re.I)),
                lambda s: s.find('article'),
                lambda s: s.find('div', class_=re.compile(r'news.*content|news.*body', re.I)),
                # 3순위: 더 넓은 패턴
                lambda s: s.find('div', class_=re.compile(r'content|body|text', re.I)),
                lambda s: s.find('div', id=re.compile(r'content|body', re.I)),
            ]
            
            # 각 선택자 시도
            for selector in selectors:
                try:
                    article_body = selector(soup)
                    if article_body:
                        # 광고나 불필요한 요소 제거
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside', 'div', 'span'], 
                                                          class_=re.compile(r'ad|advertisement|banner|sponsor|promotion|related|recommend', re.I)):
                            tag.decompose()
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside']):
                            tag.decompose()
                        
                        # 본문 텍스트 추출
                        content = self.extract_text(article_body)
                        
                        # 내용이 충분히 길면 성공으로 간주
                        # 기준을 완화하여 더 많은 본문을 수집
                        if len(content) >= 20:
                            break
                except Exception as e:
                    logger.debug(f"[{self.source_name}] 선택자 시도 오류: {e}")
                    continue
            
            # 여전히 내용이 짧으면 추가 시도
            if len(content) < 20:
                main_content = soup.find('main') or soup.find('div', class_=re.compile(r'main|container', re.I))
                if main_content:
                    for tag in main_content.find_all(['script', 'style', 'iframe', 'ins', 'aside', 'header', 'footer', 'nav']):
                        tag.decompose()
                    temp_content = self.extract_text(main_content)
                    if len(temp_content) > len(content):
                        content = temp_content
            
            # 날짜 정보 재확인
            date_tag = soup.find('time') or \
                      soup.find(class_=re.compile(r'date|time|published|reg_time', re.I)) or \
                      soup.find('span', class_=re.compile(r'date|time', re.I))
            
            date_str = self.extract_text(date_tag) if date_tag else ""
            if date_tag and date_tag.get('datetime'):
                date_str = date_tag.get('datetime')
            
            published_at = self.parse_date_string(date_str)
            
            # 내용이 없거나 너무 짧으면 로깅
            if len(content) < 50:
                logger.debug(f"[{self.source_name}] 본문 추출 실패 또는 내용 부족: {url} (길이: {len(content)})")
            
            return {
                'content': content,
                'published_at': published_at
            }
            
        except Exception as e:
            logger.debug(f"[{self.source_name}] 상세 내용 크롤링 오류: {url} - {e}")
            return None
    
    def parse_date_string(self, date_str: str) -> str:
        """날짜 문자열 파싱"""
        if not date_str:
            return datetime.now().isoformat()
        
        try:
            # ISO 형식 "2024-01-15T14:30:00"
            if 'T' in date_str:
                date_str = date_str.split('T')[0] + 'T' + date_str.split('T')[1].split('+')[0].split('.')[0]
                if len(date_str) < 19:
                    date_str = date_str + ':00'
                return date_str
            
            # "2024-01-15 14:30:00" 형식
            date_pattern = re.search(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})', date_str)
            if date_pattern:
                year, month, day, hour, minute = date_pattern.groups()
                return f"{year}-{month}-{day}T{hour}:{minute}:00"
            
            # "2024.01.15 14:30" 형식
            date_pattern = re.search(r'(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})', date_str)
            if date_pattern:
                year, month, day, hour, minute = date_pattern.groups()
                return f"{year}-{month}-{day}T{hour}:{minute}:00"
            
            # "01-15 14:30" 형식
            date_pattern = re.search(r'(\d{2})[.-](\d{2})\s+(\d{2}):(\d{2})', date_str)
            if date_pattern:
                month, day, hour, minute = date_pattern.groups()
                year = datetime.now().year
                return f"{year}-{month}-{day}T{hour}:{minute}:00"
            
        except Exception as e:
            logger.debug(f"날짜 파싱 오류: {date_str} - {e}")
        
        return datetime.now().isoformat()
    
    def extract_stock_codes(self, text: str) -> str:
        """종목 코드 추출"""
        codes = re.findall(r'\b\d{6}\b', text)
        return ','.join(set(codes))

