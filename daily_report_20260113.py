"""
2026-01-13 일일 데이터 수집 및 분석 보고서 생성
"""

from datetime import datetime
from news_scraper.database import NewsDatabase
from collections import defaultdict, Counter

def generate_daily_report():
    """일일 보고서 생성"""
    db = NewsDatabase()
    
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("2026년 1월 13일 (화) 데이터 수집 및 분석 보고서")
    report_lines.append("=" * 80)
    report_lines.append(f"보고서 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")
    
    # 1. 전체 수집 통계
    report_lines.append("[1] 전체 데이터 수집 통계")
    report_lines.append("-" * 80)
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # 전체 뉴스 수
    cursor.execute("SELECT COUNT(*) FROM news")
    total_news = cursor.fetchone()[0]
    report_lines.append(f"전체 수집된 뉴스: {total_news:,}개")
    
    # 전체 수집 로그
    cursor.execute("SELECT COUNT(*) FROM collection_log")
    total_logs = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM collection_log WHERE status = 'success'")
    success_logs = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(news_count) FROM collection_log WHERE status = 'success'")
    total_collected = cursor.fetchone()[0] or 0
    
    success_rate = (success_logs / total_logs * 100) if total_logs > 0 else 0
    
    report_lines.append(f"전체 수집 시도: {total_logs:,}회")
    report_lines.append(f"성공: {success_logs:,}회 ({success_rate:.1f}%)")
    report_lines.append(f"실패: {total_logs - success_logs:,}회 ({100-success_rate:.1f}%)")
    report_lines.append("")
    
    # 2. 오늘자 데이터 현황
    report_lines.append("[2] 오늘(1/13) 데이터 수집 현황")
    report_lines.append("-" * 80)
    
    today = datetime.now()
    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    today_news = db.get_news_by_date_range(
        start_date.isoformat(),
        end_date.isoformat()
    )
    
    report_lines.append(f"오늘 수집된 뉴스: {len(today_news):,}개")
    report_lines.append("")
    
    # 출처별 분포
    report_lines.append("출처별 분포:")
    source_counts = Counter(n.get('source', 'Unknown') for n in today_news)
    for source, count in source_counts.most_common():
        percentage = (count / len(today_news)) * 100 if len(today_news) > 0 else 0
        report_lines.append(f"  - {source:20s}: {count:5,}개 ({percentage:5.1f}%)")
    report_lines.append("")
    
    # 데이터 품질
    report_lines.append("데이터 품질:")
    good_content = sum(1 for n in today_news if n.get('content') and len(n.get('content', '')) >= 200)
    with_stock = sum(1 for n in today_news if n.get('related_stocks'))
    with_sentiment = sum(1 for n in today_news if n.get('sentiment_score') is not None)
    
    report_lines.append(f"  - 내용 양호(≥200자): {good_content:,}개 ({good_content/len(today_news)*100:.1f}%)")
    report_lines.append(f"  - 종목 코드 포함: {with_stock:,}개 ({with_stock/len(today_news)*100:.1f}%)")
    report_lines.append(f"  - 감성 분석 완료: {with_sentiment:,}개 ({with_sentiment/len(today_news)*100:.1f}%)")
    report_lines.append("")
    
    # 3. 종목 분석
    report_lines.append("[3] 오늘자 종목 분석")
    report_lines.append("-" * 80)
    
    # 종목별 뉴스 수집 및 분석
    stock_analysis = defaultdict(lambda: {
        'news_list': [],
        'sentiment_scores': [],
        'overall_scores': [],
        'positive_count': 0,
        'negative_count': 0,
        'neutral_count': 0,
    })
    
    for news in today_news:
        related_stocks = news.get('related_stocks', '')
        if related_stocks:
            stocks = [s.strip() for s in related_stocks.split(',') if s.strip()]
            sentiment_score = news.get('sentiment_score')
            overall_score = news.get('overall_score')
            
            for stock_code in stocks:
                stock_analysis[stock_code]['news_list'].append(news)
                
                if sentiment_score is not None:
                    stock_analysis[stock_code]['sentiment_scores'].append(sentiment_score)
                    if sentiment_score > 0:
                        stock_analysis[stock_code]['positive_count'] += 1
                    elif sentiment_score < 0:
                        stock_analysis[stock_code]['negative_count'] += 1
                    else:
                        stock_analysis[stock_code]['neutral_count'] += 1
                
                if overall_score is not None:
                    stock_analysis[stock_code]['overall_scores'].append(overall_score)
    
    # 종목별 통계 계산
    stock_stats = []
    for stock_code, data in stock_analysis.items():
        news_count = len(data['news_list'])
        if news_count == 0:
            continue
        
        avg_sentiment = sum(data['sentiment_scores']) / len(data['sentiment_scores']) if data['sentiment_scores'] else 0.0
        avg_overall = sum(data['overall_scores']) / len(data['overall_scores']) if data['overall_scores'] else 0.0
        
        # 종합 점수 계산
        news_score = min(news_count / 10.0, 1.0)
        composite_score = (avg_sentiment * 0.4) + (avg_overall * 0.4) + (news_score * 0.2)
        
        stock_stats.append({
            'stock_code': stock_code,
            'news_count': news_count,
            'avg_sentiment': avg_sentiment,
            'avg_overall': avg_overall,
            'composite_score': composite_score,
            'positive_count': data['positive_count'],
            'negative_count': data['negative_count'],
            'neutral_count': data['neutral_count'],
            'positive_ratio': data['positive_count'] / news_count if news_count > 0 else 0.0
        })
    
    # 종합 점수 기준으로 정렬
    stock_stats.sort(key=lambda x: x['composite_score'], reverse=True)
    
    report_lines.append(f"분석된 종목 수: {len(stock_stats):,}개")
    report_lines.append("")
    
    # 매수 후보 종목
    buy_candidates = [
        s for s in stock_stats
        if s['avg_sentiment'] > 0.05
        and s['avg_overall'] > 0.3
        and s['news_count'] >= 3
        and s['positive_ratio'] >= 0.3
        and s['positive_count'] > s['negative_count']
    ]
    
    report_lines.append(f"매수 후보 종목: {len(buy_candidates):,}개")
    report_lines.append("")
    
    if buy_candidates:
        report_lines.append("TOP 10 매수 후보:")
        report_lines.append(f"{'순위':<6} {'종목코드':<10} {'뉴스수':<8} {'평균감성':<10} {'평균종합':<10} {'긍정/부정':<12}")
        report_lines.append("-" * 80)
        
        for i, stat in enumerate(buy_candidates[:10], 1):
            report_lines.append(
                f"{i:<6} {stat['stock_code']:<10} {stat['news_count']:<8} "
                f"{stat['avg_sentiment']:>8.3f}  {stat['avg_overall']:>8.3f}  "
                f"{stat['positive_count']}/{stat['negative_count']:<10}"
            )
            
            # 대표 뉴스 제목 1개 표시
            stock_news = [n for n in today_news if stat['stock_code'] in (n.get('related_stocks', '') or '').split(',')]
            stock_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)
            if stock_news:
                latest_title = stock_news[0].get('title', 'N/A')[:70]
                report_lines.append(f"       [뉴스] {latest_title}")
    else:
        report_lines.append("[주의] 매수 후보 조건을 만족하는 종목이 없습니다.")
    
    report_lines.append("")
    
    # 매도 후보 종목
    sell_candidates = [
        s for s in stock_stats
        if s['avg_sentiment'] < -0.05
        and s['avg_overall'] < 0.3
        and s['news_count'] >= 3
        and s['negative_count'] > s['positive_count']
    ]
    
    report_lines.append(f"매도 후보 종목: {len(sell_candidates):,}개")
    report_lines.append("")
    
    if sell_candidates:
        report_lines.append("TOP 5 매도 후보:")
        report_lines.append(f"{'순위':<6} {'종목코드':<10} {'뉴스수':<8} {'평균감성':<10} {'평균종합':<10} {'긍정/부정':<12}")
        report_lines.append("-" * 80)
        
        for i, stat in enumerate(sell_candidates[:5], 1):
            report_lines.append(
                f"{i:<6} {stat['stock_code']:<10} {stat['news_count']:<8} "
                f"{stat['avg_sentiment']:>8.3f}  {stat['avg_overall']:>8.3f}  "
                f"{stat['positive_count']}/{stat['negative_count']:<10}"
            )
            
            # 대표 뉴스 제목 1개 표시
            stock_news = [n for n in today_news if stat['stock_code'] in (n.get('related_stocks', '') or '').split(',')]
            stock_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)
            if stock_news:
                latest_title = stock_news[0].get('title', 'N/A')[:70]
                report_lines.append(f"       [뉴스] {latest_title}")
    else:
        report_lines.append("[OK] 매도 후보 조건을 만족하는 종목이 없습니다.")
    
    report_lines.append("")
    
    # 4. 가장 많이 언급된 종목
    report_lines.append("[4] 가장 많이 언급된 종목 TOP 15")
    report_lines.append("-" * 80)
    
    most_mentioned = sorted(stock_stats, key=lambda x: x['news_count'], reverse=True)[:15]
    
    report_lines.append(f"{'순위':<6} {'종목코드':<10} {'언급횟수':<10} {'평균감성':<10} {'평균종합':<10}")
    report_lines.append("-" * 80)
    
    for i, stat in enumerate(most_mentioned, 1):
        report_lines.append(
            f"{i:<6} {stat['stock_code']:<10} {stat['news_count']:<10} "
            f"{stat['avg_sentiment']:>8.3f}  {stat['avg_overall']:>8.3f}"
        )
    
    report_lines.append("")
    
    # 5. 최근 24시간 수집 활동
    report_lines.append("[5] 최근 24시간 수집 활동")
    report_lines.append("-" * 80)
    
    cursor.execute("""
        SELECT source, 
               COUNT(*) as attempts,
               SUM(news_count) as total_news,
               SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count
        FROM collection_log
        WHERE datetime(collected_at) >= datetime('now', '-1 day')
        GROUP BY source
        ORDER BY total_news DESC
    """)
    
    recent_stats = cursor.fetchall()
    
    if recent_stats:
        report_lines.append(f"{'출처':<20} {'시도':<8} {'성공':<8} {'수집 건수':<12}")
        report_lines.append("-" * 80)
        for source, attempts, total_news, success_count in recent_stats:
            success_rate = (success_count / attempts * 100) if attempts > 0 else 0
            report_lines.append(
                f"{source:<20} {attempts:<8} {success_count:<8} {total_news:>8,}개 ({success_rate:5.1f}%)"
            )
    
    report_lines.append("")
    
    # 6. 시스템 상태 및 권장사항
    report_lines.append("[6] 시스템 상태 및 권장사항")
    report_lines.append("-" * 80)
    
    # 상태 평가
    issues = []
    recommendations = []
    
    if success_rate >= 95:
        report_lines.append("[OK] 수집 시스템 상태: 양호 (성공률 {:.1f}%)".format(success_rate))
    elif success_rate >= 90:
        report_lines.append("[주의] 수집 시스템 상태: 보통 (성공률 {:.1f}%)".format(success_rate))
        recommendations.append("수집 안정성 개선 필요")
    else:
        report_lines.append("[경고] 수집 시스템 상태: 주의 (성공률 {:.1f}%)".format(success_rate))
        recommendations.append("수집 시스템 점검 필요")
    
    stock_code_rate = (with_stock / len(today_news) * 100) if len(today_news) > 0 else 0
    if stock_code_rate < 50:
        issues.append(f"종목 코드 추출률 낮음 ({stock_code_rate:.1f}%)")
        recommendations.append("종목 코드 추출 로직 개선 필요")
    
    if len(today_news) < 1000:
        issues.append(f"오늘 수집량 적음 ({len(today_news):,}개)")
        recommendations.append("수집 주기 또는 출처 확장 검토")
    
    report_lines.append("")
    
    if issues:
        report_lines.append("주요 이슈:")
        for issue in issues:
            report_lines.append(f"  [!] {issue}")
        report_lines.append("")
    
    if recommendations:
        report_lines.append("권장사항:")
        for rec in recommendations:
            report_lines.append(f"  [*] {rec}")
    else:
        report_lines.append("[OK] 특별한 조치 사항 없음")
    
    report_lines.append("")
    report_lines.append("=" * 80)
    report_lines.append("보고서 종료")
    report_lines.append("=" * 80)
    
    conn.close()
    
    # 파일로 저장
    report_text = "\n".join(report_lines)
    
    with open("daily_report_20260113.txt", "w", encoding="utf-8") as f:
        f.write(report_text)
    
    # UTF-8로 인코딩된 내용을 바이트 문자열로 변환하여 출력
    try:
        print(report_text.encode('utf-8').decode('utf-8'))
    except:
        # 터미널 인코딩 문제 시 파일만 저장
        pass
    
    print("\n[완료] 보고서가 'daily_report_20260113.txt' 파일로 저장되었습니다.")

if __name__ == "__main__":
    generate_daily_report()
