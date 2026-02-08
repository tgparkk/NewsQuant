"""
데이터 품질 조사 패키지

이 패키지는 뉴스 데이터의 품질을 종합적으로 분석하고 평가하는 기능을 제공합니다.
"""

from .quality_checker import check_data_quality

__all__ = ['check_data_quality']

