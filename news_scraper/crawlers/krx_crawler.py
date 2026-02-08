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
            # 한국거래소 공시 URL (최신 구조)
            # https://kind.krx.co.kr/disclosure/disclosure.do 접근 시도
            # 또는 공시 RSS 피드 사용 고려
            
            # 방법 1: 공시 검색 페이지
            url = f"{self.DISCLOSURE_URL}?method=search&currentPageSize=100&pageIndex=1&searchMode=&marketType=&fiscalYearEnd=all&company=&reportType=&periodBegin={date_str}&periodEnd={date_str}"
            
            soup = self.fetch_page(url)
            
            if not soup:
                # 방법 2: 메인 페이지에서 공시 링크 찾기
                main_url = "https://kind.krx.co.kr/disclosure/disclosure.do"
                soup = self.fetch_page(main_url)
                
                if not soup:
                    logger.warning(f"[{self.source_name}] 페이지를 가져올 수 없습니다.")
                    return []
            
            # 공시 목록 테이블 찾기 (다양한 구조 시도)
            table = soup.find('table', class_='board_list') or \
                   soup.find('table', class_=re.compile(r'list|board|table')) or \
                   soup.find('table', id=re.compile(r'list|board')) or \
                   soup.find('table')
            
            if not table:
                # 리스트 형식 시도
                list_items = soup.find_all('div', class_=re.compile(r'list|item|disclosure')) or \
                           soup.find_all('li', class_=re.compile(r'list|item|disclosure'))
                
                if list_items:
                    for item in list_items:
                        try:
                            title_tag = item.find('a')
                            if not title_tag:
                                continue
                            
                            title = self.extract_text(title_tag)
                            relative_url = title_tag.get('href', '')
                            news_url = relative_url if relative_url.startswith('http') else f"{self.BASE_URL}{relative_url}"
                            
                            date_tag = item.find(class_=re.compile(r'date|time'))
                            date_str = self.extract_text(date_tag) if date_tag else ""
                            published_at = self.parse_date_string(date_str)
                            
                            stock_code = self.extract_stock_code("", title)
                            
                            news_data = {
                                'news_id': self.generate_news_id(news_url, title),
                                'title': f"[공시] {title}",
                                'content': '',
                                'published_at': published_at,
                                'source': self.source_name,
                                'category': '공시',
                                'url': news_url,
                                'related_stocks': stock_code,
                                'sentiment_score': None
                            }
                            
                            news_list.append(news_data)
                        except Exception as e:
                            logger.debug(f"공시 항목 파싱 오류: {e}")
                            continue
                    
                    logger.info(f"[{self.source_name}] 크롤링 완료: {len(news_list)}개")
                    return news_list
            
            # 테이블 형식 파싱
            rows = table.find_all('tr')[1:]  # 헤더 제외
            
            for row in rows:
                try:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) < 2:
                        continue
                    
                    # 공시 제목과 링크 찾기
                    title_tag = row.find('a')
                    if not title_tag:
                        # 셀에서 직접 찾기
                        for cell in cells:
                            title_tag = cell.find('a')
                            if title_tag:
                                break
                    
                    if not title_tag:
                        continue
                    
                    title = self.extract_text(title_tag)
                    if not title or len(title) < 5:
                        continue
                    
                    # URL
                    link = title_tag.get('href', '')
                    if not link:
                        continue
                    
                    news_url = link if link.startswith('http') else f"{self.BASE_URL}{link}"
                    
                    # 날짜 정보 (마지막 셀 또는 날짜 관련 셀)
                    date_str = ""
                    for cell in cells:
                        cell_text = self.extract_text(cell)
                        if re.search(r'\d{4}[.-]\d{2}[.-]\d{2}', cell_text):
                            date_str = cell_text
                            break
                    
                    if not date_str:
                        date_cell = cells[-1] if len(cells) > 0 else None
                        date_str = self.extract_text(date_cell) if date_cell else ""
                    
                    published_at = self.parse_date_string(date_str)
                    
                    # 종목 코드 추출
                    company_text = ""
                    for cell in cells[:3]:  # 처음 3개 셀에서 회사명 찾기
                        cell_text = self.extract_text(cell)
                        if cell_text and len(cell_text) < 50:  # 회사명은 보통 짧음
                            company_text = cell_text
                            break
                    
                    stock_code = self.extract_stock_code(company_text, title)
                    
                    news_data = {
                        'news_id': self.generate_news_id(news_url, title),
                        'title': f"[공시] {title}",
                        'content': '',
                        'published_at': published_at,
                        'source': self.source_name,
                        'category': '공시',
                        'url': news_url,
                        'related_stocks': stock_code,
                        'sentiment_score': None
                    }
                    
                    news_list.append(news_data)
                    
                except Exception as e:
                    logger.debug(f"공시 항목 파싱 오류: {e}")
                    continue
            
            logger.info(f"[{self.source_name}] 크롤링 완료: {len(news_list)}개")
            
            # 상세 내용 크롤링 (최신 10개만)
            for news in news_list[:10]:
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
            # 공시 내용 추출 (다양한 선택자 시도)
            content_div = soup.find('div', class_='board_view') or \
                         soup.find('div', id='content') or \
                         soup.find('div', class_=re.compile(r'view|content|body|article')) or \
                         soup.find('div', id=re.compile(r'content|view|body'))
            
            # 광고나 불필요한 요소 제거
            if content_div:
                for tag in content_div.find_all(['script', 'style', 'iframe', 'ins', 'aside']):
                    tag.decompose()
            
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

