"""
한국거래소 공시 크롤러
KRX 공시 정보 수집
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

from ..base_crawler import BaseCrawler

logger = logging.getLogger(__name__)


class KRXCrawler(BaseCrawler):
    """한국거래소 공시 크롤러"""
    
    BASE_URL = "http://kind.krx.co.kr"
    DISCLOSURE_URL = "http://kind.krx.co.kr/disclosure/disclosure.do"
    
    def __init__(self):
        super().__init__("krx_disclosure")
    
    def crawl_news_list(self, max_pages: int = 5) -> List[Dict]:
        """공시 목록 크롤링 (오늘 날짜 기준)"""
        news_list = []
        
        # 오늘 날짜
        today = datetime.now()
        date_str = today.strftime("%Y%m%d")
        
        try:
            # 한국거래소 공시는 주로 RSS나 API를 제공하지만, 
            # 여기서는 간단한 웹 크롤링 방식 사용
            # 실제로는 KRX Open API를 사용하는 것이 권장됨
            
            url = f"{self.DISCLOSURE_URL}?method=search&currentPageSize=100&pageIndex=1&searchMode=&marketType=&fiscalYearEnd=all&company=&reportType=&periodBegin={date_str}&periodEnd={date_str}"
            
            soup = self.fetch_page(url)
            
            if not soup:
                logger.warning(f"[{self.source_name}] 페이지를 가져올 수 없습니다.")
                return []
            
            # 공시 목록 테이블 찾기
            table = soup.find('table', class_='board_list')
            if not table:
                # 다른 형식의 테이블 시도
                table = soup.find('table')
            
            if not table:
                logger.warning(f"[{self.source_name}] 공시 테이블을 찾을 수 없습니다.")
                return []
            
            rows = table.find_all('tr')[1:]  # 헤더 제외
            
            for row in rows:
                try:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) < 4:
                        continue
                    
                    # 공시 제목 (보통 2번째 또는 3번째 컬럼)
                    title_tag = row.find('a') or cells[1] if len(cells) > 1 else None
                    if not title_tag:
                        continue
                    
                    title = self.extract_text(title_tag)
                    
                    # URL
                    link = title_tag.get('href') if title_tag.name == 'a' else None
                    if not link:
                        continue
                    
                    news_url = link if link.startswith('http') else f"{self.BASE_URL}{link}"
                    
                    # 날짜 정보
                    date_cell = cells[-1] if len(cells) > 0 else None
                    date_str = self.extract_text(date_cell) if date_cell else ""
                    published_at = self.parse_date_string(date_str)
                    
                    # 종목 코드 추출
                    company_cell = cells[0] if len(cells) > 0 else None
                    company_text = self.extract_text(company_cell) if company_cell else ""
                    stock_code = self.extract_stock_code(company_text, title)
                    
                    news_data = {
                        'news_id': self.generate_news_id(news_url, title),
                        'title': f"[공시] {title}",
                        'content': '',  # 상세 내용은 crawl_news_detail에서
                        'published_at': published_at,
                        'source': self.source_name,
                        'category': '공시',
                        'url': news_url,
                        'related_stocks': stock_code,
                        'sentiment_score': None
                    }
                    
                    news_list.append(news_data)
                    
                except Exception as e:
                    logger.error(f"공시 항목 파싱 오류: {e}")
                    continue
            
            logger.info(f"[{self.source_name}] 크롤링 완료: {len(news_list)}개")
            
            # 상세 내용 크롤링 (선택적)
            # 공시는 주로 PDF나 상세 페이지에 있음
            for news in news_list[:10]:  # 최신 10개만
                detail = self.crawl_news_detail(news['url'])
                if detail and detail.get('content'):
                    news['content'] = detail['content']
            
        except Exception as e:
            logger.error(f"[{self.source_name}] 크롤링 오류: {e}")
        
        return news_list
    
    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """공시 상세 내용 크롤링"""
        soup = self.fetch_page(url)
        
        if not soup:
            return None
        
        try:
            # 공시 내용 추출
            content_div = soup.find('div', class_='board_view')
            if not content_div:
                content_div = soup.find('div', id='content')
            
            content = self.extract_text(content_div) if content_div else ""
            
            return {
                'content': content
            }
            
        except Exception as e:
            logger.debug(f"[{self.source_name}] 상세 내용 크롤링 오류: {url} - {e}")
            return None
    
    def parse_date_string(self, date_str: str) -> str:
        """날짜 문자열 파싱"""
        if not date_str:
            return datetime.now().isoformat()
        
        try:
            # "2024-01-15" 또는 "2024.01.15" 형식
            date_pattern = re.search(r'(\d{4})[.-](\d{2})[.-](\d{2})', date_str)
            if date_pattern:
                year, month, day = date_pattern.groups()
                return f"{year}-{month}-{day}T00:00:00"
            
        except Exception as e:
            logger.debug(f"날짜 파싱 오류: {date_str} - {e}")
        
        return datetime.now().isoformat()
    
    def extract_stock_code(self, company_text: str, title: str) -> str:
        """종목 코드 추출"""
        text = f"{company_text} {title}"
        # 6자리 숫자 패턴
        codes = re.findall(r'\b\d{6}\b', text)
        return ','.join(set(codes))

