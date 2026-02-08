"""
데이터 품질 통계 계산 함수
"""

from typing import List, Dict, Tuple
from collections import Counter
from datetime import datetime

from .config import (
    RECENT_DAYS,
    TITLE_MIN_LENGTH,
    CONTENT_MIN_LENGTH,
    SCORE_HIGH_THRESHOLD,
    SCORE_MEDIUM_THRESHOLD,
    SentimentStatistics,
    OverallScoreStatistics,
)
from .utils import parse_date_string


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

