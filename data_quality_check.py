"""
수집된 뉴스 데이터 품질 조사 스크립트

이 모듈은 데이터베이스에 저장된 뉴스 데이터의 품질을 종합적으로 분석하고 평가합니다.
주요 기능:
- 데이터 완성도 분석 (제목, 내용, URL, 날짜)
- 출처별 및 날짜별 분포 분석
- 종목 코드 추출률 분석
- 감성 분석 및 종합 점수 통계
- 중복 뉴스 체크
- 품질 종합 평가 및 등급 산출
"""

from datetime import datetime
from typing import List, Dict, Tuple, Optional, TypedDict
from dataclasses import dataclass
from news_scraper.database import NewsDatabase
from collections import Counter

# 상수 정의
MAX_FETCH_LIMIT = 100000
RECENT_DAYS = 7

# 완성도 기준값
TITLE_MIN_LENGTH = 5
CONTENT_MIN_LENGTH = 10

# 품질 점수 기준값
QUALITY_EXCELLENT = 95
QUALITY_GOOD = 80
CONTENT_EXCELLENT = 80
CONTENT_GOOD = 60
STOCK_CODE_EXCELLENT = 30
STOCK_CODE_GOOD = 15
SENTIMENT_EXCELLENT = 90
SENTIMENT_GOOD = 70
DUPLICATE_EXCELLENT = 5
DUPLICATE_GOOD = 10

# 등급 기준값
GRADE_A = 90
GRADE_B = 80
GRADE_C = 70
GRADE_D = 60

# 점수 가중치
WEIGHT_TITLE = 20
WEIGHT_CONTENT = 20
WEIGHT_STOCK_CODE = 20
WEIGHT_SENTIMENT = 20
WEIGHT_DUPLICATE = 20

# 종합 점수 임계값
SCORE_HIGH_THRESHOLD = 0.7
SCORE_MEDIUM_THRESHOLD = 0.3
QUALITY_SCORE_GOOD_RATIO = 0.75  # 양호 등급 점수 비율


# 타입 정의
class CompletenessResult(TypedDict):
    """완성도 결과 타입"""
    title: float
    content: float
    url: float
    date: float


class SentimentStatistics(TypedDict):
    """감성 통계 타입"""
    total: int
    positive: int
    negative: int
    neutral: int
    avg_score: float


class OverallScoreStatistics(TypedDict):
    """종합 점수 통계 타입"""
    total: int
    high: int
    medium: int
    low: int
    avg_score: float


@dataclass
class QualityMetricConfig:
    """품질 지표 설정"""
    name: str
    value: float
    excellent_threshold: float
    good_threshold: float
    weight: int
    is_reverse: bool = False  # True면 낮을수록 좋음 (예: 중복률)

def parse_date_string(date_str: str) -> Optional[datetime]:
    """
    날짜 문자열을 datetime 객체로 변환
    
    Args:
        date_str: ISO 형식의 날짜 문자열 (예: "2024-01-15T09:30:00" 또는 "2024-01-15")
        
    Returns:
        변환된 datetime 객체, 변환 실패 시 None
    """
    if not date_str:
        return None
    
    try:
        # ISO 형식 파싱
        if 'T' in date_str:
            date_str = date_str.split('T')[0]
        else:
            date_str = date_str[:10]
        
        return datetime.fromisoformat(date_str)
    except (ValueError, AttributeError):
        return None


def calculate_completeness(data_list: List[Dict], field: str, min_length: int = 0) -> Tuple[float, int, int]:
    """
    필드 완성도 계산
    
    Args:
        data_list: 데이터 리스트
        field: 계산할 필드명
        min_length: 최소 길이 기준 (이 길이 이상이어야 완전한 것으로 간주)
        
    Returns:
        (완성도 %, 완전한 개수, 전체 개수)
        
    Example:
        >>> data = [{'title': 'Test'}, {'title': 'Short'}]
        >>> completeness, complete, total = calculate_completeness(data, 'title', 5)
        >>> completeness  # 50.0 (1개만 5자 이상)
    """
    total = len(data_list)
    if total == 0:
        return 0.0, 0, 0
    
    complete_count = sum(
        1 for item in data_list 
        if item.get(field) and len(str(item.get(field, ''))) >= min_length
    )
    completeness = (complete_count / total) * 100
    
    return completeness, complete_count, total


def print_section_header(title: str, number: int) -> None:
    """
    섹션 헤더 출력
    
    Args:
        title: 섹션 제목
        number: 섹션 번호
    """
    print(f"[{number}] {title}")
    print("-" * 70)


def format_number(value: int) -> str:
    """
    숫자를 천 단위 구분자로 포맷팅
    
    Args:
        value: 포맷팅할 숫자
        
    Returns:
        포맷팅된 문자열 (예: "1,234")
    """
    return f"{value:,}"


def format_percentage(value: float, total: int, decimals: int = 1) -> str:
    """
    퍼센트 포맷팅
    
    Args:
        value: 값
        total: 전체 개수
        decimals: 소수점 자릿수
        
    Returns:
        포맷팅된 퍼센트 문자열 (예: "45.5%")
    """
    if total == 0:
        return "0.0%"
    percentage = (value / total) * 100
    return f"{percentage:.{decimals}f}%"


def get_source_distribution(all_news: List[Dict]) -> Counter:
    """출처별 분포 계산"""
    source_counts = Counter()
    for news in all_news:
        source = news.get('source', 'Unknown')
        source_counts[source] += 1
    return source_counts


def get_date_distribution(all_news: List[Dict], days: int = RECENT_DAYS) -> Counter:
    """최근 N일 날짜별 분포 계산"""
    date_counts = Counter()
    today = datetime.now()
    
    for news in all_news:
        published_at = news.get('published_at', '')
        if published_at:
            date_obj = parse_date_string(published_at)
            if date_obj:
                days_ago = (today - date_obj).days
                if 0 <= days_ago <= days:
                    date_str = date_obj.strftime('%Y-%m-%d')
                    date_counts[date_str] += 1
    
    return date_counts


def get_stock_code_distribution(all_news: List[Dict]) -> Counter:
    """종목 코드 분포 계산"""
    stock_code_counts = Counter()
    for news in all_news:
        stocks = news.get('related_stocks', '')
        if stocks:
            codes = stocks.split(',')
            for code in codes:
                code = code.strip()
                if code:
                    stock_code_counts[code] += 1
    return stock_code_counts


def calculate_sentiment_statistics(all_news: List[Dict]) -> SentimentStatistics:
    """감성 점수 통계 계산"""
    sentiment_scores = [
        n.get('sentiment_score') 
        for n in all_news 
        if n.get('sentiment_score') is not None
    ]
    
    if not sentiment_scores:
        return SentimentStatistics(
            total=0,
            positive=0,
            negative=0,
            neutral=0,
            avg_score=0.0
        )
    
    positive = sum(1 for s in sentiment_scores if s > 0)
    negative = sum(1 for s in sentiment_scores if s < 0)
    neutral = sum(1 for s in sentiment_scores if s == 0)
    avg_score = sum(sentiment_scores) / len(sentiment_scores)
    
    return SentimentStatistics(
        total=len(sentiment_scores),
        positive=positive,
        negative=negative,
        neutral=neutral,
        avg_score=avg_score
    )


def calculate_overall_score_statistics(all_news: List[Dict]) -> OverallScoreStatistics:
    """종합 점수 통계 계산"""
    overall_scores = [
        n.get('overall_score') 
        for n in all_news 
        if n.get('overall_score') is not None
    ]
    
    if not overall_scores:
        return OverallScoreStatistics(
            total=0,
            high=0,
            medium=0,
            low=0,
            avg_score=0.0
        )
    
    high_score = sum(1 for s in overall_scores if s >= SCORE_HIGH_THRESHOLD)
    medium_score = sum(1 for s in overall_scores if SCORE_MEDIUM_THRESHOLD <= s < SCORE_HIGH_THRESHOLD)
    low_score = sum(1 for s in overall_scores if s < SCORE_MEDIUM_THRESHOLD)
    avg_score = sum(overall_scores) / len(overall_scores)
    
    return OverallScoreStatistics(
        total=len(overall_scores),
        high=high_score,
        medium=medium_score,
        low=low_score,
        avg_score=avg_score
    )


def print_total_statistics(all_news: List[Dict]) -> int:
    """
    전체 통계 출력
    
    Args:
        all_news: 전체 뉴스 데이터 리스트
        
    Returns:
        전체 뉴스 개수
    """
    print_section_header("전체 통계", 1)
    total_count = len(all_news)
    print(f"전체 뉴스 개수: {format_number(total_count)}개")
    print()
    return total_count


def print_source_distribution(all_news: List[Dict], total_count: int) -> None:
    """
    출처별 분포 출력
    
    Args:
        all_news: 전체 뉴스 데이터 리스트
        total_count: 전체 뉴스 개수
    """
    print_section_header("출처별 분포", 2)
    source_counts = get_source_distribution(all_news)
    
    for source, count in source_counts.most_common():
        percentage = (count / total_count) * 100
        print(f"  {source:20s}: {format_number(count):>6}개 ({percentage:5.1f}%)")
    print()


def print_date_distribution(all_news: List[Dict], days: int = RECENT_DAYS) -> None:
    """
    날짜별 분포 출력
    
    Args:
        all_news: 전체 뉴스 데이터 리스트
        days: 조회할 최근 일수 (기본값: RECENT_DAYS)
    """
    print_section_header(f"최근 {days}일 날짜별 분포", 3)
    date_counts = get_date_distribution(all_news, days)
    
    if date_counts:
        for date_str in sorted(date_counts.keys(), reverse=True):
            count = date_counts[date_str]
            print(f"  {date_str}: {format_number(count):>6}개")
    else:
        print(f"  최근 {days}일 데이터가 없습니다.")
    print()


def print_data_completeness(all_news: List[Dict], total_count: int) -> CompletenessResult:
    """
    데이터 완성도 출력 및 결과 반환
    
    Args:
        all_news: 전체 뉴스 데이터 리스트
        total_count: 전체 뉴스 개수
        
    Returns:
        각 필드별 완성도 딕셔너리
    """
    print_section_header("데이터 완성도", 4)
    
    title_completeness, title_complete, _ = calculate_completeness(all_news, 'title', TITLE_MIN_LENGTH)
    content_completeness, content_complete, _ = calculate_completeness(all_news, 'content', CONTENT_MIN_LENGTH)
    url_completeness, url_complete, _ = calculate_completeness(all_news, 'url', 0)
    date_completeness, date_complete, _ = calculate_completeness(all_news, 'published_at', 0)
    
    print(f"제목 완성도: {title_completeness:.1f}% ({format_number(title_complete)}/{format_number(total_count)})")
    print(f"내용 완성도: {content_completeness:.1f}% ({format_number(content_complete)}/{format_number(total_count)})")
    print(f"URL 완성도: {url_completeness:.1f}% ({format_number(url_complete)}/{format_number(total_count)})")
    print(f"날짜 완성도: {date_completeness:.1f}% ({format_number(date_complete)}/{format_number(total_count)})")
    print()
    
    return CompletenessResult(
        title=title_completeness,
        content=content_completeness,
        url=url_completeness,
        date=date_completeness
    )


def print_stock_code_statistics(all_news: List[Dict], total_count: int) -> float:
    """
    종목 코드 추출률 출력 및 반환
    
    Args:
        all_news: 전체 뉴스 데이터 리스트
        total_count: 전체 뉴스 개수
        
    Returns:
        종목 코드 추출률 (%)
    """
    print_section_header("종목 코드 추출률", 5)
    
    with_stock_code = sum(
        1 for n in all_news 
        if n.get('related_stocks') and len(str(n.get('related_stocks', ''))) > 0
    )
    stock_code_rate = (with_stock_code / total_count) * 100 if total_count > 0 else 0
    print(f"종목 코드가 있는 뉴스: {format_number(with_stock_code)}개 ({stock_code_rate:.1f}%)")
    
    stock_code_counts = get_stock_code_distribution(all_news)
    if stock_code_counts:
        print(f"\n가장 많이 언급된 종목 코드 (상위 10개):")
        for code, count in stock_code_counts.most_common(10):
            print(f"  {code}: {format_number(count)}회")
    print()
    
    return stock_code_rate


def print_sentiment_statistics(all_news: List[Dict], total_count: int) -> int:
    """
    감성 점수 분포 출력 및 감성 분석된 개수 반환
    
    Args:
        all_news: 전체 뉴스 데이터 리스트
        total_count: 전체 뉴스 개수
        
    Returns:
        감성 분석이 완료된 뉴스 개수
    """
    print_section_header("감성 점수 분포", 6)
    
    stats = calculate_sentiment_statistics(all_news)
    
    if stats['total'] > 0:
        sentiment_rate = (stats['total'] / total_count) * 100
        print(f"감성 분석 완료: {format_number(stats['total'])}개 ({sentiment_rate:.1f}%)")
        print(f"  긍정 (점수 > 0): {format_number(stats['positive'])}개 ({stats['positive']/stats['total']*100:.1f}%)")
        print(f"  중립 (점수 = 0): {format_number(stats['neutral'])}개 ({stats['neutral']/stats['total']*100:.1f}%)")
        print(f"  부정 (점수 < 0): {format_number(stats['negative'])}개 ({stats['negative']/stats['total']*100:.1f}%)")
        print(f"  평균 감성 점수: {stats['avg_score']:.3f}")
    else:
        print("감성 분석이 수행되지 않았습니다.")
    print()
    
    return stats['total']


def print_overall_score_statistics(all_news: List[Dict]) -> None:
    """
    종합 점수 분포 출력
    
    Args:
        all_news: 전체 뉴스 데이터 리스트
    """
    print_section_header("종합 점수 분포", 7)
    
    stats = calculate_overall_score_statistics(all_news)
    
    if stats['total'] > 0:
        print(f"종합 점수 계산 완료: {format_number(stats['total'])}개")
        print(f"  고점수 (≥{SCORE_HIGH_THRESHOLD}): {format_number(stats['high'])}개 ({stats['high']/stats['total']*100:.1f}%)")
        print(f"  중점수 ({SCORE_MEDIUM_THRESHOLD}~{SCORE_HIGH_THRESHOLD}): {format_number(stats['medium'])}개 ({stats['medium']/stats['total']*100:.1f}%)")
        print(f"  저점수 (<{SCORE_MEDIUM_THRESHOLD}): {format_number(stats['low'])}개 ({stats['low']/stats['total']*100:.1f}%)")
        print(f"  평균 종합 점수: {stats['avg_score']:.3f}")
    else:
        print("종합 점수가 계산되지 않았습니다.")
    print()


def print_duplicate_check(all_news: List[Dict], total_count: int) -> float:
    """
    중복 뉴스 체크 출력 및 중복률 반환
    
    Args:
        all_news: 전체 뉴스 데이터 리스트
        total_count: 전체 뉴스 개수
        
    Returns:
        중복률 (%)
    """
    print_section_header("중복 뉴스 체크", 8)
    
    news_ids = [n.get('news_id') for n in all_news if n.get('news_id')]
    unique_ids = set(news_ids)
    duplicate_count = len(news_ids) - len(unique_ids)
    duplicate_rate = (duplicate_count / total_count) * 100 if total_count > 0 else 0
    
    print(f"고유 뉴스 ID: {format_number(len(unique_ids))}개")
    print(f"중복 뉴스: {format_number(duplicate_count)}개 ({duplicate_rate:.1f}%)")
    print()
    
    return duplicate_rate


def print_recent_collection_status(db: NewsDatabase) -> None:
    """
    최근 수집 현황 출력
    
    Args:
        db: NewsDatabase 인스턴스
    """
    print_section_header("최근 수집 현황 (오늘)", 9)
    
    today = datetime.now()
    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    try:
        today_news = db.get_news_by_date_range(
            start_date.isoformat(),
            end_date.isoformat()
        )
        
        print(f"오늘 수집된 뉴스: {format_number(len(today_news))}개")
        
        if today_news:
            today_source_counts = get_source_distribution(today_news)
            print("출처별 분포:")
            for source, count in today_source_counts.most_common():
                print(f"  {source}: {format_number(count)}개")
    except Exception as e:
        print(f"오늘 수집 현황 조회 중 오류 발생: {e}")
    print()


def _evaluate_quality_metric(config: QualityMetricConfig) -> Tuple[int, str]:
    """
    개별 품질 지표 평가
    
    Args:
        config: 품질 지표 설정
        
    Returns:
        (점수, 평가 메시지)
    """
    value = config.value
    
    if config.is_reverse:
        # 낮을수록 좋은 지표 (예: 중복률)
        if value <= config.excellent_threshold:
            return config.weight, f"[OK] {config.name} 우수"
        elif value <= config.good_threshold:
            return int(config.weight * QUALITY_SCORE_GOOD_RATIO), f"[+] {config.name} 양호"
        else:
            return 0, f"[X] {config.name} 개선 필요"
    else:
        # 높을수록 좋은 지표
        if value >= config.excellent_threshold:
            return config.weight, f"[OK] {config.name} 우수"
        elif value >= config.good_threshold:
            return int(config.weight * QUALITY_SCORE_GOOD_RATIO), f"[+] {config.name} 양호"
        else:
            return 0, f"[X] {config.name} 개선 필요"


def calculate_quality_score(
    title_completeness: float,
    content_completeness: float,
    stock_code_rate: float,
    sentiment_rate: float,
    duplicate_rate: float
) -> Tuple[int, List[str]]:
    """품질 종합 점수 계산"""
    quality_score = 0
    quality_items = []
    
    # 품질 지표 설정
    metrics = [
        QualityMetricConfig("제목 완성도", title_completeness, QUALITY_EXCELLENT, QUALITY_GOOD, WEIGHT_TITLE),
        QualityMetricConfig("내용 완성도", content_completeness, CONTENT_EXCELLENT, CONTENT_GOOD, WEIGHT_CONTENT),
        QualityMetricConfig("종목 코드 추출률", stock_code_rate, STOCK_CODE_EXCELLENT, STOCK_CODE_GOOD, WEIGHT_STOCK_CODE),
        QualityMetricConfig("감성 분석 완료율", sentiment_rate, SENTIMENT_EXCELLENT, SENTIMENT_GOOD, WEIGHT_SENTIMENT),
        QualityMetricConfig("중복률", duplicate_rate, DUPLICATE_EXCELLENT, DUPLICATE_GOOD, WEIGHT_DUPLICATE, is_reverse=True),
    ]
    
    # 각 지표 평가
    for metric in metrics:
        score, message = _evaluate_quality_metric(metric)
        quality_score += score
        quality_items.append(message)
    
    return quality_score, quality_items


def get_quality_grade(score: int) -> str:
    """
    품질 점수에 따른 등급 반환
    
    Args:
        score: 품질 점수 (0-100)
        
    Returns:
        등급 문자열 (예: "A (우수)")
    """
    if score >= GRADE_A:
        return "A (우수)"
    elif score >= GRADE_B:
        return "B (양호)"
    elif score >= GRADE_C:
        return "C (보통)"
    elif score >= GRADE_D:
        return "D (미흡)"
    else:
        return "F (불량)"


def print_quality_assessment(
    title_completeness: float,
    content_completeness: float,
    stock_code_rate: float,
    sentiment_rate: float,
    duplicate_rate: float
) -> None:
    """
    품질 종합 평가 출력
    
    Args:
        title_completeness: 제목 완성도 (%)
        content_completeness: 내용 완성도 (%)
        stock_code_rate: 종목 코드 추출률 (%)
        sentiment_rate: 감성 분석 완료율 (%)
        duplicate_rate: 중복률 (%)
    """
    print_section_header("품질 종합 평가", 10)
    
    quality_score, quality_items = calculate_quality_score(
        title_completeness,
        content_completeness,
        stock_code_rate,
        sentiment_rate,
        duplicate_rate
    )
    
    print(f"종합 품질 점수: {quality_score}/100점")
    print()
    print("세부 평가:")
    for item in quality_items:
        print(f"  {item}")
    print()
    
    grade = get_quality_grade(quality_score)
    print(f"등급: {grade}")
    print()


def check_data_quality():
    """데이터 품질 조사"""
    try:
        db = NewsDatabase()
    except Exception as e:
        print("=" * 70)
        print("❌ 데이터베이스 연결 실패")
        print("=" * 70)
        print(f"오류: {e}")
        print("데이터베이스 파일이 존재하는지 확인해주세요.")
        return
    
    try:
        print("=" * 70)
        print("뉴스 데이터 품질 조사 리포트")
        print("=" * 70)
        print(f"조사 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # 전체 뉴스 조회
        all_news = db.get_latest_news(limit=MAX_FETCH_LIMIT)
        total_count = print_total_statistics(all_news)
        
        if total_count == 0:
            print("⚠️  데이터베이스에 뉴스가 없습니다.")
            return
        
        # 각 섹션 실행
        print_source_distribution(all_news, total_count)
        print_date_distribution(all_news, RECENT_DAYS)
        completeness = print_data_completeness(all_news, total_count)
        stock_code_rate = print_stock_code_statistics(all_news, total_count)
        sentiment_count = print_sentiment_statistics(all_news, total_count)
        print_overall_score_statistics(all_news)
        duplicate_rate = print_duplicate_check(all_news, total_count)
        print_recent_collection_status(db)
        
        # 품질 종합 평가
        sentiment_rate = (sentiment_count / total_count) * 100 if total_count > 0 else 0
        print_quality_assessment(
            completeness['title'],
            completeness['content'],
            stock_code_rate,
            sentiment_rate,
            duplicate_rate
        )
        
        print("=" * 70)
    except Exception as e:
        print("\n❌ 오류가 발생했습니다:")
        print(f"  {type(e).__name__}: {e}")
        print("\n자세한 오류 정보를 확인하려면 스크립트를 디버그 모드로 실행하세요.")
        raise

if __name__ == "__main__":
    check_data_quality()

