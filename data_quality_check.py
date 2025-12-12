"""
수집된 뉴스 데이터 품질 조사 스크립트
"""

from datetime import datetime, timedelta
from news_scraper.database import NewsDatabase
from collections import Counter

def check_data_quality():
    """데이터 품질 조사"""
    db = NewsDatabase()
    
    print("=" * 70)
    print("뉴스 데이터 품질 조사 리포트")
    print("=" * 70)
    print(f"조사 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 1. 전체 통계
    print("[1] 전체 통계")
    print("-" * 70)
    all_news = db.get_latest_news(limit=100000)  # 전체 조회
    total_count = len(all_news)
    print(f"전체 뉴스 개수: {total_count:,}개")
    print()
    
    if total_count == 0:
        print("⚠️  데이터베이스에 뉴스가 없습니다.")
        return
    
    # 2. 출처별 분포
    print("[2] 출처별 분포")
    print("-" * 70)
    source_counts = Counter()
    for news in all_news:
        source = news.get('source', 'Unknown')
        source_counts[source] += 1
    
    for source, count in source_counts.most_common():
        percentage = (count / total_count) * 100
        print(f"  {source:20s}: {count:6,}개 ({percentage:5.1f}%)")
    print()
    
    # 3. 날짜별 분포 (최근 7일)
    print("[3] 최근 7일 날짜별 분포")
    print("-" * 70)
    date_counts = Counter()
    today = datetime.now()
    
    for news in all_news:
        published_at = news.get('published_at', '')
        if published_at:
            try:
                # ISO 형식 파싱
                if 'T' in published_at:
                    date_str = published_at.split('T')[0]
                else:
                    date_str = published_at[:10]
                
                date_obj = datetime.fromisoformat(date_str)
                days_ago = (today - date_obj).days
                
                if days_ago <= 7:
                    date_counts[date_str] += 1
            except:
                pass
    
    if date_counts:
        for date_str in sorted(date_counts.keys(), reverse=True):
            count = date_counts[date_str]
            print(f"  {date_str}: {count:6,}개")
    else:
        print("  최근 7일 데이터가 없습니다.")
    print()
    
    # 4. 데이터 완성도
    print("[4] 데이터 완성도")
    print("-" * 70)
    
    # 제목 완성도
    title_empty = sum(1 for n in all_news if not n.get('title') or len(n.get('title', '')) < 5)
    title_completeness = ((total_count - title_empty) / total_count) * 100
    print(f"제목 완성도: {title_completeness:.1f}% ({total_count - title_empty:,}/{total_count:,})")
    
    # 내용 완성도
    content_empty = sum(1 for n in all_news if not n.get('content') or len(n.get('content', '')) < 10)
    content_completeness = ((total_count - content_empty) / total_count) * 100
    print(f"내용 완성도: {content_completeness:.1f}% ({total_count - content_empty:,}/{total_count:,})")
    
    # URL 완성도
    url_empty = sum(1 for n in all_news if not n.get('url'))
    url_completeness = ((total_count - url_empty) / total_count) * 100
    print(f"URL 완성도: {url_completeness:.1f}% ({total_count - url_empty:,}/{total_count:,})")
    
    # 날짜 완성도
    date_empty = sum(1 for n in all_news if not n.get('published_at'))
    date_completeness = ((total_count - date_empty) / total_count) * 100
    print(f"날짜 완성도: {date_completeness:.1f}% ({total_count - date_empty:,}/{total_count:,})")
    print()
    
    # 5. 종목 코드 추출률
    print("[5] 종목 코드 추출률")
    print("-" * 70)
    with_stock_code = sum(1 for n in all_news if n.get('related_stocks') and len(n.get('related_stocks', '')) > 0)
    stock_code_rate = (with_stock_code / total_count) * 100
    print(f"종목 코드가 있는 뉴스: {with_stock_code:,}개 ({stock_code_rate:.1f}%)")
    
    # 종목 코드 분포
    stock_code_counts = Counter()
    for news in all_news:
        stocks = news.get('related_stocks', '')
        if stocks:
            codes = stocks.split(',')
            for code in codes:
                if code.strip():
                    stock_code_counts[code.strip()] += 1
    
    if stock_code_counts:
        print(f"\n가장 많이 언급된 종목 코드 (상위 10개):")
        for code, count in stock_code_counts.most_common(10):
            print(f"  {code}: {count:,}회")
    print()
    
    # 6. 감성 점수 분포
    print("[6] 감성 점수 분포")
    print("-" * 70)
    sentiment_scores = [n.get('sentiment_score') for n in all_news if n.get('sentiment_score') is not None]
    
    if sentiment_scores:
        positive = sum(1 for s in sentiment_scores if s > 0)
        negative = sum(1 for s in sentiment_scores if s < 0)
        neutral = sum(1 for s in sentiment_scores if s == 0)
        
        print(f"감성 분석 완료: {len(sentiment_scores):,}개 ({len(sentiment_scores)/total_count*100:.1f}%)")
        print(f"  긍정 (점수 > 0): {positive:,}개 ({positive/len(sentiment_scores)*100:.1f}%)")
        print(f"  중립 (점수 = 0): {neutral:,}개 ({neutral/len(sentiment_scores)*100:.1f}%)")
        print(f"  부정 (점수 < 0): {negative:,}개 ({negative/len(sentiment_scores)*100:.1f}%)")
        
        if sentiment_scores:
            avg_score = sum(sentiment_scores) / len(sentiment_scores)
            print(f"  평균 감성 점수: {avg_score:.3f}")
    else:
        print("감성 분석이 수행되지 않았습니다.")
    print()
    
    # 7. 종합 점수 분포
    print("[7] 종합 점수 분포")
    print("-" * 70)
    overall_scores = [n.get('overall_score') for n in all_news if n.get('overall_score') is not None]
    
    if overall_scores:
        high_score = sum(1 for s in overall_scores if s >= 0.7)
        medium_score = sum(1 for s in overall_scores if 0.3 <= s < 0.7)
        low_score = sum(1 for s in overall_scores if s < 0.3)
        
        print(f"종합 점수 계산 완료: {len(overall_scores):,}개")
        print(f"  고점수 (≥0.7): {high_score:,}개 ({high_score/len(overall_scores)*100:.1f}%)")
        print(f"  중점수 (0.3~0.7): {medium_score:,}개 ({medium_score/len(overall_scores)*100:.1f}%)")
        print(f"  저점수 (<0.3): {low_score:,}개 ({low_score/len(overall_scores)*100:.1f}%)")
        
        if overall_scores:
            avg_score = sum(overall_scores) / len(overall_scores)
            print(f"  평균 종합 점수: {avg_score:.3f}")
    else:
        print("종합 점수가 계산되지 않았습니다.")
    print()
    
    # 8. 중복 뉴스 체크
    print("[8] 중복 뉴스 체크")
    print("-" * 70)
    news_ids = [n.get('news_id') for n in all_news if n.get('news_id')]
    unique_ids = set(news_ids)
    duplicate_count = len(news_ids) - len(unique_ids)
    duplicate_rate = (duplicate_count / total_count) * 100 if total_count > 0 else 0
    
    print(f"고유 뉴스 ID: {len(unique_ids):,}개")
    print(f"중복 뉴스: {duplicate_count:,}개 ({duplicate_rate:.1f}%)")
    print()
    
    # 9. 최근 수집 현황
    print("[9] 최근 수집 현황 (오늘)")
    print("-" * 70)
    today = datetime.now()
    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    today_news = db.get_news_by_date_range(
        start_date.isoformat(),
        end_date.isoformat()
    )
    
    print(f"오늘 수집된 뉴스: {len(today_news):,}개")
    
    if today_news:
        today_source_counts = Counter()
        for news in today_news:
            source = news.get('source', 'Unknown')
            today_source_counts[source] += 1
        
        print("출처별 분포:")
        for source, count in today_source_counts.most_common():
            print(f"  {source}: {count:,}개")
    print()
    
    # 10. 품질 종합 평가
    print("[10] 품질 종합 평가")
    print("-" * 70)
    
    quality_score = 0
    quality_items = []
    
    # 제목 완성도 (20점)
    if title_completeness >= 95:
        quality_score += 20
        quality_items.append("[OK] 제목 완성도 우수")
    elif title_completeness >= 80:
        quality_score += 15
        quality_items.append("[+] 제목 완성도 양호")
    else:
        quality_items.append("[X] 제목 완성도 개선 필요")
    
    # 내용 완성도 (20점)
    if content_completeness >= 80:
        quality_score += 20
        quality_items.append("[OK] 내용 완성도 우수")
    elif content_completeness >= 60:
        quality_score += 15
        quality_items.append("[+] 내용 완성도 양호")
    else:
        quality_items.append("[X] 내용 완성도 개선 필요")
    
    # 종목 코드 추출률 (20점)
    if stock_code_rate >= 30:
        quality_score += 20
        quality_items.append("[OK] 종목 코드 추출률 우수")
    elif stock_code_rate >= 15:
        quality_score += 15
        quality_items.append("[+] 종목 코드 추출률 양호")
    else:
        quality_items.append("[X] 종목 코드 추출률 개선 필요")
    
    # 감성 분석 완료율 (20점)
    sentiment_rate = (len(sentiment_scores) / total_count) * 100 if total_count > 0 else 0
    if sentiment_rate >= 90:
        quality_score += 20
        quality_items.append("[OK] 감성 분석 완료율 우수")
    elif sentiment_rate >= 70:
        quality_score += 15
        quality_items.append("[+] 감성 분석 완료율 양호")
    else:
        quality_items.append("[X] 감성 분석 완료율 개선 필요")
    
    # 중복률 (20점)
    if duplicate_rate <= 5:
        quality_score += 20
        quality_items.append("[OK] 중복률 낮음 (우수)")
    elif duplicate_rate <= 10:
        quality_score += 15
        quality_items.append("[+] 중복률 양호")
    else:
        quality_items.append("[X] 중복률 높음 (개선 필요)")
    
    print(f"종합 품질 점수: {quality_score}/100점")
    print()
    print("세부 평가:")
    for item in quality_items:
        print(f"  {item}")
    print()
    
    # 등급
    if quality_score >= 90:
        grade = "A (우수)"
    elif quality_score >= 80:
        grade = "B (양호)"
    elif quality_score >= 70:
        grade = "C (보통)"
    elif quality_score >= 60:
        grade = "D (미흡)"
    else:
        grade = "F (불량)"
    
    print(f"등급: {grade}")
    print()
    print("=" * 70)

if __name__ == "__main__":
    check_data_quality()

