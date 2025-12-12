"""
한국경제 뉴스 크롤러
한국경제 증시/경제 뉴스 수집
"""

import re
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import urljoin
import logging

from ..base_crawler import BaseCrawler

logger = logging.getLogger(__name__)


class HankyungCrawler(BaseCrawler):
    """한국경제 뉴스 크롤러"""
    
    BASE_URL = "https://www.hankyung.com"
    NEWS_LIST_URL = "https://www.hankyung.com/economy"
    
    def __init__(self):
        super().__init__("hankyung")
    
    def crawl_news_list(self, max_pages: int = 5) -> List[Dict]:
        """뉴스 목록 크롤링"""
        news_list = []
        
        # 경제/증시 섹션 URL들
        sections = [
            {'url': 'https://www.hankyung.com/economy', 'name': '경제'},
            {'url': 'https://www.hankyung.com/financial-market', 'name': '금융시장'},
            {'url': 'https://www.hankyung.com/industry', 'name': '산업'},
            {'url': 'https://www.hankyung.com/tech', 'name': '기술'},
            {'url': 'https://www.hankyung.com/international', 'name': '국제'},
            {'url': 'https://www.hankyung.com/distribution', 'name': '유통'}
        ]
        
        for section in sections:
            for page in range(1, max_pages + 1):
                try:
                    url = f"{section['url']}?page={page}"
                    soup = self.fetch_page(url)
                    
                    if not soup:
                        continue
                    
                    # 뉴스 목록 추출
                    news_items = soup.find_all('div', class_=re.compile(r'article|news|item')) or \
                                soup.find_all('li', class_=re.compile(r'article|news|item')) or \
                                soup.find_all('article')
                    
                    if not news_items:
                        # 다른 패턴 시도
                        news_items = soup.find_all('a', href=re.compile(r'/news/'))
                    
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
                            
                            if not title or len(title) < 10:  # 너무 짧은 제목 제외
                                continue
                            
                            relative_url = title_tag.get('href', '')
                            if not relative_url:
                                continue
                            
                            news_url = urljoin(self.BASE_URL, relative_url)
                            
                            # 날짜 정보
                            date_tag = item.find(class_=re.compile(r'date|time|pub|reg'))
                            if not date_tag:
                                date_tag = item.find('time')
                            
                            date_str = self.extract_text(date_tag) if date_tag else ""
                            published_at = self.parse_date_string(date_str)
                            
                            # 요약
                            summary_tag = item.find(class_=re.compile(r'summary|desc|lead|preview'))
                            summary = self.extract_text(summary_tag) if summary_tag else ""
                            
                            # 제목과 요약에서 주식 코드 추출 (초기 추출)
                            text_for_extraction = f"{title} {summary}"
                            related_stocks = self.extract_stock_codes(text_for_extraction)
                            
                            news_data = {
                                'news_id': self.generate_news_id(news_url, title),
                                'title': title,
                                'content': summary,
                                'published_at': published_at,
                                'source': self.source_name,
                                'category': section['name'],
                                'url': news_url,
                                'related_stocks': related_stocks,
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
            if detail and detail.get('content'):
                news['content'] = detail['content']
                # 본문에서도 주식 코드 추출하여 기존 코드와 합치기
                content_codes = self.extract_stock_codes(detail['content'])
                existing_codes = news.get('related_stocks', '')
                if content_codes:
                    if existing_codes:
                        # 기존 코드와 합치기 (중복 제거)
                        all_codes = set(existing_codes.split(',')) | set(content_codes.split(','))
                        news['related_stocks'] = ','.join(sorted(all_codes))
                    else:
                        news['related_stocks'] = content_codes
        
        return news_list
    
    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """뉴스 상세 내용 크롤링"""
        soup = self.fetch_page(url)
        
        if not soup:
            return None
        
        try:
            # 본문 추출
            article_body = soup.find('div', class_=re.compile(r'article|content|body|text'))
            if not article_body:
                article_body = soup.find('div', id=re.compile(r'article|content|body'))
            
            if not article_body:
                article_body = soup.find('article')
            
            # 광고나 불필요한 요소 제거
            if article_body:
                for tag in article_body.find_all(['script', 'style', 'iframe', 'ins']):
                    tag.decompose()
            
            content = self.extract_text(article_body) if article_body else ""
            
            # 날짜 정보 재확인
            date_tag = soup.find('time') or soup.find(class_=re.compile(r'date|time|published'))
            date_str = self.extract_text(date_tag) if date_tag else ""
            if date_tag and date_tag.get('datetime'):
                date_str = date_tag.get('datetime')
            
            published_at = self.parse_date_string(date_str)
            
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
                return date_str if len(date_str) == 19 else date_str + ':00'
            
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
    

