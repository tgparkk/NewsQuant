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
}


class BaseCrawler(ABC):
    """모든 크롤러의 기본 클래스"""
    
    def __init__(self, source_name: str, headers: Optional[Dict] = None):
        """
        Args:
            source_name: 출처 이름
            headers: HTTP 헤더 (기본 User-Agent 포함)
        """
        self.source_name = source_name
        self.headers = headers or {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=10)
                response.raise_for_status()
                response.encoding = 'utf-8'
                return BeautifulSoup(response.text, 'lxml')
            except requests.exceptions.RequestException as e:
                logger.warning(f"[{self.source_name}] 페이지 가져오기 실패 (시도 {attempt+1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(delay)
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
        return element.get_text(strip=True).replace('\xa0', ' ')
    
    def extract_stock_codes(self, text: str) -> str:
        """
        텍스트에서 종목 코드 추출 (6자리 숫자 + 종목명 매핑)
        
        Args:
            text: 추출할 텍스트
        
        Returns:
            콤마로 구분된 종목 코드 문자열
        """
        if not text:
            return ""
        
        codes = set()
        
        # 1. 6자리 숫자 패턴으로 직접 추출
        import re
        numeric_codes = re.findall(r'\b\d{6}\b', text)
        # 유효한 종목 코드 범위 체크 (000001~999999 중 실제 존재하는 범위)
        valid_codes = [code for code in numeric_codes if code.startswith(('0', '1', '2', '3', '4', '5', '6'))]
        codes.update(valid_codes)
        
        # 2. 종목명으로 추출 (긴 이름부터 매칭하여 정확도 향상)
        sorted_stocks = sorted(STOCK_NAME_TO_CODE.items(), key=lambda x: len(x[0]), reverse=True)
        for stock_name, stock_code in sorted_stocks:
            # 단어 경계를 고려한 매칭 (부분 단어 오매칭 방지)
            pattern = r'\b' + re.escape(stock_name) + r'\b'
            if re.search(pattern, text):
                codes.add(stock_code)
        
        # 3. 괄호 안의 종목명 추출 (예: "삼성전자(005930)")
        bracket_pattern = r'\((\d{6})\)'
        bracket_codes = re.findall(bracket_pattern, text)
        codes.update(bracket_codes)
        
        return ','.join(sorted(codes))
    
    def __del__(self):
        """세션 정리"""
        if hasattr(self, 'session'):
            self.session.close()

