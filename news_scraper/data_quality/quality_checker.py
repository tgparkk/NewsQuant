"""
데이터 품질 조사 메인 로직
"""

from typing import List, Tuple
from datetime import datetime

from news_scraper.database import NewsDatabase

from .config import (
    MAX_FETCH_LIMIT,
    RECENT_DAYS,
    QUALITY_EXCELLENT,
    QUALITY_GOOD,
    CONTENT_EXCELLENT,
    CONTENT_GOOD,
    STOCK_CODE_EXCELLENT,
    STOCK_CODE_GOOD,
    SENTIMENT_EXCELLENT,
    SENTIMENT_GOOD,
    DUPLICATE_EXCELLENT,
    DUPLICATE_GOOD,
    WEIGHT_TITLE,
    WEIGHT_CONTENT,
    WEIGHT_STOCK_CODE,
    WEIGHT_SENTIMENT,
    WEIGHT_DUPLICATE,
    QUALITY_SCORE_GOOD_RATIO,
    GRADE_A,
    GRADE_B,
    GRADE_C,
    GRADE_D,
    QualityMetricConfig,
)
from .report import (
    print_total_statistics,
    print_source_distribution,
    print_date_distribution,
    print_data_completeness,
    print_stock_code_statistics,
    print_sentiment_statistics,
    print_overall_score_statistics,
    print_duplicate_check,
    print_recent_collection_status,
    print_section_header,
)


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

