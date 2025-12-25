"""
수집된 뉴스 데이터 품질 조사 스크립트
"""

from datetime import datetime
from typing import List, Dict, Tuple, Optional
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

def parse_date_string(date_str: str) -> Optional[datetime]:
    """날짜 문자열을 datetime 객체로 변환"""
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
    
    Returns:
        (완성도 %, 완전한 개수, 전체 개수)
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
    """섹션 헤더 출력"""
    print(f"[{number}] {title}")
    print("-" * 70)


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


def calculate_sentiment_statistics(all_news: List[Dict]) -> Dict:
    """감성 점수 통계 계산"""
    sentiment_scores = [
        n.get('sentiment_score') 
        for n in all_news 
        if n.get('sentiment_score') is not None
    ]
    
    if not sentiment_scores:
        return {
            'total': 0,
            'positive': 0,
            'negative': 0,
            'neutral': 0,
            'avg_score': 0.0
        }
    
    positive = sum(1 for s in sentiment_scores if s > 0)
    negative = sum(1 for s in sentiment_scores if s < 0)
    neutral = sum(1 for s in sentiment_scores if s == 0)
    avg_score = sum(sentiment_scores) / len(sentiment_scores)
    
    return {
        'total': len(sentiment_scores),
        'positive': positive,
        'negative': negative,
        'neutral': neutral,
        'avg_score': avg_score
    }


def calculate_overall_score_statistics(all_news: List[Dict]) -> Dict:
    """종합 점수 통계 계산"""
    overall_scores = [
        n.get('overall_score') 
        for n in all_news 
        if n.get('overall_score') is not None
    ]
    
    if not overall_scores:
        return {
            'total': 0,
            'high': 0,
            'medium': 0,
            'low': 0,
            'avg_score': 0.0
        }
    
    high_score = sum(1 for s in overall_scores if s >= 0.7)
    medium_score = sum(1 for s in overall_scores if 0.3 <= s < 0.7)
    low_score = sum(1 for s in overall_scores if s < 0.3)
    avg_score = sum(overall_scores) / len(overall_scores)
    
    return {
        'total': len(overall_scores),
        'high': high_score,
        'medium': medium_score,
        'low': low_score,
        'avg_score': avg_score
    }


def print_total_statistics(all_news: List[Dict]) -> int:
    """전체 통계 출력"""
    print_section_header("전체 통계", 1)
    total_count = len(all_news)
    print(f"전체 뉴스 개수: {total_count:,}개")
    print()
    return total_count


def print_source_distribution(all_news: List[Dict], total_count: int) -> None:
    """출처별 분포 출력"""
    print_section_header("출처별 분포", 2)
    source_counts = get_source_distribution(all_news)
    
    for source, count in source_counts.most_common():
        percentage = (count / total_count) * 100
        print(f"  {source:20s}: {count:6,}개 ({percentage:5.1f}%)")
    print()


def print_date_distribution(all_news: List[Dict], days: int = RECENT_DAYS) -> None:
    """날짜별 분포 출력"""
    print_section_header(f"최근 {days}일 날짜별 분포", 3)
    date_counts = get_date_distribution(all_news, days)
    
    if date_counts:
        for date_str in sorted(date_counts.keys(), reverse=True):
            count = date_counts[date_str]
            print(f"  {date_str}: {count:6,}개")
    else:
        print(f"  최근 {days}일 데이터가 없습니다.")
    print()


def print_data_completeness(all_news: List[Dict], total_count: int) -> Dict[str, float]:
    """데이터 완성도 출력 및 결과 반환"""
    print_section_header("데이터 완성도", 4)
    
    title_completeness, title_complete, _ = calculate_completeness(all_news, 'title', TITLE_MIN_LENGTH)
    content_completeness, content_complete, _ = calculate_completeness(all_news, 'content', CONTENT_MIN_LENGTH)
    url_completeness, url_complete, _ = calculate_completeness(all_news, 'url', 0)
    date_completeness, date_complete, _ = calculate_completeness(all_news, 'published_at', 0)
    
    print(f"제목 완성도: {title_completeness:.1f}% ({title_complete:,}/{total_count:,})")
    print(f"내용 완성도: {content_completeness:.1f}% ({content_complete:,}/{total_count:,})")
    print(f"URL 완성도: {url_completeness:.1f}% ({url_complete:,}/{total_count:,})")
    print(f"날짜 완성도: {date_completeness:.1f}% ({date_complete:,}/{total_count:,})")
    print()
    
    return {
        'title': title_completeness,
        'content': content_completeness,
        'url': url_completeness,
        'date': date_completeness
    }


def print_stock_code_statistics(all_news: List[Dict], total_count: int) -> float:
    """종목 코드 추출률 출력 및 반환"""
    print_section_header("종목 코드 추출률", 5)
    
    with_stock_code = sum(
        1 for n in all_news 
        if n.get('related_stocks') and len(str(n.get('related_stocks', ''))) > 0
    )
    stock_code_rate = (with_stock_code / total_count) * 100 if total_count > 0 else 0
    print(f"종목 코드가 있는 뉴스: {with_stock_code:,}개 ({stock_code_rate:.1f}%)")
    
    stock_code_counts = get_stock_code_distribution(all_news)
    if stock_code_counts:
        print(f"\n가장 많이 언급된 종목 코드 (상위 10개):")
        for code, count in stock_code_counts.most_common(10):
            print(f"  {code}: {count:,}회")
    print()
    
    return stock_code_rate


def print_sentiment_statistics(all_news: List[Dict], total_count: int) -> int:
    """감성 점수 분포 출력 및 감성 분석된 개수 반환"""
    print_section_header("감성 점수 분포", 6)
    
    stats = calculate_sentiment_statistics(all_news)
    
    if stats['total'] > 0:
        sentiment_rate = (stats['total'] / total_count) * 100
        print(f"감성 분석 완료: {stats['total']:,}개 ({sentiment_rate:.1f}%)")
        print(f"  긍정 (점수 > 0): {stats['positive']:,}개 ({stats['positive']/stats['total']*100:.1f}%)")
        print(f"  중립 (점수 = 0): {stats['neutral']:,}개 ({stats['neutral']/stats['total']*100:.1f}%)")
        print(f"  부정 (점수 < 0): {stats['negative']:,}개 ({stats['negative']/stats['total']*100:.1f}%)")
        print(f"  평균 감성 점수: {stats['avg_score']:.3f}")
    else:
        print("감성 분석이 수행되지 않았습니다.")
    print()
    
    return stats['total']


def print_overall_score_statistics(all_news: List[Dict]) -> None:
    """종합 점수 분포 출력"""
    print_section_header("종합 점수 분포", 7)
    
    stats = calculate_overall_score_statistics(all_news)
    
    if stats['total'] > 0:
        print(f"종합 점수 계산 완료: {stats['total']:,}개")
        print(f"  고점수 (≥0.7): {stats['high']:,}개 ({stats['high']/stats['total']*100:.1f}%)")
        print(f"  중점수 (0.3~0.7): {stats['medium']:,}개 ({stats['medium']/stats['total']*100:.1f}%)")
        print(f"  저점수 (<0.3): {stats['low']:,}개 ({stats['low']/stats['total']*100:.1f}%)")
        print(f"  평균 종합 점수: {stats['avg_score']:.3f}")
    else:
        print("종합 점수가 계산되지 않았습니다.")
    print()


def print_duplicate_check(all_news: List[Dict], total_count: int) -> float:
    """중복 뉴스 체크 출력 및 중복률 반환"""
    print_section_header("중복 뉴스 체크", 8)
    
    news_ids = [n.get('news_id') for n in all_news if n.get('news_id')]
    unique_ids = set(news_ids)
    duplicate_count = len(news_ids) - len(unique_ids)
    duplicate_rate = (duplicate_count / total_count) * 100 if total_count > 0 else 0
    
    print(f"고유 뉴스 ID: {len(unique_ids):,}개")
    print(f"중복 뉴스: {duplicate_count:,}개 ({duplicate_rate:.1f}%)")
    print()
    
    return duplicate_rate


def print_recent_collection_status(db: NewsDatabase) -> None:
    """최근 수집 현황 출력"""
    print_section_header("최근 수집 현황 (오늘)", 9)
    
    today = datetime.now()
    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    today_news = db.get_news_by_date_range(
        start_date.isoformat(),
        end_date.isoformat()
    )
    
    print(f"오늘 수집된 뉴스: {len(today_news):,}개")
    
    if today_news:
        today_source_counts = get_source_distribution(today_news)
        print("출처별 분포:")
        for source, count in today_source_counts.most_common():
            print(f"  {source}: {count:,}개")
    print()


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
    
    # 제목 완성도
    if title_completeness >= QUALITY_EXCELLENT:
        quality_score += WEIGHT_TITLE
        quality_items.append("[OK] 제목 완성도 우수")
    elif title_completeness >= QUALITY_GOOD:
        quality_score += WEIGHT_TITLE * 0.75
        quality_items.append("[+] 제목 완성도 양호")
    else:
        quality_items.append("[X] 제목 완성도 개선 필요")
    
    # 내용 완성도
    if content_completeness >= CONTENT_EXCELLENT:
        quality_score += WEIGHT_CONTENT
        quality_items.append("[OK] 내용 완성도 우수")
    elif content_completeness >= CONTENT_GOOD:
        quality_score += WEIGHT_CONTENT * 0.75
        quality_items.append("[+] 내용 완성도 양호")
    else:
        quality_items.append("[X] 내용 완성도 개선 필요")
    
    # 종목 코드 추출률
    if stock_code_rate >= STOCK_CODE_EXCELLENT:
        quality_score += WEIGHT_STOCK_CODE
        quality_items.append("[OK] 종목 코드 추출률 우수")
    elif stock_code_rate >= STOCK_CODE_GOOD:
        quality_score += WEIGHT_STOCK_CODE * 0.75
        quality_items.append("[+] 종목 코드 추출률 양호")
    else:
        quality_items.append("[X] 종목 코드 추출률 개선 필요")
    
    # 감성 분석 완료율
    if sentiment_rate >= SENTIMENT_EXCELLENT:
        quality_score += WEIGHT_SENTIMENT
        quality_items.append("[OK] 감성 분석 완료율 우수")
    elif sentiment_rate >= SENTIMENT_GOOD:
        quality_score += WEIGHT_SENTIMENT * 0.75
        quality_items.append("[+] 감성 분석 완료율 양호")
    else:
        quality_items.append("[X] 감성 분석 완료율 개선 필요")
    
    # 중복률
    if duplicate_rate <= DUPLICATE_EXCELLENT:
        quality_score += WEIGHT_DUPLICATE
        quality_items.append("[OK] 중복률 낮음 (우수)")
    elif duplicate_rate <= DUPLICATE_GOOD:
        quality_score += WEIGHT_DUPLICATE * 0.75
        quality_items.append("[+] 중복률 양호")
    else:
        quality_items.append("[X] 중복률 높음 (개선 필요)")
    
    return quality_score, quality_items


def get_quality_grade(score: int) -> str:
    """품질 점수에 따른 등급 반환"""
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
    """품질 종합 평가 출력"""
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
    db = NewsDatabase()
    
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

if __name__ == "__main__":
    check_data_quality()

