"""
오늘 수집 데이터의 문제점 분석 스크립트
"""

from datetime import datetime
from news_scraper.database import NewsDatabase
from collections import Counter

def analyze_today_issues():
    """오늘 수집 데이터의 문제점 분석"""
    db = NewsDatabase()
    
    print("=" * 80)
    print("오늘 수집 데이터 문제점 분석")
    print("=" * 80)
    print(f"분석 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
    
    print(f"[1] 전체 현황")
    print("-" * 80)
    print(f"오늘 수집된 뉴스: {len(today_news):,}개")
    print()
    
    if len(today_news) == 0:
        print("[경고] 오늘자 뉴스가 없습니다.")
        return
    
    # 내용이 없는 뉴스 분석
    empty_content = [n for n in today_news if not n.get('content') or len(n.get('content', '')) < 10]
    short_content = [n for n in today_news if n.get('content') and 10 <= len(n.get('content', '')) < 50]
    good_content = [n for n in today_news if n.get('content') and len(n.get('content', '')) >= 50]
    
    print(f"[2] 내용 완성도 분석")
    print("-" * 80)
    print(f"내용 없음 (<10자): {len(empty_content):,}개 ({len(empty_content)/len(today_news)*100:.1f}%)")
    print(f"내용 부족 (10~49자): {len(short_content):,}개 ({len(short_content)/len(today_news)*100:.1f}%)")
    print(f"내용 양호 (≥50자): {len(good_content):,}개 ({len(good_content)/len(today_news)*100:.1f}%)")
    print()
    
    # 출처별 내용 완성도
    print(f"[3] 출처별 내용 완성도")
    print("-" * 80)
    source_stats = {}
    for news in today_news:
        source = news.get('source', 'Unknown')
        if source not in source_stats:
            source_stats[source] = {'total': 0, 'empty': 0, 'short': 0, 'good': 0}
        
        source_stats[source]['total'] += 1
        content_len = len(news.get('content', '') or '')
        if content_len < 10:
            source_stats[source]['empty'] += 1
        elif content_len < 50:
            source_stats[source]['short'] += 1
        else:
            source_stats[source]['good'] += 1
    
    for source, stats in sorted(source_stats.items()):
        empty_rate = stats['empty'] / stats['total'] * 100
        good_rate = stats['good'] / stats['total'] * 100
        print(f"{source:20s}: 전체 {stats['total']:4d}개 | "
              f"없음 {stats['empty']:3d}개 ({empty_rate:5.1f}%) | "
              f"부족 {stats['short']:3d}개 | "
              f"양호 {stats['good']:3d}개 ({good_rate:5.1f}%)")
    print()
    
    # 내용이 없는 뉴스 샘플
    print(f"[4] 내용 없는 뉴스 샘플 (최대 10개)")
    print("-" * 80)
    for i, news in enumerate(empty_content[:10], 1):
        source = news.get('source', 'Unknown')
        title = news.get('title', 'N/A')[:60]
        url = news.get('url', 'N/A')[:70]
        content_len = len(news.get('content', '') or '')
        print(f"{i}. [{source:15s}] {title}...")
        print(f"   URL: {url}...")
        print(f"   내용 길이: {content_len}자")
        print()
    
    # URL 패턴 분석 (내용이 없는 뉴스의 URL 패턴)
    print(f"[5] 내용 없는 뉴스의 URL 패턴 분석")
    print("-" * 80)
    url_patterns = Counter()
    for news in empty_content:
        url = news.get('url', '')
        if 'naver.com' in url:
            if '/news/read' in url:
                url_patterns['naver_finance_read'] += 1
            elif '/news/news_view' in url:
                url_patterns['naver_finance_view'] += 1
            else:
                url_patterns['naver_finance_other'] += 1
        elif 'hankyung.com' in url:
            url_patterns['hankyung'] += 1
        elif 'mk.co.kr' in url:
            url_patterns['mk_news'] += 1
        else:
            url_patterns['other'] += 1
    
    for pattern, count in url_patterns.most_common():
        print(f"  {pattern:25s}: {count:4d}개")
    print()
    
    # 상세 페이지 크롤링 실패 가능성 체크
    print(f"[6] 문제 원인 추정")
    print("-" * 80)
    
    # 1. 요약만 있고 본문이 없는 경우
    summary_only = 0
    for news in empty_content:
        # URL이 있지만 내용이 없는 경우는 상세 페이지 크롤링 실패로 추정
        if news.get('url'):
            summary_only += 1
    
    print(f"상세 페이지 크롤링 실패 추정: {summary_only:,}개")
    print(f"  - URL은 있지만 본문 내용이 없음")
    print(f"  - crawl_news_detail() 메서드가 None 반환 또는 빈 내용 반환")
    print()
    
    # 2. 크롤러별 실패율
    print(f"[7] 크롤러별 상세 페이지 크롤링 실패율")
    print("-" * 80)
    crawler_failures = {}
    for news in empty_content:
        source = news.get('source', 'Unknown')
        if source not in crawler_failures:
            crawler_failures[source] = 0
        crawler_failures[source] += 1
    
    for source, count in sorted(crawler_failures.items()):
        total = source_stats[source]['total']
        fail_rate = count / total * 100
        print(f"{source:20s}: {count:4d}개 실패 / {total:4d}개 전체 ({fail_rate:5.1f}% 실패율)")
    print()
    
    # 8. 해결 방안 제시
    print(f"[8] 해결 방안")
    print("-" * 80)
    print("1. 크롤러의 crawl_news_detail() 메서드 개선:")
    print("   - 더 많은 CSS 선택자 패턴 추가")
    print("   - 본문 추출 실패 시 재시도 로직 강화")
    print("   - JavaScript로 동적 로딩되는 콘텐츠 처리 (Selenium 등)")
    print()
    print("2. 요약 정보 활용:")
    print("   - 상세 페이지 크롤링 실패 시 목록 페이지의 요약 정보라도 저장")
    print("   - 요약이 10자 이상이면 최소한의 내용으로 저장")
    print()
    print("3. 재처리 스크립트 실행:")
    print("   - reprocess_data.py를 실행하여 내용이 없는 뉴스 재크롤링")
    print("   - 실패한 URL들을 별도로 수집하여 재시도")
    print()
    print("4. 로깅 강화:")
    print("   - 상세 페이지 크롤링 실패 시 URL과 원인을 로그에 기록")
    print("   - 실패 패턴 분석을 위한 통계 수집")
    print()
    
    print("=" * 80)

if __name__ == "__main__":
    analyze_today_issues()

