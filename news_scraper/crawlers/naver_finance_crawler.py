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
        global_seen_urls = set()  # 전체 섹션/페이지에 걸친 URL 중복 제거

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
                    seen_urls = set()  # 페이지 내 중복 제거용
                    
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
                        
                        # 중복 제거 (페이지 내 + 전체 섹션 간)
                        if full_url in seen_urls or full_url in global_seen_urls:
                            continue
                        seen_urls.add(full_url)
                        global_seen_urls.add(full_url)
                        
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
                        
                        # 요약 찾기 (부모 요소에서) - 더 강화된 버전
                        parent = link.parent
                        for _ in range(5):  # 더 넓은 범위 검색
                            if parent:
                                # 다양한 요약 패턴 시도
                                summary_tag = (parent.find(class_=re.compile(r'summary|desc|lead|preview|article|text', re.I)) or
                                             parent.find('p', class_=re.compile(r'summary|desc|lead|preview', re.I)) or
                                             parent.find('span', class_=re.compile(r'summary|desc|lead|preview', re.I)) or
                                             parent.find('div', class_=re.compile(r'summary|desc|lead|preview', re.I)))
                                
                                if summary_tag:
                                    summary = self.extract_text(summary_tag)
                                    if len(summary) > 20:  # 의미있는 요약만
                                        break
                                
                                # 부모의 전체 텍스트에서 요약 추출 시도
                                parent_text = self.extract_text(parent)
                                # 제목 다음에 오는 텍스트가 요약일 가능성
                                if title in parent_text:
                                    parts = parent_text.split(title, 1)
                                    if len(parts) > 1:
                                        potential_summary = parts[1].strip()
                                        # 요약으로 보이는 텍스트 (20자 이상, 제목보다 짧음)
                                        if 20 <= len(potential_summary) < len(title) * 3:
                                            summary = potential_summary[:200]  # 최대 200자
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
                    if len(content) >= 100:
                        news['content'] = content
                        logger.debug(f"[{self.source_name}] 본문 사용: {news.get('url', '')} (길이: {len(content)})")
                    # 본문이 50자 이상이면 본문 사용
                    elif len(content) >= 50:
                        news['content'] = content
                        logger.debug(f"[{self.source_name}] 본문 사용 (짧음): {news.get('url', '')} (길이: {len(content)})")
                    # 본문이 짧지만 요약과 합치면 의미있으면 병합
                    elif len(content) >= 20 and len(summary) >= 20:
                        merged = (content + " " + summary).strip()
                        news['content'] = merged
                        logger.debug(f"[{self.source_name}] 본문+요약 병합: {news.get('url', '')} (길이: {len(merged)})")
                    # 본문이 없거나 너무 짧으면 요약 사용
                    elif len(summary) >= 30:  # 요약 최소 길이 증가
                        news['content'] = summary
                        logger.debug(f"[{self.source_name}] 요약 사용: {news.get('url', '')} (길이: {len(summary)})")
                    # 요약도 짧으면 본문이라도 저장
                    elif len(content) >= 10:
                        news['content'] = content
                        logger.debug(f"[{self.source_name}] 짧은 본문 사용: {news.get('url', '')} (길이: {len(content)})")
                    # 요약도 없으면 본문이라도 저장 (빈 문자열일 수 있음)
                    else:
                        news['content'] = content or summary or ""
                        if not news['content']:
                            logger.warning(f"[{self.source_name}] 내용 없음: {news.get('url', '')}")

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
                    # 요약이 20자 이상이면 저장
                    if len(summary) >= 20:
                        news['content'] = summary
                        logger.warning(f"[{self.source_name}] 상세 페이지 실패, 요약 사용: {news.get('url', '')} (요약 길이: {len(summary)})")
                    elif len(summary) >= 10:
                        news['content'] = summary
                        logger.warning(f"[{self.source_name}] 상세 페이지 실패, 짧은 요약 사용: {news.get('url', '')} (요약 길이: {len(summary)})")
                    else:
                        # 요약도 없으면 빈 문자열이라도 저장 (나중에 재처리 가능하도록)
                        news['content'] = summary or ""
                        logger.warning(f"[{self.source_name}] 상세 페이지 실패, 요약 정보도 없음: {news.get('url', '')}")
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
            logger.warning(f"[{self.source_name}] 페이지 가져오기 실패: {url}")
            return None
        
        # JavaScript 리다이렉트 처리
        # 예: <SCRIPT>top.location.href='https://n.news.naver.com/mnews/article/018/0005236061';</SCRIPT>
        script_content = str(soup)
        if 'top.location.href' in script_content and len(script_content) < 1000:
            redirect_match = re.search(r"top\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", script_content)
            if redirect_match:
                new_url = redirect_match.group(1)
                logger.debug(f"[{self.source_name}] JavaScript 리다이렉트 감지: {url} -> {new_url}")
                soup = self.fetch_page(new_url)
                if not soup:
                    logger.warning(f"[{self.source_name}] 리다이렉트 페이지 가져오기 실패: {new_url}")
                    return None
                # URL 업데이트 (로깅용)
                url = new_url
        
        try:
            content = ""
            article_body = None
            best_content = ""  # 가장 긴 내용 저장
            
            # 네이버 금융 본문 추출 - 다양한 선택자 순차 시도 (개선된 버전)
            selectors = [
                # 1순위: 네이버 금융/뉴스 최신 패턴
                lambda s: s.find('article', id='dic_area'),  # 네이버 뉴스 모바일/PC 공통 (가장 정확)
                lambda s: s.find('div', id='dic_area'),      # 네이버 뉴스 일반 섹션
                lambda s: s.find('div', id='articleBodyContents'),
                lambda s: s.find('div', id='newsEndContents'),
                lambda s: s.find('div', id='articleBody'),
                lambda s: s.find('div', class_='article_body'),
                lambda s: s.find('div', class_='news_read'),
                lambda s: s.find('div', id='news_read'),
                # 추가된 네이버 금융/뉴스 패턴
                lambda s: s.find('div', class_='article_view'),
                lambda s: s.find('div', class_='article_content'),
                lambda s: s.find('div', id='articeBody'), # 오타 대응
                lambda s: s.find('div', class_='view_content'),
                # 2순위: 연합뉴스, 뉴스1 등 언론사별 특정 패턴
                lambda s: s.find('div', class_='article_txt'),
                lambda s: s.find('div', class_='article-body'),
                lambda s: s.find('div', class_=re.compile(r'art_body|post_content|content_area', re.I)),
                # 3순위: 일반적인 본문 패턴
                lambda s: s.find('article'),
                lambda s: s.find('main'),
            ]
            
            # 먼저 페이지 내의 모든 iframe 확인 및 처리
            iframes = soup.find_all('iframe')
            for iframe in iframes:
                iframe_src = iframe.get('src', '')
                if iframe_src:
                    # 절대 URL로 변환
                    if not iframe_src.startswith('http'):
                        iframe_src = urljoin(self.BASE_URL, iframe_src)
                    
                    # 네이버 금융 내부 iframe인 경우 크롤링 시도
                    if 'naver.com' in iframe_src or 'finance.naver.com' in iframe_src:
                        try:
                            logger.debug(f"[{self.source_name}] 네이버 내부 iframe 크롤링 시도: {iframe_src}")
                            iframe_soup = self.fetch_page(iframe_src)
                            if iframe_soup:
                                # iframe 내부에서 본문 찾기
                                iframe_content = self._extract_content_from_soup(iframe_soup)
                                if len(iframe_content) > len(best_content):
                                    best_content = iframe_content
                                    content = iframe_content
                                    if len(content) >= 100:
                                        break
                        except Exception as e:
                            logger.debug(f"[{self.source_name}] iframe 크롤링 오류: {iframe_src} - {e}")
            
            # 각 선택자 시도
            for selector in selectors:
                try:
                    article_body = selector(soup)
                    if article_body:
                        # iframe인 경우는 이미 처리했으므로 스킵
                        if article_body.name == 'iframe':
                            continue
                        
                        # 광고나 불필요한 요소 제거
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside', 'div', 'span'], 
                                                          class_=re.compile(r'ad|advertisement|banner|sponsor|promotion|related|recommend|news_end_btn|end_photo_org|photo_area', re.I)):
                            tag.decompose()
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside', 'div'], 
                                                          id=re.compile(r'ad|advertisement|banner|sponsor|promotion', re.I)):
                            tag.decompose()
                        # 일반적인 불필요 요소 제거
                        for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside']):
                            tag.decompose()
                        
                        # 본문 텍스트 추출
                        temp_content = self.extract_text(article_body)
                        
                        # 가장 긴 내용 저장
                        if len(temp_content) > len(best_content):
                            best_content = temp_content
                            content = temp_content
                        
                        # 내용이 충분히 길면 성공으로 간주
                        if len(content) >= 100:  # 100자 이상이면 충분한 본문으로 간주
                            break
                except Exception as e:
                    logger.debug(f"[{self.source_name}] 선택자 시도 오류: {e}")
                    continue
            
            # iframe 내부에서 찾은 내용이 있으면 사용
            if len(best_content) > len(content):
                content = best_content
            
            # 여전히 내용이 짧으면 추가 시도
            if len(content) < 100:
                # 본문 영역을 더 넓게 찾기
                main_content = soup.find('main') or soup.find('div', class_=re.compile(r'main|container', re.I))
                if main_content:
                    # 본문 관련 요소만 추출
                    for tag in main_content.find_all(['script', 'style', 'iframe', 'ins', 'aside', 'header', 'footer', 'nav', 'div'], 
                                                      class_=re.compile(r'header|footer|nav|menu|sidebar|ad|advertisement|comment', re.I)):
                        tag.decompose()
                    temp_content = self.extract_text(main_content)
                    if len(temp_content) > len(content):
                        content = temp_content
                        best_content = temp_content
                
                # 마지막 시도: 모든 p 태그에서 본문 추출 (강화된 버전)
                if len(content) < 100:
                    # 본문 영역 내의 p 태그 우선 추출
                    article_area = soup.find('div', id=re.compile(r'article|news|content|body', re.I)) or \
                                  soup.find('article') or \
                                  soup.find('main') or \
                                  soup.find('div', class_=re.compile(r'article|news|content|body', re.I))
                    
                    search_area = article_area if article_area else soup
                    
                    all_paragraphs = search_area.find_all('p')
                    paragraph_texts = []
                    seen_texts = set()  # 중복 제거
                    
                    for p in all_paragraphs:
                        p_text = self.extract_text(p).strip()
                        # 광고나 불필요한 텍스트 필터링
                        if (len(p_text) > 30 and  # 최소 길이 증가
                            p_text not in seen_texts and
                            not any(keyword in p_text for keyword in [
                                '광고', 'advertisement', 'sponsor', '관련기사', '추천기사', 
                                '기사제공', '무단전재', '저작권', 'copyright',
                                '댓글', '로그인', '회원가입', '구독', '구독하기'
                            ])):
                            paragraph_texts.append(p_text)
                            seen_texts.add(p_text)
                    
                    if paragraph_texts:
                        combined_content = ' '.join(paragraph_texts)
                        if len(combined_content) > len(content):
                            content = combined_content
                            best_content = combined_content
                    
                    # 추가 시도: div 태그 내의 텍스트도 추출 (p 태그가 없는 경우)
                    if len(content) < 100:
                        div_texts = []
                        for div in search_area.find_all('div', class_=re.compile(r'text|content|body|article', re.I)):
                            div_text = self.extract_text(div).strip()
                            if (len(div_text) > 50 and 
                                div_text not in seen_texts and
                                not any(keyword in div_text for keyword in [
                                    '광고', 'advertisement', 'sponsor', '관련기사', '추천기사',
                                    '기사제공', '무단전재', '저작권', 'copyright'
                                ])):
                                div_texts.append(div_text)
                                seen_texts.add(div_text)
                        
                        if div_texts:
                            combined_content = ' '.join(div_texts)
                            if len(combined_content) > len(content):
                                content = combined_content
                                best_content = combined_content
                    
                    # 최종 시도: 페이지의 모든 텍스트 노드에서 본문 추출 (매우 넓은 범위)
                    if len(content) < 50:
                        # 스크립트, 스타일, 메뉴 등 제외하고 본문 영역 찾기
                        body_tag = soup.find('body')
                        if body_tag:
                            # 본문이 아닌 영역 제거
                            for tag in body_tag.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
                                tag.decompose()
                            
                            # 클래스나 ID에 본문 관련 키워드가 있는 div만 추출
                            potential_content_divs = body_tag.find_all('div', 
                                class_=re.compile(r'article|news|content|body|text|view|read', re.I))
                            
                            for div in potential_content_divs:
                                div_text = self.extract_text(div).strip()
                                # 충분히 긴 텍스트만 본문으로 간주
                                if len(div_text) > 100 and div_text not in seen_texts:
                                    # 본문으로 보이는 텍스트인지 확인 (광고나 메뉴 텍스트 제외)
                                    if not any(keyword in div_text[:200] for keyword in [
                                        '메뉴', '로그인', '회원가입', '구독', '광고', 'advertisement'
                                    ]):
                                        if len(div_text) > len(content):
                                            content = div_text
                                            best_content = div_text
                                            seen_texts.add(div_text)
                                            if len(content) >= 200:  # 충분한 본문을 찾으면 중단
                                                break
            
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
                logger.warning(f"[{self.source_name}] 본문 추출 실패 또는 내용 부족: {url} (길이: {len(content)})")
                # 디버깅을 위해 페이지 구조 일부 로깅
                if logger.isEnabledFor(logging.DEBUG):
                    # 주요 div ID/클래스 확인
                    main_divs = soup.find_all('div', id=True)[:5]
                    main_classes = soup.find_all('div', class_=True)[:5]
                    logger.debug(f"  주요 div ID: {[d.get('id') for d in main_divs]}")
                    logger.debug(f"  주요 div 클래스: {[d.get('class') for d in main_classes]}")
            else:
                logger.info(f"[{self.source_name}] 본문 추출 성공: {url} (길이: {len(content)})")
            
            # 최종적으로 가장 긴 내용 사용
            final_content = best_content if len(best_content) > len(content) else content
            
            # 내용이 없어도 빈 문자열 반환 (요약 정보는 상위에서 처리)
            return {
                'content': final_content,
                'published_at': published_at
            }
            
        except Exception as e:
            logger.error(f"[{self.source_name}] 상세 내용 크롤링 오류: {url} - {e}", exc_info=True)
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
    
    def _extract_content_from_soup(self, soup) -> str:
        """Soup 객체에서 본문 추출 (재사용 가능한 메서드)"""
        content = ""
        
        # 본문 추출 선택자들
        content_selectors = [
            lambda s: s.find('div', id='articleBodyContents'),
            lambda s: s.find('div', id='newsEndContents'),
            lambda s: s.find('div', id='articleBody'),
            lambda s: s.find('div', class_='articleBody'),
            lambda s: s.find('article'),
            lambda s: s.find('div', class_=re.compile(r'article.*body|article.*content', re.I)),
            lambda s: s.find('div', id=re.compile(r'article.*body|article.*content', re.I)),
            lambda s: s.find('div', class_=re.compile(r'content|body|text', re.I)),
        ]
        
        for selector in content_selectors:
            try:
                article_body = selector(soup)
                if article_body:
                    # 불필요한 요소 제거
                    for tag in article_body.find_all(['script', 'style', 'iframe', 'ins', 'aside']):
                        tag.decompose()
                    
                    temp_content = self.extract_text(article_body)
                    if len(temp_content) > len(content):
                        content = temp_content
                        if len(content) >= 100:
                            break
            except:
                continue
        
        # p 태그에서 추출 시도
        if len(content) < 100:
            paragraphs = soup.find_all('p')
            paragraph_texts = []
            for p in paragraphs:
                p_text = self.extract_text(p).strip()
                if len(p_text) > 30 and not any(keyword in p_text for keyword in [
                    '광고', 'advertisement', 'sponsor', '관련기사', '추천기사'
                ]):
                    paragraph_texts.append(p_text)
            
            if paragraph_texts:
                combined = ' '.join(paragraph_texts)
                if len(combined) > len(content):
                    content = combined
        
        return content
    
    def extract_stock_codes(self, text: str) -> str:
        """텍스트에서 종목 코드 추출 (부모 클래스의 개선된 로직 사용)"""
        # 부모 클래스의 extract_stock_codes 사용 (종목명 매핑 포함)
        return super().extract_stock_codes(text)

