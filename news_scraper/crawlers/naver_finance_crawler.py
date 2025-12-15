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
    
    def __init__(self):
        super().__init__("naver_finance")
    
    def crawl_news_list(self, max_pages: int = 5) -> List[Dict]:
        """뉴스 목록 크롤링"""
        news_list = []
        
        # 네이버 금융 뉴스 섹션들
        sections = [
            {'url': 'https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258', 'name': '증시'},
            {'url': 'https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=259', 'name': '경제'},
            {'url': 'https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=260', 'name': '산업'}
        ]
        
        for section in sections:
            for page in range(1, max_pages + 1):
                try:
                    url = f"{section['url']}&page={page}"
                    soup = self.fetch_page(url)
                    
                    if not soup:
                        continue
                    
                    # 네이버 금융은 a 태그로 뉴스 링크를 직접 찾는 방식이 효과적
                    # 다양한 뉴스 링크 패턴 찾기
                    all_links = soup.find_all('a', href=True)
                    news_links = []
                    seen_urls = set()  # 중복 제거용
                    
                    for link in all_links:
                        href = link.get('href', '')
                        # 뉴스 관련 링크 패턴들
                        is_news_link = (
                            '/news/read' in href or 
                            '/news/news_view' in href or
                            '/news/news_read' in href or
                            (href.startswith('/news/') and 'article_id' in href) or
                            (href.startswith('/news/') and len(href) > 20)  # 긴 링크는 뉴스일 가능성 높음
                        )
                        
                        if not is_news_link:
                            continue
                        
                        # 절대 URL로 변환
                        if href.startswith('http'):
                            full_url = href
                        else:
                            full_url = urljoin(self.BASE_URL, href)
                        
                        # 중복 제거
                        if full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)
                        
                        # 제목 추출
                        title = self.extract_text(link)
                        
                        # 제목이 너무 짧거나 없는 경우, 부모 요소에서 찾기
                        if not title or len(title) < 10:
                            # 부모 요소에서 제목 찾기
                            parent = link.parent
                            for _ in range(2):
                                if parent:
                                    # 부모의 텍스트에서 의미있는 제목 찾기
                                    parent_text = self.extract_text(parent)
                                    # 링크 텍스트가 아닌 다른 텍스트 찾기
                                    if parent_text and len(parent_text) > len(title):
                                        # 첫 번째 긴 텍스트를 제목으로 사용
                                        lines = [line.strip() for line in parent_text.split('\n') if line.strip()]
                                        for line in lines:
                                            if len(line) >= 10 and line != title:
                                                title = line
                                                break
                                    if len(title) >= 10:
                                        break
                                    parent = parent.parent if hasattr(parent, 'parent') else None
                                else:
                                    break
                        
                        # 여전히 제목이 없거나 짧으면 스킵
                        if not title or len(title) < 10:
                            continue
                        
                        # 부모 요소에서 날짜와 요약 찾기
                        parent = link.parent
                        date_str = ""
                        summary = ""
                        
                        # 날짜 찾기 (부모 요소에서)
                        for _ in range(3):  # 최대 3단계 상위 요소까지 검색
                            if parent:
                                date_tag = parent.find(class_=re.compile(r'date|time|pub|reg')) or \
                                          parent.find('time') or \
                                          parent.find('span', class_=re.compile(r'date|time'))
                                if date_tag:
                                    date_str = self.extract_text(date_tag)
                                    if date_tag.get('datetime'):
                                        date_str = date_tag.get('datetime')
                                    break
                                
                                # 텍스트에서 날짜 패턴 찾기
                                parent_text = self.extract_text(parent)
                                date_match = re.search(r'\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2}', parent_text)
                                if date_match:
                                    date_str = date_match.group()
                                    break
                                
                                parent = parent.parent if hasattr(parent, 'parent') else None
                            else:
                                break
                        
                        # 요약 찾기 (부모 요소에서)
                        parent = link.parent
                        for _ in range(3):
                            if parent:
                                summary_tag = parent.find(class_=re.compile(r'summary|desc|lead|preview|article'))
                                if summary_tag:
                                    summary = self.extract_text(summary_tag)
                                    if len(summary) > 20:  # 의미있는 요약만
                                        break
                                parent = parent.parent if hasattr(parent, 'parent') else None
                            else:
                                break
                        
                        published_at = self.parse_date_string(date_str)
                        
                        news_data = {
                            'news_id': self.generate_news_id(full_url, title),
                            'title': title,
                            'content': summary,
                            'published_at': published_at,
                            'source': self.source_name,
                            'category': section['name'],
                            'url': full_url,
                            'related_stocks': self.extract_stock_codes(title + " " + summary),
                            'sentiment_score': None
                        }
                        
                        news_links.append(news_data)
                    
                    # 중복 제거 (제목 기준)
                    unique_news = {}
                    for news in news_links:
                        title_key = news['title']
                        if title_key not in unique_news:
                            unique_news[title_key] = news
                    
                    news_list.extend(unique_news.values())
                    
                    logger.info(f"[{self.source_name}] {section['name']} 섹션 {page}페이지 크롤링 완료: {len(unique_news)}개 뉴스 수집")
                    
                except Exception as e:
                    logger.error(f"[{self.source_name}] 페이지 {page} 크롤링 오류: {e}")
                    continue
        
        # 상세 내용 크롤링 (최신 20개만)
        for news in news_list[:20]:
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
            # 본문 추출 (다양한 선택자 시도)
            article_body = soup.find('div', class_='articleBody') or \
                          soup.find('div', id='newsEndContents') or \
                          soup.find('div', class_=re.compile(r'article|content|body|text')) or \
                          soup.find('div', id=re.compile(r'article|content|body')) or \
                          soup.find('article')
            
            # 광고나 불필요한 요소 제거
            if article_body:
                for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside']):
                    tag.decompose()
            
            content = self.extract_text(article_body) if article_body else ""
            
            # 날짜 정보 재확인
            date_tag = soup.find('span', class_='tah') or \
                      soup.find('div', class_='article_info') or \
                      soup.find('time') or \
                      soup.find(class_=re.compile(r'date|time|published'))
            
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

