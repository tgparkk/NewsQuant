"""
오늘 수집된 데이터 종합 평가 스크립트
"""

from datetime import datetime
from news_scraper.database import NewsDatabase
from news_scraper.data_quality.quality_checker import (
    calculate_quality_score,
    get_quality_grade,
    print_quality_assessment
)
from news_scraper.data_quality.report import (
    print_section_header,
    format_number,
    calculate_completeness,
    get_source_distribution,
    get_stock_code_distribution,
    calculate_sentiment_statistics,
    calculate_overall_score_statistics,
)
from news_scraper.data_quality.config import (
    TITLE_MIN_LENGTH,
    CONTENT_MIN_LENGTH,
    SCORE_HIGH_THRESHOLD,
    SCORE_MEDIUM_THRESHOLD,
)
from collections import Counter


def evaluate_today_data():
    """오늘 수집된 데이터 종합 평가"""
    db = NewsDatabase()
    
    print("=" * 80)
    print("오늘 수집 데이터 종합 평가 리포트")
    print("=" * 80)
    print(f"평가 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 오늘 날짜 범위 설정
    today = datetime.now()
    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # 오늘자 뉴스 조회
    today_news = db.get_news_by_date_range(
        start_date.isoformat(),
        end_date.isoformat()
    )
    
    total_count = len(today_news)
    
    print_section_header("1. 수집 현황", 1)
    print(f"오늘 수집된 뉴스: {format_number(total_count)}개")
    print()
    
    if total_count == 0:
        print("⚠️  오늘 수집된 데이터가 없습니다.")
        return
    
    # 출처별 분포
    print_section_header("2. 출처별 분포", 2)
    source_counts = get_source_distribution(today_news)
    for source, count in source_counts.most_common():
        percentage = (count / total_count) * 100
        print(f"  {source:20s}: {format_number(count):>6}개 ({percentage:5.1f}%)")
    print()
    
    # 시간대별 분포
    print_section_header("3. 시간대별 수집 현황", 3)
    hour_counts = Counter()
    for news in today_news:
        published_at = news.get('published_at', '')
        if published_at:
            try:
                dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                hour = dt.hour
                hour_counts[hour] += 1
            except:
                pass
    
    if hour_counts:
        print("시간대별 수집 건수:")
        for hour in sorted(hour_counts.keys()):
            count = hour_counts[hour]
            bar = "#" * (count // 5)  # 5개당 1칸
            print(f"  {hour:02d}시: {count:4d}개 {bar}")
    print()
    
    # 데이터 완성도
    print_section_header("4. 데이터 완성도", 4)
    title_completeness, title_complete, _ = calculate_completeness(today_news, 'title', TITLE_MIN_LENGTH)
    content_completeness, content_complete, _ = calculate_completeness(today_news, 'content', CONTENT_MIN_LENGTH)
    url_completeness, url_complete, _ = calculate_completeness(today_news, 'url', 0)
    date_completeness, date_complete, _ = calculate_completeness(today_news, 'published_at', 0)
    
    print(f"제목 완성도: {title_completeness:.1f}% ({format_number(title_complete)}/{format_number(total_count)})")
    print(f"내용 완성도: {content_completeness:.1f}% ({format_number(content_complete)}/{format_number(total_count)})")
    print(f"URL 완성도: {url_completeness:.1f}% ({format_number(url_complete)}/{format_number(total_count)})")
    print(f"날짜 완성도: {date_completeness:.1f}% ({format_number(date_complete)}/{format_number(total_count)})")
    print()
    
    # 내용 길이 분포
    print_section_header("5. 내용 길이 분포", 5)
    empty_content = [n for n in today_news if not n.get('content') or len(n.get('content', '')) < 10]
    short_content = [n for n in today_news if n.get('content') and 10 <= len(n.get('content', '')) < 50]
    medium_content = [n for n in today_news if n.get('content') and 50 <= len(n.get('content', '')) < 200]
    good_content = [n for n in today_news if n.get('content') and len(n.get('content', '')) >= 200]
    
    print(f"내용 없음 (<10자): {format_number(len(empty_content))}개 ({len(empty_content)/total_count*100:.1f}%)")
    print(f"내용 부족 (10~49자): {format_number(len(short_content))}개 ({len(short_content)/total_count*100:.1f}%)")
    print(f"내용 보통 (50~199자): {format_number(len(medium_content))}개 ({len(medium_content)/total_count*100:.1f}%)")
    print(f"내용 양호 (≥200자): {format_number(len(good_content))}개 ({len(good_content)/total_count*100:.1f}%)")
    print()
    
    # 출처별 내용 완성도
    print_section_header("6. 출처별 내용 완성도", 6)
    source_content_stats = {}
    for news in today_news:
        source = news.get('source', 'Unknown')
        if source not in source_content_stats:
            source_content_stats[source] = {'total': 0, 'empty': 0, 'good': 0}
        
        source_content_stats[source]['total'] += 1
        content_len = len(news.get('content', '') or '')
        if content_len < 50:
            source_content_stats[source]['empty'] += 1
        else:
            source_content_stats[source]['good'] += 1
    
    for source, stats in sorted(source_content_stats.items()):
        empty_rate = stats['empty'] / stats['total'] * 100
        good_rate = stats['good'] / stats['total'] * 100
        print(f"{source:20s}: 전체 {stats['total']:4d}개 | "
              f"부족 {stats['empty']:3d}개 ({empty_rate:5.1f}%) | "
              f"양호 {stats['good']:3d}개 ({good_rate:5.1f}%)")
    print()
    
    # 종목 코드 추출률
    print_section_header("7. 종목 코드 추출률", 7)
    with_stock_code = sum(
        1 for n in today_news 
        if n.get('related_stocks') and len(str(n.get('related_stocks', ''))) > 0
    )
    stock_code_rate = (with_stock_code / total_count) * 100 if total_count > 0 else 0
    print(f"종목 코드가 있는 뉴스: {format_number(with_stock_code)}개 ({stock_code_rate:.1f}%)")
    
    stock_code_counts = get_stock_code_distribution(today_news)
    if stock_code_counts:
        print(f"\n가장 많이 언급된 종목 코드 (상위 10개):")
        for code, count in stock_code_counts.most_common(10):
            print(f"  {code}: {format_number(count)}회")
    print()
    
    # 감성 분석 현황
    print_section_header("8. 감성 분석 현황", 8)
    stats = calculate_sentiment_statistics(today_news)
    
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
    
    # 종합 점수 현황
    print_section_header("9. 종합 점수 현황", 9)
    overall_stats = calculate_overall_score_statistics(today_news)
    
    if overall_stats['total'] > 0:
        print(f"종합 점수 계산 완료: {format_number(overall_stats['total'])}개")
        print(f"  고점수 (≥{SCORE_HIGH_THRESHOLD}): {format_number(overall_stats['high'])}개 ({overall_stats['high']/overall_stats['total']*100:.1f}%)")
        print(f"  중점수 ({SCORE_MEDIUM_THRESHOLD}~{SCORE_HIGH_THRESHOLD}): {format_number(overall_stats['medium'])}개 ({overall_stats['medium']/overall_stats['total']*100:.1f}%)")
        print(f"  저점수 (<{SCORE_MEDIUM_THRESHOLD}): {format_number(overall_stats['low'])}개 ({overall_stats['low']/overall_stats['total']*100:.1f}%)")
        print(f"  평균 종합 점수: {overall_stats['avg_score']:.3f}")
    else:
        print("종합 점수가 계산되지 않았습니다.")
    print()
    
    # 중복 체크
    print_section_header("10. 중복 뉴스 체크", 10)
    news_ids = [n.get('news_id') for n in today_news if n.get('news_id')]
    unique_ids = set(news_ids)
    duplicate_count = len(news_ids) - len(unique_ids)
    duplicate_rate = (duplicate_count / total_count) * 100 if total_count > 0 else 0
    
    print(f"고유 뉴스 ID: {format_number(len(unique_ids))}개")
    print(f"중복 뉴스: {format_number(duplicate_count)}개 ({duplicate_rate:.1f}%)")
    print()
    
    # 종합 품질 평가
    print_section_header("11. 종합 품질 평가", 11)
    sentiment_count = stats['total']
    sentiment_rate = (sentiment_count / total_count) * 100 if total_count > 0 else 0
    
    print_quality_assessment(
        title_completeness,
        content_completeness,
        stock_code_rate,
        sentiment_rate,
        duplicate_rate
    )
    
    # 주요 문제점 요약
    print_section_header("12. 주요 문제점 및 개선사항", 12)
    
    issues = []
    if content_completeness < 60:
        issues.append(f"[X] 내용 완성도가 낮습니다 ({content_completeness:.1f}%). 상세 페이지 크롤링 개선이 필요합니다.")
    
    if stock_code_rate < 50:
        issues.append(f"[!] 종목 코드 추출률이 낮습니다 ({stock_code_rate:.1f}%). 종목 코드 추출 로직 개선이 필요합니다.")
    
    if sentiment_rate < 80:
        issues.append(f"[!] 감성 분석 완료율이 낮습니다 ({sentiment_rate:.1f}%). 감성 분석 프로세스 확인이 필요합니다.")
    
    if duplicate_rate > 5:
        issues.append(f"[!] 중복률이 높습니다 ({duplicate_rate:.1f}%). 중복 체크 로직 강화가 필요합니다.")
    
    # 출처별 문제점
    for source, stats in source_content_stats.items():
        empty_rate = stats['empty'] / stats['total'] * 100
        if empty_rate > 50:
            issues.append(f"[X] {source}의 내용 부족률이 높습니다 ({empty_rate:.1f}%). 크롤러 개선이 필요합니다.")
    
    if issues:
        for i, issue in enumerate(issues, 1):
            print(f"{i}. {issue}")
    else:
        print("[OK] 주요 문제점이 발견되지 않았습니다.")
    print()
    
    # 수집 성공률 평가
    print_section_header("13. 수집 성공률 평가", 13)
    
    # 내용이 있고 종목 코드가 있고 감성 분석이 완료된 뉴스
    complete_news = [
        n for n in today_news
        if n.get('content') and len(n.get('content', '')) >= 50
        and n.get('related_stocks')
        and n.get('sentiment_score') is not None
    ]
    
    complete_rate = (len(complete_news) / total_count) * 100 if total_count > 0 else 0
    
    print(f"완전한 데이터 (내용≥50자 + 종목코드 + 감성분석): {format_number(len(complete_news))}개 ({complete_rate:.1f}%)")
    print()
    
    if complete_rate >= 70:
        print("[OK] 수집 품질이 우수합니다.")
    elif complete_rate >= 50:
        print("[!] 수집 품질이 보통입니다. 개선 여지가 있습니다.")
    else:
        print("[X] 수집 품질이 낮습니다. 즉시 개선이 필요합니다.")
    print()
    
    print("=" * 80)
    print("평가 완료")
    print("=" * 80)


if __name__ == "__main__":
    evaluate_today_data()

