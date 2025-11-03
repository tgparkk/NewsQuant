"""
네이버 금융 뉴스 크롤러
네이버 금융 증시/경제 뉴스를 수집
"""

import re
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse
import logging

from ..base_crawler import BaseCrawler

logger = logging.getLogger(__name__)


class NaverFinanceCrawler(BaseCrawler):
    """네이버 금융 뉴스 크롤러"""
    
    BASE_URL = "https://finance.naver.com"
    NEWS_LIST_URL = "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258"
    
    def __init__(self):
        super().__init__("naver_finance")
    
    def crawl_news_list(self, max_pages: int = 5) -> List[Dict]:
        """뉴스 목록 크롤링"""
        news_list = []
        
        for page in range(1, max_pages + 1):
            try:
                url = f"{self.NEWS_LIST_URL}&page={page}"
                soup = self.fetch_page(url)
                
                if not soup:
                    continue
                
                # 뉴스 목록 추출
                news_items = soup.find_all('dl', class_='articleSubject')
                
                for item in news_items:
                    try:
                        # 제목과 링크
                        title_tag = item.find('a')
                        if not title_tag:
                            continue
                        
                        title = self.extract_text(title_tag)
                        relative_url = title_tag.get('href', '')
                        news_url = urljoin(self.BASE_URL, relative_url)
                        
                        # 날짜 정보
                        date_tag = item.find_next_sibling('dd', class_='articleSubjectSummary')
                        date_str = self.extract_text(date_tag) if date_tag else ""
                        published_at = self.parse_date_string(date_str)
                        
                        # 언론사 정보
                        press_tag = item.find_next_sibling('dd', class_='press')
                        press = self.extract_text(press_tag) if press_tag else ""
                        
                        # 요약 정보
                        summary_tag = item.find_next_sibling('dd', class_='articleSummary')
                        summary = self.extract_text(summary_tag) if summary_tag else ""
                        
                        news_data = {
                            'news_id': self.generate_news_id(news_url, title),
                            'title': title,
                            'content': summary,  # 상세 내용은 crawl_news_detail에서
                            'published_at': published_at,
                            'source': self.source_name,
                            'category': '증시',
                            'url': news_url,
                            'related_stocks': self.extract_stock_codes(title + " " + summary),
                            'sentiment_score': None
                        }
                        
                        news_list.append(news_data)
                        
                    except Exception as e:
                        logger.error(f"뉴스 항목 파싱 오류: {e}")
                        continue
                
                logger.info(f"[{self.source_name}] {page}페이지 크롤링 완료: {len(news_items)}개")
                
            except Exception as e:
                logger.error(f"[{self.source_name}] 페이지 {page} 크롤링 오류: {e}")
                continue
        
        # 상세 내용 크롤링
        for news in news_list:
            detail = self.crawl_news_detail(news['url'])
            if detail and detail.get('content'):
                news['content'] = detail['content']
        
        return news_list
    
    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """뉴스 상세 내용 크롤링"""
        soup = self.fetch_page(url)
        
        if not soup:
            return None
        
        try:
            # 본문 추출
            article_body = soup.find('div', class_='articleBody')
            if not article_body:
                article_body = soup.find('div', id='newsEndContents')
            
            content = self.extract_text(article_body) if article_body else ""
            
            # 날짜 정보 재확인
            date_tag = soup.find('span', class_='tah')
            if not date_tag:
                date_tag = soup.find('div', class_='article_info')
            
            date_str = self.extract_text(date_tag) if date_tag else ""
            published_at = self.parse_date_string(date_str)
            
            return {
                'content': content,
                'published_at': published_at
            }
            
        except Exception as e:
            logger.error(f"[{self.source_name}] 상세 내용 크롤링 오류: {url} - {e}")
            return None
    
    def parse_date_string(self, date_str: str) -> str:
        """네이버 금융 날짜 형식 파싱"""
        if not date_str:
            return datetime.now().isoformat()
        
        try:
            # "2024.01.15 14:30" 형식
            date_pattern = re.search(r'(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})', date_str)
            if date_pattern:
                year, month, day, hour, minute = date_pattern.groups()
                return f"{year}-{month}-{day}T{hour}:{minute}:00"
            
            # "2024.01.15" 형식
            date_pattern = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', date_str)
            if date_pattern:
                year, month, day = date_pattern.groups()
                return f"{year}-{month}-{day}T00:00:00"
            
            # "01.15 14:30" 형식 (올해 날짜)
            date_pattern = re.search(r'(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})', date_str)
            if date_pattern:
                month, day, hour, minute = date_pattern.groups()
                year = datetime.now().year
                return f"{year}-{month}-{day}T{hour}:{minute}:00"
            
        except Exception as e:
            logger.debug(f"날짜 파싱 오류: {date_str} - {e}")
        
        return datetime.now().isoformat()
    
    def extract_stock_codes(self, text: str) -> str:
        """텍스트에서 종목 코드 추출 (6자리 숫자)"""
        # 6자리 숫자 패턴 (종목 코드로 추정)
        codes = re.findall(r'\b\d{6}\b', text)
        return ','.join(set(codes))  # 중복 제거

