"""
DART(전자공시시스템) 크롤러
Open DART API를 사용하여 공시 정보를 수집합니다.
"""

import os
import logging
from typing import List, Dict, Optional
from datetime import datetime
from ..base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

class DARTCrawler(BaseCrawler):
    """Open DART API를 이용한 공시 수집 크롤러"""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(source_name="dart")
        # 전달받은 API 키 사용
        self.api_key = api_key or "bb67ad478f75dd345fd10bd0234205d5917f5e4a"
        self.base_url = "https://opendart.fss.or.kr/api/list.json"

    def crawl_news_list(self, max_pages: int = 1) -> List[Dict]:
        """
        오늘자 공시 목록 수집
        """
        if not self.api_key or self.api_key == "YOUR_API_KEY_HERE":
            logger.error("[dart] API 키가 설정되지 않았습니다.")
            return []

        # 오늘 날짜 (YYYYMMDD)
        today = datetime.now().strftime("%Y%m%d")
        
        params = {
            'crtfc_key': self.api_key,
            'bgn_de': today,
            'end_de': today,
            'page_count': 100,  # 한 페이지 최대 건수
        }

        try:
            logger.info(f"[dart] 공시 목록 요청: {today}")
            response = self.session.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('status') != '000':
                if data.get('status') == '013':  # 데이터 없음
                    logger.info("[dart] 오늘 등록된 공시가 아직 없습니다.")
                    return []
                logger.error(f"[dart] API 오류: {data.get('message')} (상태코드: {data.get('status')})")
                return []

            disclosures = data.get('list', [])
            news_list = []

            for item in disclosures:
                corp_name = item.get('corp_name')
                report_nm = item.get('report_nm')
                rcept_no = item.get('rcept_no')
                stock_code = item.get('stock_code', '')
                
                # 뉴스 형식으로 데이터 매핑
                title = f"[{corp_name}] {report_nm}"
                # DART 웹 뷰어 주소
                url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                
                # 공시 데이터 생성
                # 공시의 경우 corp_name에서만 종목을 추출하거나 stock_code 사용
                related_stocks = stock_code
                if not related_stocks:
                    # corp_name이 STOCK_NAME_TO_CODE에 있는지 확인
                    from ..base_crawler import STOCK_NAME_TO_CODE
                    related_stocks = STOCK_NAME_TO_CODE.get(corp_name, "")
                
                # 그래도 없으면 corp_name 텍스트에서 추출
                if not related_stocks:
                    related_stocks = self.extract_stock_codes(corp_name)

                news_item = {
                    'news_id': self.generate_news_id(url, title),
                    'title': title,
                    'content': f"기업명: {corp_name}\n공시제목: {report_nm}\n접수번호: {rcept_no}\n시장: {item.get('corp_cls')}",
                    'url': url,
                    'source': self.source_name,
                    'category': '공시',
                    'published_at': self.parse_datetime(item.get('rcept_dt', today)),
                    'related_stocks': related_stocks
                }
                news_list.append(news_item)

            logger.info(f"[dart] {len(news_list)}건의 공시 수집 완료")
            return news_list

        except Exception as e:
            logger.error(f"[dart] 공시 수집 중 오류 발생: {e}", exc_info=True)
            return []

    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """
        공시 상세 내용은 웹 뷰어 형태이므로, 제목 기반 정보를 우선 사용합니다.
        (필요 시 문서 번문을 가져오는 API 추가 가능)
        """
        return None

    def parse_datetime(self, date_str: str) -> str:
        """YYYYMMDD 형식을 ISO 형식으로 변환"""
        try:
            dt = datetime.strptime(date_str, "%Y%m%d")
            return dt.isoformat()
        except:
            return datetime.now().isoformat()

