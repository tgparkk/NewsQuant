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
                        
                        # 제목 추출 - 링크 자체의 텍스트만 사용 (부모에서 찾지 않음)
                        title = self.extract_text(link)
                        
                        # 제목 정리: 너무 긴 경우 잘라내기 (여러 뉴스가 합쳐진 경우 방지)
                        if title:
                            # 제목이 200자 이상이면 여러 뉴스가 합쳐진 것으로 간주
                            if len(title) > 200:
                                # 첫 번째 의미있는 부분만 사용
                                lines = [line.strip() for line in title.split('\n') if line.strip() and len(line.strip()) >= 10]
                                if lines:
                                    title = lines[0]
                                else:
                                    # 줄바꿈이 없으면 첫 100자만 사용
                                    title = title[:100].strip()
                            
                            # 특수 문자나 구분자로 여러 제목이 합쳐진 경우 처리
                            # '|' 또는 '...' 또는 날짜 패턴으로 구분된 경우
                            if '|' in title and len(title) > 100:
                                # 첫 번째 '|' 이전만 사용
                                title = title.split('|')[0].strip()
                            
                            # 날짜 패턴으로 구분된 경우 (예: "제목...2025-12-16 18:07")
                            date_pattern = re.search(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}', title)
                            if date_pattern and date_pattern.start() > 0:
                                title = title[:date_pattern.start()].strip()
                        
                        # 제목이 너무 짧거나 없으면 스킵
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
            
            # 네이버 금융 본문 추출 - 다양한 선택자 순차 시도 (개선된 버전)
            selectors = [
                # 1순위: 네이버 금융 특정 ID/클래스 (최신 패턴)
                lambda s: s.find('div', id='articleBodyContents'),
                lambda s: s.find('div', id='newsEndContents'),
                lambda s: s.find('div', id='articleBody'),
                lambda s: s.find('div', class_='articleBody'),
                # 1-1순위: 네이버 금융 iframe 내부 콘텐츠 (외부 기사 링크)
                lambda s: s.find('iframe', id='mainFrame') or s.find('iframe', id='main_frame'),
                # 2순위: 네이버 특정 클래스 (더 많은 패턴)
                lambda s: s.find('div', class_='_article_body_contents'),
                lambda s: s.find('div', class_='go_trans _article_content'),
                lambda s: s.find('div', class_=re.compile(r'news_end_body|article_view|article_body', re.I)),
                lambda s: s.find('div', class_=re.compile(r'article.*body|article.*content', re.I)),
                lambda s: s.find('div', id=re.compile(r'article.*body|article.*content', re.I)),
                # 3순위: 일반적인 본문 패턴
                lambda s: s.find('article', class_=re.compile(r'article|content|body', re.I)),
                lambda s: s.find('article'),
                lambda s: s.find('div', class_=re.compile(r'content|body|text|article', re.I)),
                lambda s: s.find('div', id=re.compile(r'content|body|article', re.I)),
                # 4순위: 네이버 금융 뉴스 읽기 페이지 특정 구조
                lambda s: s.find('div', class_='news_read'),
                lambda s: s.find('div', id='news_read'),
                lambda s: s.find('div', class_=re.compile(r'news.*read|read.*news', re.I)),
                # 5순위: 본문 영역을 더 넓게 찾기
                lambda s: s.find('main'),
                lambda s: s.find('div', class_=re.compile(r'main|container|wrapper', re.I)),
            ]
            
            # 각 선택자 시도
            for selector in selectors:
                try:
                    article_body = selector(soup)
                    if article_body:
                        # iframe인 경우 처리
                        if article_body.name == 'iframe':
                            iframe_src = article_body.get('src', '')
                            if iframe_src:
                                # iframe 내부 콘텐츠는 별도 처리 필요하지만, 일단 스킵
                                # (실제로는 외부 사이트 크롤링이 필요)
                                continue
                        
                        # 광고나 불필요한 요소 제거
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside', 'div', 'span'], 
                                                          class_=re.compile(r'ad|advertisement|banner|sponsor|promotion|related|recommend|news_end_btn|end_photo_org', re.I)):
                            tag.decompose()
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside', 'div'], 
                                                          id=re.compile(r'ad|advertisement|banner|sponsor|promotion', re.I)):
                            tag.decompose()
                        # 일반적인 불필요 요소 제거
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside']):
                            tag.decompose()
                        
                        # 본문 텍스트 추출
                        content = self.extract_text(article_body)
                        
                        # 내용이 충분히 길면 성공으로 간주
                        # 기준을 완화하여 더 많은 본문을 수집
                        if len(content) >= 50:  # 20자에서 50자로 상향
                            break
                        elif len(content) >= 20:
                            # 20자 이상이면 일단 저장하되, 더 나은 선택자 계속 시도
                            if not article_body or len(content) > len(content):
                                pass  # 이미 더 긴 내용을 찾았으면 유지
                except Exception as e:
                    logger.debug(f"[{self.source_name}] 선택자 시도 오류: {e}")
                    continue
            
            # 여전히 내용이 짧으면 추가 시도
            if len(content) < 50:
                # 본문 영역을 더 넓게 찾기
                main_content = soup.find('main') or soup.find('div', class_=re.compile(r'main|container', re.I))
                if main_content:
                    # 본문 관련 요소만 추출
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
            date_tag = soup.find('span', class_='tah') or \
                      soup.find('div', class_='article_info') or \
                      soup.find('div', class_=re.compile(r'article.*info|news.*info', re.I)) or \
                      soup.find('time') or \
                      soup.find(class_=re.compile(r'date|time|published', re.I))
            
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
        """텍스트에서 종목 코드 추출 (부모 클래스의 개선된 로직 사용)"""
        # 부모 클래스의 extract_stock_codes 사용 (종목명 매핑 포함)
        return super().extract_stock_codes(text)

