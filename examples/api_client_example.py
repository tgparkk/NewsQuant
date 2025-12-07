"""
NewsQuant API 클라이언트 예제
다른 프로그램에서 NewsQuant API를 사용하는 방법을 보여주는 예제 코드
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# API 기본 URL
API_BASE = "http://127.0.0.1:8000"


def get_latest_news(limit: int = 50, min_score: Optional[float] = None) -> List[Dict]:
    """
    최신 뉴스 조회
    
    Args:
        limit: 조회 개수
        min_score: 최소 종합 점수
    
    Returns:
        뉴스 리스트
    """
    params = {"limit": limit}
    if min_score is not None:
        params["min_score"] = min_score
    
    response = requests.get(f"{API_BASE}/api/news/latest", params=params)
    response.raise_for_status()
    
    data = response.json()
    return data["data"]


def get_news_by_date(start_date: str, end_date: str, source: Optional[str] = None) -> List[Dict]:
    """
    날짜 범위로 뉴스 조회
    
    Args:
        start_date: 시작일시 (ISO 형식)
        end_date: 종료일시 (ISO 형식)
        source: 출처 필터
    
    Returns:
        뉴스 리스트
    """
    params = {
        "start_date": start_date,
        "end_date": end_date
    }
    if source:
        params["source"] = source
    
    response = requests.get(f"{API_BASE}/api/news/date", params=params)
    response.raise_for_status()
    
    data = response.json()
    return data["data"]


def get_news_by_stock(stock_code: str, limit: int = 50) -> List[Dict]:
    """
    특정 종목 관련 뉴스 조회
    
    Args:
        stock_code: 종목 코드 (6자리, 예: "005930")
        limit: 조회 개수
    
    Returns:
        뉴스 리스트
    """
    response = requests.get(
        f"{API_BASE}/api/news/stock/{stock_code}",
        params={"limit": limit}
    )
    response.raise_for_status()
    
    data = response.json()
    return data["data"]


def search_news(
    keyword: Optional[str] = None,
    min_sentiment: Optional[float] = None,
    max_sentiment: Optional[float] = None,
    min_overall_score: Optional[float] = None,
    source: Optional[str] = None,
    limit: int = 100
) -> List[Dict]:
    """
    뉴스 검색 (고급 필터링)
    
    Args:
        keyword: 키워드 검색
        min_sentiment: 최소 감성 점수
        max_sentiment: 최대 감성 점수
        min_overall_score: 최소 종합 점수
        source: 출처 필터
        limit: 조회 개수
    
    Returns:
        뉴스 리스트
    """
    params = {"limit": limit}
    
    if keyword:
        params["keyword"] = keyword
    if min_sentiment is not None:
        params["min_sentiment"] = min_sentiment
    if max_sentiment is not None:
        params["max_sentiment"] = max_sentiment
    if min_overall_score is not None:
        params["min_overall_score"] = min_overall_score
    if source:
        params["source"] = source
    
    response = requests.get(f"{API_BASE}/api/news/search", params=params)
    response.raise_for_status()
    
    data = response.json()
    return data["data"]


def get_statistics(days: int = 7) -> Dict:
    """
    수집 통계 조회
    
    Args:
        days: 최근 N일간 통계
    
    Returns:
        통계 딕셔너리
    """
    response = requests.get(f"{API_BASE}/api/stats", params={"days": days})
    response.raise_for_status()
    
    data = response.json()
    return data["data"]


def health_check() -> bool:
    """
    API 서버 건강 상태 확인
    
    Returns:
        정상 여부
    """
    try:
        response = requests.get(f"{API_BASE}/api/health", timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get("status") == "healthy"
    except Exception:
        return False


# 사용 예제
if __name__ == "__main__":
    print("=" * 60)
    print("NewsQuant API 클라이언트 예제")
    print("=" * 60)
    
    # 1. 건강 상태 체크
    print("\n1. API 서버 건강 상태 확인...")
    if health_check():
        print("✅ API 서버가 정상적으로 작동 중입니다.")
    else:
        print("❌ API 서버에 연결할 수 없습니다.")
        print("   NewsQuant가 실행 중인지 확인하세요.")
        exit(1)
    
    # 2. 최신 뉴스 조회
    print("\n2. 최신 뉴스 조회 (상위 10개, 종합 점수 0.5 이상)...")
    try:
        latest_news = get_latest_news(limit=10, min_score=0.5)
        print(f"   조회된 뉴스: {len(latest_news)}개")
        for i, news in enumerate(latest_news[:3], 1):
            print(f"   {i}. {news.get('title', 'N/A')[:50]}...")
            print(f"      점수: {news.get('overall_score', 'N/A')}")
    except Exception as e:
        print(f"   오류: {e}")
    
    # 3. 오늘 뉴스 조회
    print("\n3. 오늘 뉴스 조회...")
    try:
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        today_news = get_news_by_date(
            start_date=yesterday.isoformat(),
            end_date=today.isoformat()
        )
        print(f"   조회된 뉴스: {len(today_news)}개")
    except Exception as e:
        print(f"   오류: {e}")
    
    # 4. 삼성전자 관련 뉴스 조회
    print("\n4. 삼성전자(005930) 관련 뉴스 조회...")
    try:
        samsung_news = get_news_by_stock("005930", limit=5)
        print(f"   조회된 뉴스: {len(samsung_news)}개")
        for i, news in enumerate(samsung_news[:3], 1):
            print(f"   {i}. {news.get('title', 'N/A')[:50]}...")
    except Exception as e:
        print(f"   오류: {e}")
    
    # 5. 검색 예제 (긍정적인 뉴스만)
    print("\n5. 긍정적인 뉴스 검색 (감성 점수 0.5 이상)...")
    try:
        positive_news = search_news(min_sentiment=0.5, limit=10)
        print(f"   조회된 뉴스: {len(positive_news)}개")
    except Exception as e:
        print(f"   오류: {e}")
    
    # 6. 통계 조회
    print("\n6. 수집 통계 조회 (최근 7일)...")
    try:
        stats = get_statistics(days=7)
        print(f"   전체 뉴스: {stats.get('total_news', 0):,}개")
        print("   출처별 뉴스:")
        for source, count in stats.get('by_source', {}).items():
            print(f"     - {source}: {count:,}개")
    except Exception as e:
        print(f"   오류: {e}")
    
    print("\n" + "=" * 60)
    print("예제 완료!")
    print("=" * 60)
