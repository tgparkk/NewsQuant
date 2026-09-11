"""
기본 크롤러 클래스
모든 크롤러의 기본 클래스
"""

import requests
from bs4 import BeautifulSoup
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, NamedTuple, Optional
import logging
import re
import time
import hashlib
from collections import Counter

from news_scraper.http_guard import (
    AdaptiveDelay,
    CircuitBreaker,
    FailedUrlCache,
    is_retryable_status,
)

# 소스별 기본 요청 간격(초). 429 를 맞으면 AdaptiveDelay 가 여기서부터 늘린다.
BASE_REQUEST_DELAY = {
    'hankyung': 1.0,
    'naver_finance': 0.3,
    'mk_news': 0.5,
}
DEFAULT_REQUEST_DELAY = 0.5

# 크롤러 스스로 접는 시간 예산(초). 스케줄러의 CRAWLER_TIMEOUT(300) 보다 짧게 둬서
# 타임아웃 회수 경로로 빠지지 않고 정상 반환하게 한다.
DEFAULT_TIME_BUDGET = 240

# 모든 크롤러가 쓰는 고정 User-Agent (최신 데스크톱 Chrome).
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
)

# HTML 의 charset 메타 태그에서 인코딩을 뽑는다
_CHARSET_RE = re.compile(r'charset\s*=\s*["\']?([^"\'\s>]+)', re.IGNORECASE)

logger = logging.getLogger(__name__)

# 주요 종목명 → 종목 코드 매핑
# 기본 목록 (주요 대형주 + 자주 언급되는 종목)
STOCK_NAME_TO_CODE_BASE = {
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
    'LG전자': '066570',
    '삼성SDI': '006400', 'SDI': '006400',
    '아모레퍼시픽': '090430', '아모레': '090430',
    'LG생활건강': '051900', '생활건강': '051900',
    'CJ제일제당': '097950',
    '롯데': '004990', '롯데지주': '004990',
    '신세계': '004170', '신세계백화점': '004170',
    '이마트': '139480', '이마트몰': '139480',
    'GS리테일': '007070',
    '현대중공업': '009540', '현대중공업지주': '009540',
    '두산에너빌리티': '034020',
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

# 확장 종목 리스트 로드 (네이버 금융에서 수집한 전체 종목)
try:
    import os
    import sys
    # stock_codes_extended.py 파일을 동적으로 import
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    sys.path.insert(0, parent_dir)
    
    try:
        from stock_codes_extended import EXTENDED_STOCK_CODES
        # 기본 목록과 확장 목록 병합 (기본 목록이 우선)
        STOCK_NAME_TO_CODE = {**EXTENDED_STOCK_CODES, **STOCK_NAME_TO_CODE_BASE}
        logger.info(f"확장 종목 리스트 로드 완료: {len(STOCK_NAME_TO_CODE)}개 종목")
    except ImportError:
        # 확장 파일이 없으면 기본 목록만 사용
        STOCK_NAME_TO_CODE = STOCK_NAME_TO_CODE_BASE
        logger.warning("확장 종목 리스트 없음, 기본 목록 사용")
except Exception as e:
    STOCK_NAME_TO_CODE = STOCK_NAME_TO_CODE_BASE
    logger.error(f"종목 리스트 로드 오류: {e}")




# ---------------------------------------------------------------------------
# 종목 추출용 정규식
#
# 종목 사전이 2,155개라 기사마다 패턴을 새로 만들면 Python 의 정규식
# 캐시(512개)를 넘겨 매번 전부 재컴파일된다 (실측 기사 1건당 574ms).
# 사전은 임포트 시점에 고정이므로 «한 번만» 컴파일해 재사용한다.
# ---------------------------------------------------------------------------

# 종목명 + 이 키워드가 붙으면 해당 종목을 언급한 것으로 본다
TITLE_KEYWORDS = ('주가', '주식', '증권', '종목', '기업', '회사')

_BRACKET_PATTERNS = (
    re.compile(r'\((\d{6})\)'),          # (005930)
    re.compile(r'[（(](\d{6})[）)]'),     # 전각/반각 괄호 모두
)
_NUMERIC_CODE_RE = re.compile(r'\b(\d{6})\b')
_DATE_AMOUNT_RE = re.compile(
    r'(?:20\d{2}[년/\-\.]?\s*\d{0,2}|'   # 2024년, 2024/, 2024-
    r'\d{1,3}[,\.]\d{3}|'                 # 100,000 등 금액
    r'\d+억|\d+만|\d+원|\d+조|'            # 금액 단위
    r'\d{2,4}[년월일])'                    # 날짜 단위
)


class _StockPatterns(NamedTuple):
    """종목 하나에 대해 미리 컴파일해 둔 패턴 묶음."""
    code: str
    lowered: str                        # 선필터용 소문자 종목명
    name_then_code: 're.Pattern'        # "삼성전자 005930"
    code_then_name: 're.Pattern'        # "005930 삼성전자"
    standalone: 're.Pattern'            # 앞뒤가 공백/문장부호인 "삼성전자"
    with_keyword: tuple                 # "삼성전자 주가" 등


_STOCK_PATTERN_CACHE: Optional[Dict[str, _StockPatterns]] = None


def _stock_patterns() -> Dict[str, _StockPatterns]:
    """종목별 패턴을 최초 호출 때 한 번만 만든다 (긴 이름부터)."""
    global _STOCK_PATTERN_CACHE
    if _STOCK_PATTERN_CACHE is not None:
        return _STOCK_PATTERN_CACHE

    built = {}
    for stock_name, stock_code in sorted(
        STOCK_NAME_TO_CODE.items(), key=lambda x: len(x[0]), reverse=True
    ):
        if len(stock_name) < 2:
            continue
        escaped = re.escape(stock_name)
        built[stock_name] = _StockPatterns(
            code=stock_code,
            lowered=stock_name.lower(),
            name_then_code=re.compile(escaped + r'[\(\s]*(\d{6})[\)\s]*'),
            code_then_name=re.compile(r'(\d{6})[\(\s]*' + escaped),
            # 한국어는 \b 가 잘 안 먹으므로 앞뒤 문맥을 직접 확인한다
            standalone=re.compile(
                r'(?:^|[\s\(\[\{\,\.\?\!\/])' + escaped + r'(?=$|[\s\)\}\]\,\.\?\!\/])'
            ),
            with_keyword=tuple(
                re.compile(escaped + r'[\s]*' + kw, re.IGNORECASE)
                for kw in TITLE_KEYWORDS
            ),
        )

    _STOCK_PATTERN_CACHE = built
    return built


VALID_STOCK_CODES = frozenset(STOCK_NAME_TO_CODE.values())


class BaseCrawler(ABC):
    """모든 크롤러의 기본 클래스"""
    
    def __init__(
        self,
        source_name: str,
        headers: Optional[Dict] = None,
        *,
        failure_threshold: int = 5,
        failure_cooldown: float = 300,
        max_request_delay: float = 8.0,
        failed_url_ttl: float = 21600,
        time_budget: Optional[float] = DEFAULT_TIME_BUDGET,
        clock=time.monotonic,
    ):
        """
        Args:
            source_name:       출처 이름
            headers:           HTTP 헤더
            failure_threshold: 회로를 여는 연속 실패 횟수
            failure_cooldown:  회로가 열린 뒤 시험 요청까지 기다리는 시간(초)
            max_request_delay: 429 로 늘어날 수 있는 요청 간격의 상한(초)
            failed_url_ttl:    403/404 난 URL 을 기억하는 시간(초)
            time_budget:       한 사이클에 쓸 수 있는 시간(초). None 이면 무제한
            clock:             단조 시계 (테스트에서 주입)
        """
        self.source_name = source_name
        self._clock = clock
        self._time_budget = time_budget
        self._cycle_started_at: Optional[float] = None
        self._breaker = CircuitBreaker(
            threshold=failure_threshold, cooldown=failure_cooldown
        )
        self._failed_urls = FailedUrlCache(ttl=failed_url_ttl)
        self._failed_url_ttl_hours = failed_url_ttl / 3600
        self._delay = AdaptiveDelay(
            base=BASE_REQUEST_DELAY.get(source_name, DEFAULT_REQUEST_DELAY),
            maximum=max_request_delay,
        )
        self._stats = self._fresh_stats()
        # UA 는 하나로 고정한다. 무작위 풀은 차단 대상을 (IP x UA 5개) 로 넓히고,
        # UA 마다 결과가 달라져 429 신호를 가렸다 (2026-09-11 한국경제 차단 사례).
        self.headers = headers or {
            'User-Agent': DEFAULT_USER_AGENT,
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
    
    # ---------------------------------------------------------------- 사이클
    def _fresh_stats(self) -> Dict:
        return {
            'requests': 0,        # 실제로 요청을 시도한 fetch_page 호출 수
            'success': 0,
            'skipped': 0,         # 캐시/회로/예산 때문에 요청조차 안 나간 수
            'errors': 0,          # 네트워크 예외로 끝난 수
            'bad_payload': 0,     # 200 인데 JSON 이 아니었던 수
            'status': Counter(),  # 실패로 끝난 fetch_page 호출의 대표 상태코드
        }

    def begin_cycle(self) -> None:
        """수집 사이클 시작을 알린다.

        통계를 비우고 시간 예산 시계를 켠다. 회로도 여기서 닫는다 -
        쿨다운을 끝까지 기다리느라 소스를 통째로 잃지 않도록 매 사이클
        새 기회를 준다. 실패 URL 캐시는 TTL 로 살아 있어 그대로 둔다.
        """
        self._cycle_started_at = self._clock()
        self._stats = self._fresh_stats()
        self._breaker.reset()
        self._failed_urls.purge_expired()

    def request_delay(self) -> float:
        """지금 적용 중인 요청 간격(초). 429 를 맞으면 늘어난다."""
        return self._delay.current()

    def budget_exhausted(self) -> bool:
        """이번 사이클의 시간 예산을 다 썼는가."""
        if self._time_budget is None or self._cycle_started_at is None:
            return False
        return self._clock() - self._cycle_started_at > self._time_budget

    def cycle_summary(self) -> str:
        """이번 사이클을 한 줄로 요약한다.

        143만 줄을 grep 하지 않고 «어느 소스가 왜 아픈지»를 보기 위한 줄이다.
        """
        stats = self._stats
        if not stats['requests'] and not stats['skipped']:
            # 이 크롤러는 fetch_page 를 쓰지 않는다 (dart·global_news 는 자체 HTTP/RSS).
            # '요청 0 · 성공 0' 을 찍으면 «아무것도 안 했다»로 오해된다.
            return ""
        parts = [f"요청 {stats['requests']}", f"성공 {stats['success']}"]
        for status in sorted(stats['status']):
            parts.append(f"{status} {stats['status'][status]}")
        if stats['errors']:
            parts.append(f"네트워크오류 {stats['errors']}")
        if stats['bad_payload']:
            parts.append(f"응답형식오류 {stats['bad_payload']}")
        parts.append(f"생략 {stats['skipped']}")
        if self._breaker.state != "closed":
            parts.append(f"차단기 {self._breaker.state.upper()}")
        if self._cycle_started_at is not None:
            parts.append(f"소요 {self._clock() - self._cycle_started_at:.0f}s")
        return f"[{self.source_name}] " + " · ".join(parts)

    # ---------------------------------------------------------------- 요청
    def _guarded_get(self, url: str, retries: int, delay: float,
                     params: Optional[Dict] = None):
        """가드를 통과시킨 뒤 GET 을 보내고 성공 응답을 돌려준다.

        요청 전에 세 가지 가드를 통과해야 한다:
          1. 실패 URL 캐시 - 403/404 났던 URL 은 TTL 동안 다시 두드리지 않는다
          2. 시간 예산      - 사이클 예산을 넘겼으면 남은 수집을 접는다
          3. 회로 차단기    - 연속 실패가 임계에 닿았으면 즉시 포기한다

        재시도는 «결과가 바뀔 수 있는» 실패에만 한다. 403/404 같은 영구 실패는
        한 번만 요청하고 URL 을 캐시에 넣는다.

        Returns:
            성공한 Response, 또는 실패했으면 None
        """
        if self._failed_urls.is_blocked(url):
            self._stats['skipped'] += 1
            logger.debug(f"[{self.source_name}] 실패 이력으로 생략: {url}")
            return None

        if self.budget_exhausted():
            self._stats['skipped'] += 1
            logger.debug(f"[{self.source_name}] 시간 예산 소진으로 생략: {url}")
            return None

        if not self._breaker.allows_request():
            self._stats['skipped'] += 1
            logger.debug(f"[{self.source_name}] 회로 열림으로 생략: {url}")
            return None

        self._stats['requests'] += 1
        last_status: Optional[int] = None
        last_error: Optional[Exception] = None

        for attempt in range(retries):
            time.sleep(self._delay.current())
            try:
                response = self.session.get(url, timeout=10, params=params)
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.debug(f"[{self.source_name}] 요청 예외 (시도 {attempt+1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))
                continue

            status = response.status_code
            last_status = status

            if status == 429:
                # 우리가 너무 빨리 두드렸다. 간격을 늘리고 물러선다.
                self._delay.penalize()
                logger.debug(f"[{self.source_name}] 429 - 요청 간격을 늘린다")
                if attempt < retries - 1:
                    time.sleep(delay * (2 ** attempt))
                continue

            if status >= 400:
                if not is_retryable_status(status):
                    # 재시도해도 같은 답이 온다. 한 번으로 끝내고 URL 을 기억한다.
                    self._failed_urls.record(url)
                    self._stats['status'][status] += 1
                    self._breaker.record_failure()
                    logger.warning(
                        f"[{self.source_name}] {status} - 재시도 없이 포기하고 "
                        f"{self._failed_url_ttl_hours:.0f}시간 차단: {url}"
                    )
                    self._log_if_breaker_open()
                    return None
                logger.debug(f"[{self.source_name}] {status} (시도 {attempt+1}/{retries}): {url}")
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))
                continue

            self._stats['success'] += 1
            self._breaker.record_success()
            self._delay.reward()
            return response

        # 재시도를 모두 소진했다.
        if last_status is not None:
            self._stats['status'][last_status] += 1
        else:
            self._stats['errors'] += 1
        self._breaker.record_failure()
        reason = f"HTTP {last_status}" if last_status is not None else str(last_error)
        logger.warning(f"[{self.source_name}] {retries}회 시도 후 실패 ({reason}): {url}")
        self._log_if_breaker_open()
        return None

    def fetch_page(self, url: str, retries: int = 3, delay: float = 1.0) -> Optional[BeautifulSoup]:
        """
        웹 페이지를 가져와 파싱한다 (가드는 _guarded_get 참고).

        Args:
            url: 페이지 URL
            retries: 재시도 횟수 (일시적 실패에만 적용)
            delay: 재시도 백오프의 기준 시간 (초)

        Returns:
            BeautifulSoup 객체 또는 None
        """
        response = self._guarded_get(url, retries, delay)
        if response is None:
            return None
        return self._parse_response(response, url)

    def fetch_json(self, url: str, params: Optional[Dict] = None,
                   retries: int = 3, delay: float = 1.0) -> Optional[Dict]:
        """
        JSON API 를 호출한다 (가드는 _guarded_get 참고).

        200 을 받았어도 JSON 이 아니면 None 을 돌려준다 - API 가 바뀌어
        HTML 오류 페이지를 주는 상황을 «성공»으로 넘기면 안 된다.

        Args:
            url: API URL
            params: 쿼리 파라미터
            retries: 재시도 횟수
            delay: 재시도 백오프의 기준 시간 (초)

        Returns:
            파싱된 JSON (dict/list) 또는 None
        """
        response = self._guarded_get(url, retries, delay, params=params)
        if response is None:
            return None
        try:
            return response.json()
        except ValueError as e:
            self._stats['bad_payload'] += 1
            logger.warning(f"[{self.source_name}] JSON 응답이 아니다 ({e}): {url}")
            return None

    def _log_if_breaker_open(self) -> None:
        """회로가 막 열렸다면 알린다. 이게 실제로 조치가 필요한 사건이다."""
        if self._breaker.state == "open":
            logger.error(
                f"[{self.source_name}] 연속 실패로 회로 차단 - "
                f"이번 사이클의 남은 요청을 건너뛴다"
            )

    @staticmethod
    def _parse_response(response, url: str) -> BeautifulSoup:
        """응답 바이트의 인코딩을 추정해 디코딩하고 파싱한다."""
        html_content_raw = response.content
        charset = None

        # HTML 의 charset 메타 태그를 먼저 본다
        try:
            temp_html = html_content_raw.decode('utf-8', errors='ignore')
            if 'charset' in temp_html.lower():
                charset_match = _CHARSET_RE.search(temp_html)
                if charset_match:
                    charset = charset_match.group(1).lower()
        except Exception:
            pass

        # 네이버 금융은 UTF-8 로 못박는다
        if 'naver.com' in url:
            charset = charset or 'utf-8'

        encodings_to_try = ['utf-8', 'euc-kr', 'cp949', 'latin1']
        if charset and charset not in encodings_to_try:
            encodings_to_try.insert(0, charset)

        html_content = None
        for encoding in encodings_to_try:
            try:
                html_content = html_content_raw.decode(encoding, errors='strict')
                # 한글이 제대로 나왔으면 성공
                if any('가' <= char <= '힣' for char in html_content[:1000]):
                    break
                if encoding == 'utf-8':
                    # UTF-8 인데 한글이 없어도 일단 쓴다 (영문 페이지일 수 있다)
                    break
            except (UnicodeDecodeError, UnicodeError):
                continue

        if html_content is None:
            html_content = html_content_raw.decode('utf-8', errors='replace')

        return BeautifulSoup(html_content, 'lxml')

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

        종목 사전이 2,155개라 기사 1건마다 정규식을 새로 만들면 Python 의
        정규식 캐시(512개)를 넘겨 «매번 전부 재컴파일»된다. 그래서
          1. 종목별 패턴은 모듈 수준에서 한 번만 컴파일하고
          2. 종목명이 텍스트에 «문자열로도» 없으면 정규식을 아예 건너뛴다
        매칭 규칙 자체는 바꾸지 않는다 - 선필터는 정규식이 요구하는
        종목명 리터럴이 없으면 어차피 매칭될 수 없다는 사실만 이용한다.
        """
        if not text:
            return ""

        codes = set()
        patterns = _stock_patterns()
        # 선필터용. 섹션5 가 IGNORECASE 를 쓰므로 소문자로 맞춰 «놓치는 일이 없게» 한다.
        text_lower = text.lower()

        # 1. 괄호 안의 종목 코드 추출 (예: "삼성전자(005930)") - 가장 정확
        for pattern in _BRACKET_PATTERNS:
            codes.update(pattern.findall(text))

        # 2~5. 종목명이 텍스트에 등장하는 것만 실제로 검사한다
        for stock_name, entry in patterns.items():
            if entry.lowered not in text_lower:
                continue

            stock_code = entry.code

            # 2. 종목명과 코드가 인접한 패턴 ("삼성전자 005930", "005930 삼성전자")
            codes.update(entry.name_then_code.findall(text))
            codes.update(entry.code_then_name.findall(text))

            # 3. 종목명으로 추출 (앞뒤가 공백/문장부호/문장 경계인 경우만)
            if entry.standalone.search(text):
                codes.add(stock_code)

            # 5. 종목명 + 키워드 패턴 ("삼성전자 주가", "삼성전자 종목")
            for keyword_pattern in entry.with_keyword:
                if keyword_pattern.search(text):
                    codes.add(stock_code)
                    break

        # 4. 6자리 숫자 패턴으로 직접 추출 — 알려진 종목 코드만 허용
        # (날짜, 금액 등 오인식 방지)
        for code in _NUMERIC_CODE_RE.findall(text):
            if code not in VALID_STOCK_CODES:
                continue
            # 텍스트에서 해당 코드 위치를 찾아 주변 문맥 확인
            code_pos = text.find(code)
            if code_pos >= 0:
                context = text[max(0, code_pos - 10):code_pos + 10]
                if _DATE_AMOUNT_RE.search(context):
                    continue
            codes.add(code)

        return ','.join(sorted(codes))

    def __del__(self):
        """세션 정리"""
        if hasattr(self, 'session'):
            self.session.close()

