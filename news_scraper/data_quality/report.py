"""
데이터 품질 리포트 출력 함수
"""

from typing import List, Dict
from datetime import datetime

from news_scraper.database import NewsDatabase

from .config import (
    RECENT_DAYS,
    TITLE_MIN_LENGTH,
    CONTENT_MIN_LENGTH,
    SCORE_HIGH_THRESHOLD,
    SCORE_MEDIUM_THRESHOLD,
    CompletenessResult,
)
from .utils import format_number, print_section_header
from .statistics import (
    calculate_completeness,
    get_source_distribution,
    get_date_distribution,
    get_stock_code_distribution,
    calculate_sentiment_statistics,
    calculate_overall_score_statistics,
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

