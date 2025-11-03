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
    
    def __del__(self):
        """세션 정리"""
        if hasattr(self, 'session'):
            self.session.close()

