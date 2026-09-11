"""
DART(전자공시시스템) 크롤러
Open DART API를 사용하여 공시 정보를 수집합니다.
"""

import os
import logging
from typing import List, Dict, Optional
from datetime import datetime
from ..base_crawler import BaseCrawler
from ..config import get_config

logger = logging.getLogger(__name__)

class DARTCrawler(BaseCrawler):
    """Open DART API를 이용한 공시 수집 크롤러"""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(source_name="dart")
        # config.yaml → 환경 변수 → 인자 순으로 API 키 결정
        self.api_key = api_key or get_config("dart.api_key", "")
        self.base_url = "https://opendart.fss.or.kr/api/list.json"

    def crawl_news_list(self, max_pages: int = 1) -> List[Dict]:
        """
        오늘자 공시 목록 수집
        """
        if not self.api_key or self.api_key == "YOUR_API_KEY_HERE":
            logger.error("[dart] API 키가 설정되지 않았습니다.")
            return []

        # 사이클 시작 시각을 한 번만 찍어 모든 공시가 공유한다.
        # 건마다 datetime.now() 를 부르면 DART 가 «최신순»으로 주기 때문에
        # 가장 새 공시가 가장 이른 시각을 받아 순서가 뒤집힌다.
        collected_at = datetime.now()
        today = collected_at.strftime("%Y%m%d")
        news_list = []
        
        for page in range(1, max_pages + 1):
            params = {
                'crtfc_key': self.api_key,
                'bgn_de': today,
                'end_de': today,
                'page_count': 100,  # 한 페이지 최대 건수
                'page_no': page
            }

            try:
                logger.info(f"[dart] 공시 목록 요청: {today} (페이지: {page})")
                response = self.session.get(self.base_url, params=params, timeout=15)
                response.raise_for_status()
                
                # 인코딩 명시적 설정 (DART API는 UTF-8)
                response.encoding = 'utf-8'
                data = response.json()

                if data.get('status') != '000':
                    if data.get('status') == '013':  # 데이터 없음
                        if page == 1:
                            logger.info("[dart] 오늘 등록된 공시가 아직 없습니다.")
                        break
                    logger.error(f"[dart] API 오류: {data.get('message')} (상태코드: {data.get('status')})")
                    break

                disclosures = data.get('list', [])
                if not disclosures:
                    break

                for item in disclosures:
                    corp_name = item.get('corp_name')
                    report_nm = item.get('report_nm')
                    rcept_no = item.get('rcept_no')
                    stock_code = item.get('stock_code', '').strip()
                    
                    # 뉴스 형식으로 데이터 매핑
                    title = f"[{corp_name}] {report_nm}"
                    # DART 웹 뷰어 주소
                    url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                    
                    # 공시 데이터 생성 - 다단계 종목 코드 추출
                    related_stocks = ""
                    
                    # 1단계: API의 stock_code 사용 (최우선)
                    if stock_code and stock_code != ' ':
                        related_stocks = stock_code
                    
                    # 2단계: 회사명 정확히 매핑 (확장 종목 리스트 사용)
                    if not related_stocks:
                        from ..base_crawler import STOCK_NAME_TO_CODE
                        # 정확한 회사명 매칭
                        related_stocks = STOCK_NAME_TO_CODE.get(corp_name, "")
                        
                        # 회사명 변형 시도
                        if not related_stocks:
                            # "주식회사 삼성전자" → "삼성전자"
                            for prefix in ['주식회사 ', '㈜', '(주)', '(주) ']:
                                if corp_name.startswith(prefix):
                                    clean_name = corp_name[len(prefix):].strip()
                                    related_stocks = STOCK_NAME_TO_CODE.get(clean_name, "")
                                    if related_stocks:
                                        break
                    
                    # 3단계: 제목과 회사명에서 종목 코드 추출
                    if not related_stocks:
                        text_for_extraction = f"{corp_name} {report_nm}"
                        related_stocks = self.extract_stock_codes(text_for_extraction)

                    news_item = {
                        'news_id': self.generate_news_id(url, title),
                        'title': title,
                        'content': f"기업명: {corp_name}\n공시제목: {report_nm}\n접수번호: {rcept_no}\n시장: {item.get('corp_cls')}",
                        'url': url,
                        'source': self.source_name,
                        'category': '공시',
                        'published_at': self.parse_datetime(item.get('rcept_dt', today), now=collected_at),
                        'related_stocks': related_stocks
                    }
                    news_list.append(news_item)

                # 다음 페이지가 있는지 확인 (total_page 필드가 있을 경우 활용 가능하나 여기선 목록 끝이면 종료)
                if len(disclosures) < 100:
                    break

            except Exception as e:
                logger.error(f"[dart] 공시 수집 중 오류 발생 (페이지 {page}): {e}", exc_info=True)
                break

        logger.info(f"[dart] 총 {len(news_list)}건의 공시 수집 완료")
        return news_list

    def crawl_news_detail(self, url: str) -> Optional[Dict]:
        """
        공시 상세 내용은 웹 뷰어 형태이므로, 제목 기반 정보를 우선 사용합니다.
        (필요 시 문서 번문을 가져오는 API 추가 가능)
        """
        return None

    def parse_datetime(self, date_str: str, now: Optional[datetime] = None) -> str:
        """공시 접수 시각을 정한다.

        Open DART list.json 은 «시각을 주지 않는다». 2026-09-12 실측 기준
        응답 필드는 corp_cls·corp_code·corp_name·flr_nm·rcept_dt·rcept_no·
        report_nm·rm·stock_code 뿐이고, rcept_dt 는 YYYYMMDD 다.

        그래서 예전에는 strptime("%Y%m%d") 결과를 그대로 써서 모든 공시가
        자정으로 저장됐다 — DB 기준 149,996건 100%. 그 탓에 장 마감 뒤에
        나온 공시가 섹터 집계 창([직전 평일 15:30, now]) 의 시작보다 앞서서
        통째로 빠졌다. 15:30 이후 접수분이 40.5%(60,709건) 이고, 실적·유상증자·
        공급계약처럼 가장 크게 움직이는 재료가 거기 몰려 있다.

        크롤러는 오늘자만 요청하므로(bgn_de=end_de=today) 목록에 처음 뜬
        공시는 «방금» 접수된 것이다. 그래서 수집 시각을 쓴다. DART 공시검색
        화면과 대조한 실측 오차는 약 1분이다(18:42 공시를 18:43:06 에 수집).
        정확한 접수 시각은 공시검색 HTML 에만 있는데, 하루 653건이 시장별
        5개 탭에 100건씩 쪼개져 있어 사이클마다 7회 넘는 추가 요청이 필요하다.
        1분을 줄이자고 API 크롤러에 페이징 스크레이핑을 붙일 이유가 없다.

        수집 시각은 "우리가 이 정보를 쓸 수 있게 된 시점"이라 백테스트에서
        미래를 참조하지 않는다는 점도 접수 시각보다 낫다.
        """
        now = now or datetime.now()

        try:
            filed_date = datetime.strptime(date_str, "%Y%m%d").date()
        except (ValueError, TypeError):
            logger.warning(f"[dart] 접수일 형식이 예상과 다르다: {date_str!r} — 수집 시각을 쓴다")
            return now.isoformat()

        if filed_date != now.date():
            # 자정 전후에 어제자 공시가 딸려 오는 경우. 날짜 범위를 넓히도록
            # crawl_news_list 를 고쳤다면 여기가 매 건 울린다 — 그때는 접수
            # 시각을 따로 구해 와야 한다.
            logger.warning(
                f"[dart] 접수일({date_str}) 이 오늘({now:%Y%m%d}) 이 아니다 — "
                f"시각을 알 수 없어 수집 시각을 쓴다"
            )

        return now.isoformat()

