"""
데이터 품질 조사 유틸리티 함수
"""

from datetime import datetime
from typing import Optional


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


def print_section_header(title: str, number: int) -> None:
    """
    섹션 헤더 출력
    
    Args:
        title: 섹션 제목
        number: 섹션 번호
    """
    print(f"[{number}] {title}")
    print("-" * 70)

