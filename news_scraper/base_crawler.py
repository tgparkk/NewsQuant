"""
기본 크롤러 클래스
모든 크롤러의 기본 클래스
"""

import requests
from bs4 import BeautifulSoup
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Optional
import logging
import time
import hashlib

logger = logging.getLogger(__name__)

# 주요 종목명 → 종목 코드 매핑 (주요 대형주 중심)
STOCK_NAME_TO_CODE = {
    # 대형주
    '삼성전자': '005930', 'SK하이닉스': '000660', 'NAVER': '035420', '카카오': '035720',
    'LG전자': '066570', '현대차': '005380', '기아': '000270', 'POSCO홀딩스': '005490',
    'POSCO': '005490', '셀트리온': '068270', '아모레퍼시픽': '090430', 'LG화학': '051910',
    '삼성SDI': '006400', 'SK이노베이션': '096770', '한화솔루션': '009830', '롯데케미칼': '011170',
    'LG생활건강': '051900', 'CJ제일제당': '097950', '오리온': '271560', '농심': '004370',
    'LG유플러스': '032640', 'KT': '030200', 'SK텔레콤': '017670', 'KT&G': '033780',
    '신한지주': '055550', 'KB금융': '105560', '하나금융지주': '086790', '우리금융지주': '316140',
    'NH투자증권': '005940', '미래에셋증권': '006800', '한국금융지주': '071050',
    '삼성물산': '028260', '롯데': '004990', '신세계': '004170', '이마트': '139480',
    'GS리테일': '007070', 'CJ올리브네트웍스': '036420', 'GS': '078930',
    '현대중공업': '009540', '두산에너빌리티': '034020', '두산': '000150',
    '한화': '000880', '한화에어로스페이스': '012450', 'LIG넥스원': '079550',
    '한국전력': '015760', '한국가스공사': '036460', 'GS건설': '006360',
    '대한항공': '003490', '아시아나항공': '020560', '제주항공': '089590',
    '삼성바이오로직스': '207940', '셀트리온헬스케어': '091990', '유한양행': '000100',
    '대웅제약': '069620', '녹십자': '006280', 'GC녹십자': '006280',
    # 중형주 및 인기주
    '카카오뱅크': '323410', '토스': '302550', '쿠팡': 'CPNG', '배달의민족': '035720',
    '넷마블': '251270', '엔씨소프트': '036570', '크래프톤': '259960',
    '삼성전기': '009150', '삼성디스플레이': '034730', 'LG디스플레이': '034220',
    'SK바이오팜': '326030', 'SK바이오사이언스': '302440',
    '한화솔루션케미칼': '298000', '롯데정밀화학': '004000',
    '한진': '002320', 'CJ대한통운': '000120', '한진해운': '002320',
    # 금융
    '교보증권': '030610', '대신증권': '003540', '메리츠증권': '008560',
    '한국투자증권': '006200', '키움증권': '039490',
    # 유틸리티
    'SK': '034730', 'LG': '003550', '삼성': '005930', '현대': '005380',
    # 추가 변형명
    '삼성전자주식회사': '005930', 'SK하이닉스주식회사': '000660',
    '네이버': '035420', '카카오톡': '035720',
    # 추가 대형주
    'LG에너지솔루션': '373220', 'LG이노텍': '011070', 'LG디스플레이': '034220',
    'SK하이닉스': '000660', 'SK텔레콤': '017670', 'SK이노베이션': '096770',
    '한화솔루션': '009830', '한화케미칼': '009830', '한화에어로스페이스': '012450',
    '두산': '000150', '두산중공업': '034020', '두산에너빌리티': '034020',
    '현대모비스': '012330', '현대제철': '004020', '현대중공업': '009540',
    '기아': '000270', '기아자동차': '000270',
    '롯데케미칼': '011170', '롯데지주': '004990', '롯데칠성': '005300',
    'CJ': '001040', 'CJ제일제당': '097950', 'CJ대한통운': '000120',
    'GS': '078930', 'GS건설': '006360', 'GS리테일': '007070',
    '신세계': '004170', '이마트': '139480', '롯데마트': '004990',
    # IT/기술주
    '카카오': '035720', '카카오페이': '377300', '카카오뱅크': '323410',
    'NAVER': '035420', '네이버': '035420',
    '엔씨소프트': '036570', '넷마블': '251270', '크래프톤': '259960',
    'LG유플러스': '032640', 'KT': '030200',
    # 바이오/제약
    '셀트리온': '068270', '셀트리온헬스케어': '091990', '삼성바이오로직스': '207940',
    '유한양행': '000100', '대웅제약': '069620', '녹십자': '006280',
    'SK바이오팜': '326030', 'SK바이오사이언스': '302440',
    # 금융
    '신한은행': '055550', 'KB은행': '105560', '하나은행': '086790',
    '우리은행': '316140', 'NH농협은행': '005940',
    # 에너지/화학
    'POSCO': '005490', 'POSCO홀딩스': '005490', '포스코': '005490',
    'LG화학': '051910', '한화케미칼': '009830',
    # 건설/부동산
    '현대건설': '000720', 'GS건설': '006360', '대우건설': '047040',
    # 해운/물류
    '한진': '002320', '한진해운': '002320', 'CJ대한통운': '000120',
    # 항공
    '대한항공': '003490', '아시아나항공': '020560', '제주항공': '089590',
    # 기타
    '한국전력': '015760', '한국가스공사': '036460', 'KT&G': '033780',
    # 추가 종목명 (더 많은 변형 포함)
    '카카오모빌리티': '162025', '카모': '162025', '카카오모빌': '162025',
    '현대오토에버': '307950', '오토에버': '307950',
    '배달의민족': '035720', '우아한형제들': '035720',
    '토스': '302550', '비바리퍼블리카': '302550',
    '쿠팡': 'CPNG', '쿠팡이츠': 'CPNG',
    '네이버파이낸셜': '035420', '네이버페이': '035420',
    '카카오페이': '377300', '카카오뱅크': '323410',
    '한화에너지': '162025', '한화에너지파워': '162025',
    'LG에너지솔루션': '373220', 'LGES': '373220',
    'SK하이닉스': '000660', '하이닉스': '000660',
    '삼성전자': '005930', '삼전': '005930',
    'NAVER': '035420', '네이버': '035420',
    '카카오': '035720', '카톡': '035720',
    '현대차': '005380', '현대자동차': '005380',
    '기아': '000270', '기아자동차': '000270',
    '포스코': '005490', 'POSCO': '005490',
    'LG화학': '051910', 'LG Chem': '051910',
    '셀트리온': '068270', '셀트리온제약': '068270',
    'SK이노베이션': '096770', 'SK인노베이션': '096770',
    '한화솔루션': '009830', '한화케미칼': '009830',
    'LG전자': '066570', 'LG': '066570',
    '삼성SDI': '006400', 'SDI': '006400',
    '아모레퍼시픽': '090430', '아모레': '090430',
    'LG생활건강': '051900', '생활건강': '051900',
    'CJ제일제당': '097950', 'CJ': '097950',
    '롯데': '004990', '롯데지주': '004990',
    '신세계': '004170', '신세계백화점': '004170',
    '이마트': '139480', '이마트몰': '139480',
    'GS리테일': '007070', 'GS': '007070',
    '현대중공업': '009540', '현대중공업지주': '009540',
    '두산에너빌리티': '034020', '두산': '034020',
    '한화에어로스페이스': '012450', '한화항공우주': '012450',
    '대한항공': '003490', '대한항': '003490',
    '아시아나항공': '020560', '아시아나': '020560',
    '제주항공': '089590', '제주항': '089590',
    '삼성바이오로직스': '207940', '삼성바이오': '207940',
    '셀트리온헬스케어': '091990', '셀트리온헬스': '091990',
    '유한양행': '000100', '유한': '000100',
    '대웅제약': '069620', '대웅': '069620',
    '녹십자': '006280', 'GC녹십자': '006280',
    '넷마블': '251270', '넷마블엔터테인먼트': '251270',
    '엔씨소프트': '036570', 'NC소프트': '036570',
    '크래프톤': '259960', '크래프톤게임즈': '259960',
    '신한지주': '055550', '신한금융지주': '055550',
    'KB금융': '105560', 'KB금융지주': '105560',
    '하나금융지주': '086790', '하나금융': '086790',
    '우리금융지주': '316140', '우리금융': '316140',
    'NH투자증권': '005940', 'NH투자': '005940',
    '미래에셋증권': '006800', '미래에셋': '006800',
    '한국금융지주': '071050', '한국금융': '071050',
}


class BaseCrawler(ABC):
    """모든 크롤러의 기본 클래스"""
    
    def __init__(self, source_name: str, headers: Optional[Dict] = None):
        """
        Args:
            source_name: 출처 이름
            headers: HTTP 헤더
        """
        self.source_name = source_name
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1.2 Mobile/15E148 Safari/604.1'
        ]
        import random
        self.headers = headers or {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def generate_news_id(self, url: str, title: str) -> str:
        """
        뉴스 고유 ID 생성
        
        Args:
            url: 뉴스 URL
            title: 뉴스 제목
        
        Returns:
            고유 ID (source_url_hash 형태)
        """
        # URL과 제목을 조합하여 고유 ID 생성
        combined = f"{self.source_name}_{url}_{title}"
        hash_value = hashlib.md5(combined.encode()).hexdigest()[:16]
        return f"{self.source_name}_{hash_value}"
    
    def fetch_page(self, url: str, retries: int = 3, delay: float = 1.0) -> Optional[BeautifulSoup]:
        """
        웹 페이지 가져오기
        
        Args:
            url: 페이지 URL
            retries: 재시도 횟수
            delay: 재시도 전 대기 시간 (초)
        
        Returns:
            BeautifulSoup 객체 또는 None
        """
        # 429 에러 방지를 위한 요청 전 딜레이
        # 사이트별로 다른 딜레이 적용
        request_delay = 0.5  # 기본 딜레이 (초)
        if 'hankyung.com' in url:
            request_delay = 1.0  # 한국경제는 더 긴 딜레이
        elif 'naver.com' in url or 'finance.naver.com' in url:
            request_delay = 0.3  # 네이버는 짧은 딜레이
        elif 'mk.co.kr' in url:
            request_delay = 0.5
        
        # 요청 전 딜레이
        time.sleep(request_delay)
        
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=10)
                
                # 429 에러 발생 시 더 긴 딜레이로 재시도
                if response.status_code == 429:
                    wait_time = delay * (2 ** attempt)  # 지수 백오프
                    logger.warning(f"[{self.source_name}] 429 에러 발생, {wait_time}초 대기 후 재시도...")
                    time.sleep(wait_time)
                    continue
                
                response.raise_for_status()
                
                # HTML에서 charset 메타 태그 확인
                html_content_raw = response.content
                charset = None
                
                # 먼저 HTML의 charset 메타 태그 확인
                try:
                    # 임시로 UTF-8로 디코딩하여 charset 확인
                    temp_html = html_content_raw.decode('utf-8', errors='ignore')
                    if 'charset' in temp_html.lower():
                        import re
                        charset_match = re.search(r'charset\s*=\s*["\']?([^"\'\s>]+)', temp_html, re.IGNORECASE)
                        if charset_match:
                            charset = charset_match.group(1).lower()
                except:
                    pass
                
                # 네이버 금융의 경우 명시적으로 UTF-8 처리
                if 'naver.com' in url or 'finance.naver.com' in url:
                    if not charset:
                        charset = 'utf-8'
                    response.encoding = 'utf-8'
                else:
                    # 인코딩 자동 감지 및 설정
                    if charset:
                        response.encoding = charset
                    elif response.encoding is None or response.encoding.lower() == 'iso-8859-1':
                        # Content-Type 헤더에서 인코딩 추출 시도
                        try:
                            import chardet
                            detected = chardet.detect(response.content)
                            if detected and detected.get('encoding'):
                                response.encoding = detected['encoding']
                            else:
                                response.encoding = 'utf-8'
                        except ImportError:
                            # chardet이 없으면 utf-8 사용
                            response.encoding = 'utf-8'
                
                # response.content를 직접 디코딩하여 처리
                # 여러 인코딩 시도
                html_content = None
                encodings_to_try = ['utf-8', 'euc-kr', 'cp949', 'latin1']
                
                if charset and charset not in encodings_to_try:
                    encodings_to_try.insert(0, charset)
                
                for encoding in encodings_to_try:
                    try:
                        html_content = html_content_raw.decode(encoding, errors='strict')
                        # 한글이 제대로 디코딩되었는지 확인
                        if any('\uac00' <= char <= '\ud7a3' for char in html_content[:1000]):
                            # 한글이 있으면 성공
                            break
                        elif encoding == 'utf-8':
                            # UTF-8인데 한글이 없어도 일단 사용 (영문 페이지일 수 있음)
                            break
                    except (UnicodeDecodeError, UnicodeError):
                        continue
                
                # 모든 인코딩 실패 시 errors='replace'로 처리
                if html_content is None:
                    html_content = html_content_raw.decode('utf-8', errors='replace')
                
                return BeautifulSoup(html_content, 'lxml')
            except requests.exceptions.RequestException as e:
                # 429 에러인 경우 더 긴 딜레이
                if hasattr(e, 'response') and e.response is not None and e.response.status_code == 429:
                    wait_time = delay * (2 ** attempt)  # 지수 백오프
                    logger.warning(f"[{self.source_name}] 429 에러 발생, {wait_time}초 대기 후 재시도...")
                    if attempt < retries - 1:
                        time.sleep(wait_time)
                        continue
                
                logger.warning(f"[{self.source_name}] 페이지 가져오기 실패 (시도 {attempt+1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))  # 재시도 시 딜레이 증가
                else:
                    logger.error(f"[{self.source_name}] 최종 실패: {url}")
                    return None
        
        return None
    
    def parse_datetime(self, date_str: str) -> str:
        """
        날짜 문자열을 ISO 형식으로 변환
        
        Args:
            date_str: 날짜 문자열
        
        Returns:
            ISO 형식 날짜 문자열 (YYYY-MM-DDTHH:MM:SS)
        """
        # 각 크롤러에서 오버라이드하여 구현
        return datetime.now().isoformat()
    
    @abstractmethod
    def crawl_news_list(self, max_pages: int = 5) -> List[Dict]:
        """
        뉴스 목록 크롤링
        
        Args:
            max_pages: 최대 페이지 수
        
        Returns:
            뉴스 데이터 리스트
        """
        pass
    
    @abstractmethod
    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """
        뉴스 상세 내용 크롤링
        
        Args:
            url: 뉴스 URL
        
        Returns:
            뉴스 상세 데이터 딕셔너리 또는 None
        """
        pass
    
    def extract_text(self, element) -> str:
        """
        HTML 요소에서 텍스트 추출
        
        Args:
            element: BeautifulSoup 요소
        
        Returns:
            추출된 텍스트
        """
        if element is None:
            return ""
        
        try:
            text = element.get_text(strip=True, separator=' ')
            # 인코딩 문제가 있는 경우 정리
            if text:
                # 잘못된 바이트 시퀀스 제거
                text = text.replace('\xa0', ' ')
                # replacement character 제거
                text = text.replace('\ufffd', '')
                # 연속된 공백 정리
                text = ' '.join(text.split())
            return text
        except Exception as e:
            logger.debug(f"텍스트 추출 오류: {e}")
            return ""
    
    def extract_stock_codes(self, text: str) -> str:
        """
        텍스트에서 종목 코드 추출 (6자리 숫자 + 종목명 매핑)
        """
        if not text:
            return ""
        
        # 노이즈 제거: 특정 키워드 이후의 텍스트는 제외
        noise_keywords = ['인기검색어', '인기종목', '관련 뉴스', '주요 종목', '증시 현황', '더보기']
        clean_text = text
        for keyword in noise_keywords:
            if keyword in clean_text:
                clean_text = clean_text.split(keyword)[0]
        
        codes = set()
        import re
        
        # 1. 괄호 안의 종목 코드 추출 (예: "삼성전자(005930)", "(005930)") - 가장 정확
        bracket_patterns = [
            r'\((\d{6})\)',  # (005930)
            r'[（(](\d{6})[）)]',  # 전각/반각 괄호 모두
        ]
        for pattern in bracket_patterns:
            bracket_codes = re.findall(pattern, text)
            codes.update(bracket_codes)
        
        # 2. 종목명과 코드가 함께 나오는 패턴 (예: "삼성전자 005930", "005930 삼성전자")
        # 종목명과 6자리 숫자가 인접한 경우
        sorted_stocks = sorted(STOCK_NAME_TO_CODE.items(), key=lambda x: len(x[0]), reverse=True)
        for stock_name, stock_code in sorted_stocks:
            if len(stock_name) >= 2:
                # 패턴 1: "종목명 005930" 또는 "종목명(005930)"
                pattern1 = re.escape(stock_name) + r'[\(\s]*(\d{6})[\)\s]*'
                matches = re.findall(pattern1, text)
                if matches:
                    codes.update(matches)
                
                # 패턴 2: "005930 종목명"
                pattern2 = r'(\d{6})[\(\s]*' + re.escape(stock_name)
                matches = re.findall(pattern2, text)
                if matches:
                    codes.update(matches)
        
        # 3. 종목명으로 추출 (긴 이름부터 매칭하여 정확도 향상)
        for stock_name, stock_code in sorted_stocks:
            if len(stock_name) >= 2:
                # 한국어는 \b(word boundary)가 잘 작동하지 않으므로 앞뒤 문맥 확인
                # 패턴: 앞뒤가 공백, 문장 부호, 또는 시작/끝인 경우
                pattern = r'(?:^|[\s\(\[\{\,\.\?\!\/])' + re.escape(stock_name) + r'(?=$|[\s\)\}\]\,\.\?\!\/])'
                if re.search(pattern, text):
                    codes.add(stock_code)
        
        # 4. 6자리 숫자 패턴으로 직접 추출
        # ... (생략 가능하지만 코드 흐름상 유지)
        # 종목 코드는 보통 0~6으로 시작 (한국 주식 시장 특성)
        numeric_codes = re.findall(r'\b(\d{6})\b', text)
        # 유효한 종목 코드 범위 체크
        valid_codes = [code for code in numeric_codes 
                      if code.startswith(('0', '1', '2', '3', '4', '5', '6')) 
                      and len(code) == 6
                      and not code.startswith('000000')]  # 000000은 유효하지 않음
        codes.update(valid_codes)
        
        # 5. 특수 케이스: 종목명이 제목에 명시적으로 언급된 경우
        # 제목에서 종목명이 언급되면 해당 종목 코드 추가
        # (이미 위에서 처리되지만, 더 명확한 패턴 추가)
        title_keywords = ['주가', '주식', '증권', '종목', '기업', '회사']
        for stock_name, stock_code in sorted_stocks:
            if len(stock_name) >= 2:
                # 종목명 + 키워드 패턴 (예: "삼성전자 주가", "삼성전자 종목")
                for keyword in title_keywords:
                    pattern = re.escape(stock_name) + r'[\s]*' + keyword
                    if re.search(pattern, text, re.IGNORECASE):
                        codes.add(stock_code)
                        break
        
        return ','.join(sorted(codes))
    
    def __del__(self):
        """세션 정리"""
        if hasattr(self, 'session'):
            self.session.close()

