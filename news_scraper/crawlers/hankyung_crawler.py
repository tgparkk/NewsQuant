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
                            # 종목명 매핑을 활용한 정확한 추출
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
            try:
                summary = news.get('content') or ""  # 목록 페이지에서 추출한 요약
                detail = self.crawl_news_detail(news['url'])

                if detail:
                    content = detail.get('content') or ""
                    
                    # 본문이 충분히 길면 본문 사용
                    if len(content) >= 50:
                        news['content'] = content
                    # 본문이 짧지만 요약과 합치면 의미있으면 병합
                    elif len(content) >= 10 and len(summary) >= 10:
                        merged = (content + " " + summary).strip()
                        news['content'] = merged
                    # 본문이 없거나 너무 짧으면 요약 사용
                    elif len(summary) >= 10:
                        news['content'] = summary
                    # 요약도 없으면 본문이라도 저장 (빈 문자열일 수 있음)
                    else:
                        news['content'] = content or summary or ""

                    # 본문에서도 종목 코드 추출하여 기존 코드와 합치기
                    content_codes = self.extract_stock_codes(content)
                    existing_codes = news.get('related_stocks', '')
                    if content_codes:
                        if existing_codes:
                            # 기존 코드와 합치기 (중복 제거)
                            all_codes = set(existing_codes.split(',')) | set(content_codes.split(','))
                            news['related_stocks'] = ','.join(sorted(all_codes))
                        else:
                            news['related_stocks'] = content_codes
                else:
                    # 상세 페이지 크롤링 실패 시에도 요약이 있으면 반드시 사용
                    # 요약이 5자 이상이면 저장 (기준 완화)
                    if len(summary) >= 5:
                        news['content'] = summary
                    else:
                        # 요약도 없으면 빈 문자열이라도 저장 (나중에 재처리 가능하도록)
                        news['content'] = summary or ""
                        logger.debug(f"[{self.source_name}] 요약 정보도 없음: {news.get('url', '')}")
            except Exception as e:
                logger.debug(f"[{self.source_name}] 상세 크롤링 오류: {news.get('url', '')} - {e}")
                # 오류 발생 시에도 요약 정보라도 저장
                summary = news.get('content') or ""
                if len(summary) >= 5:
                    news['content'] = summary
                else:
                    news['content'] = summary or ""
                continue
        
        return news_list
    
    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """뉴스 상세 내용 크롤링"""
        soup = self.fetch_page(url)
        
        if not soup:
            return None
        
        try:
            content = ""
            article_body = None
            
            # 한국경제 본문 추출 - 다양한 선택자 순차 시도 (개선된 버전)
            selectors = [
                # 1순위: 한국경제 특정 클래스/ID (더 많은 패턴)
                lambda s: s.find('div', class_='article-body'),
                lambda s: s.find('div', id='article-body'),
                lambda s: s.find('div', class_='article_body'),
                lambda s: s.find('div', id='article_body'),
                lambda s: s.find('div', class_=re.compile(r'article.*body|article.*content|article.*text', re.I)),
                lambda s: s.find('div', id=re.compile(r'article.*body|article.*content', re.I)),
                # 2순위: 한국경제 특정 구조
                lambda s: s.find('div', class_=re.compile(r'news_body|article_view|article_content', re.I)),
                lambda s: s.find('div', class_=re.compile(r'news.*content|news.*body', re.I)),
                lambda s: s.find('section', class_=re.compile(r'article|content|body', re.I)),
                # 3순위: 일반적인 본문 패턴
                lambda s: s.find('article', class_=re.compile(r'article|content|body', re.I)),
                lambda s: s.find('article'),
                lambda s: s.find('div', class_=re.compile(r'content|body|text|article', re.I)),
                lambda s: s.find('div', id=re.compile(r'content|body|article', re.I)),
                # 4순위: 더 넓은 패턴
                lambda s: s.find('main'),
                lambda s: s.find('div', class_=re.compile(r'main|container|wrapper', re.I)),
            ]
            
            # 각 선택자 시도
            for selector in selectors:
                try:
                    article_body = selector(soup)
                    if article_body:
                        # 광고나 불필요한 요소 제거
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside', 'div', 'span'], 
                                                          class_=re.compile(r'ad|advertisement|banner|sponsor|promotion|related|recommend|news_end_btn|end_photo_org', re.I)):
                            tag.decompose()
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside', 'div'], 
                                                          id=re.compile(r'ad|advertisement|banner|sponsor|promotion', re.I)):
                            tag.decompose()
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside']):
                            tag.decompose()
                        
                        # 본문 텍스트 추출
                        content = self.extract_text(article_body)
                        
                        # 내용이 충분히 길면 성공으로 간주
                        # 기준을 상향하여 더 정확한 본문 수집
                        if len(content) >= 50:  # 20자에서 50자로 상향
                            break
                        elif len(content) >= 20:
                            # 20자 이상이면 일단 저장하되, 더 나은 선택자 계속 시도
                            pass
                except Exception as e:
                    logger.debug(f"[{self.source_name}] 선택자 시도 오류: {e}")
                    continue
            
            # 여전히 내용이 짧으면 추가 시도
            if len(content) < 50:
                main_content = soup.find('main') or soup.find('div', class_=re.compile(r'main|container', re.I))
                if main_content:
                    for tag in main_content.find_all(['script', 'style', 'iframe', 'ins', 'aside', 'header', 'footer', 'nav', 'div'], 
                                                      class_=re.compile(r'header|footer|nav|menu|sidebar|ad|advertisement', re.I)):
                        tag.decompose()
                    temp_content = self.extract_text(main_content)
                    if len(temp_content) > len(content):
                        content = temp_content
                
                # 마지막 시도: 모든 p 태그에서 본문 추출
                if len(content) < 50:
                    all_paragraphs = soup.find_all('p')
                    paragraph_texts = []
                    for p in all_paragraphs:
                        p_text = self.extract_text(p)
                        # 광고나 불필요한 텍스트 필터링
                        if len(p_text) > 20 and not any(keyword in p_text.lower() for keyword in ['광고', 'advertisement', 'sponsor', '관련기사', '추천기사']):
                            paragraph_texts.append(p_text)
                    if paragraph_texts:
                        combined_content = ' '.join(paragraph_texts)
                        if len(combined_content) > len(content):
                            content = combined_content
            
            # 날짜 정보 재확인
            date_tag = soup.find('time') or soup.find(class_=re.compile(r'date|time|published', re.I))
            date_str = self.extract_text(date_tag) if date_tag else ""
            if date_tag and date_tag.get('datetime'):
                date_str = date_tag.get('datetime')
            
            published_at = self.parse_date_string(date_str)
            
            # 내용이 없거나 너무 짧으면 로깅 (하지만 빈 문자열이라도 반환)
            if len(content) < 50:
                logger.debug(f"[{self.source_name}] 본문 추출 실패 또는 내용 부족: {url} (길이: {len(content)})")
            
            # 내용이 없어도 빈 문자열 반환 (요약 정보는 상위에서 처리)
            return {
                'content': content,
                'published_at': published_at
            }
            
        except Exception as e:
            logger.debug(f"[{self.source_name}] 상세 내용 크롤링 오류: {url} - {e}")
            # 오류 발생 시에도 None 대신 빈 내용 반환 (요약 정보 활용 가능하도록)
            return {
                'content': '',
                'published_at': datetime.now().isoformat()
            }
    
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
    

