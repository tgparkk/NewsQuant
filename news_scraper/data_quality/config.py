"""
데이터 품질 조사 설정 및 타입 정의
"""

from typing import TypedDict
from dataclasses import dataclass

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

