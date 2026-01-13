"""
시스템 문제점 종합 점검 스크립트
"""

from datetime import datetime, timedelta
from news_scraper.database import NewsDatabase
from collections import Counter, defaultdict
import sqlite3

def check_all_issues():
    """모든 문제점 종합 점검"""
    db = NewsDatabase()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    issues = []
    warnings = []
    recommendations = []
    
    print("=" * 80)
    print("시스템 문제점 종합 점검")
    print("=" * 80)
    print(f"점검 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 1. 최근 오류 로그 점검
    print("[1] 최근 오류 로그 점검")
    print("-" * 80)
    
    cursor.execute("""
        SELECT source, collected_at, error_message, COUNT(*) as count
        FROM collection_log
        WHERE status = 'error'
        AND datetime(collected_at) >= datetime('now', '-7 days')
        GROUP BY error_message
        ORDER BY count DESC
        LIMIT 10
    """)
    
    recent_errors = cursor.fetchall()
    
    if recent_errors:
        print(f"[주의] 최근 7일간 오류 발생: {len(recent_errors)}개 유형")
        print()
        for source, collected_at, error_msg, count in recent_errors:
            print(f"  [{count}회] {error_msg[:100]}")
            issues.append(f"오류 발생: {error_msg[:50]}... ({count}회)")
    else:
        print("[OK] 최근 7일간 오류 없음")
    print()
    
    # 2. 종목 코드 추출 문제 점검
    print("[2] 종목 코드 추출 문제")
    print("-" * 80)
    
    today = datetime.now()
    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    today_news = db.get_news_by_date_range(
        start_date.isoformat(),
        end_date.isoformat()
    )
    
    # 출처별 종목 코드 추출률
    source_stock_stats = defaultdict(lambda: {'total': 0, 'with_stock': 0})
    
    for news in today_news:
        source = news.get('source', 'Unknown')
        source_stock_stats[source]['total'] += 1
        if news.get('related_stocks'):
            source_stock_stats[source]['with_stock'] += 1
    
    print("출처별 종목 코드 추출률:")
    for source, stats in sorted(source_stock_stats.items()):
        if stats['total'] > 0:
            rate = (stats['with_stock'] / stats['total']) * 100
            status = "[OK]" if rate >= 50 else "[주의]" if rate >= 30 else "[경고]"
            print(f"  {status} {source:20s}: {stats['with_stock']:4d}/{stats['total']:4d} ({rate:5.1f}%)")
            
            if rate < 50:
                issues.append(f"{source}의 종목 코드 추출률 낮음 ({rate:.1f}%)")
                recommendations.append(f"{source} 크롤러의 종목 코드 추출 로직 개선 필요")
    print()
    
    # 3. 데이터 품질 문제
    print("[3] 데이터 품질 문제")
    print("-" * 80)
    
    # 내용이 너무 짧은 뉴스
    short_content_by_source = defaultdict(lambda: {'total': 0, 'short': 0})
    
    for news in today_news:
        source = news.get('source', 'Unknown')
        content_len = len(news.get('content', '') or '')
        short_content_by_source[source]['total'] += 1
        if content_len < 50:
            short_content_by_source[source]['short'] += 1
    
    print("출처별 내용 부족률 (50자 미만):")
    for source, stats in sorted(short_content_by_source.items()):
        if stats['total'] > 0:
            rate = (stats['short'] / stats['total']) * 100
            status = "[OK]" if rate < 10 else "[주의]" if rate < 30 else "[경고]"
            print(f"  {status} {source:20s}: {stats['short']:4d}/{stats['total']:4d} ({rate:5.1f}%)")
            
            if rate > 30:
                issues.append(f"{source}의 내용 부족률 높음 ({rate:.1f}%)")
                recommendations.append(f"{source} 크롤러의 본문 추출 로직 개선 필요")
    print()
    
    # 4. 감성 분석 문제
    print("[4] 감성 분석 문제")
    print("-" * 80)
    
    sentiment_stats = {
        'total': len(today_news),
        'analyzed': sum(1 for n in today_news if n.get('sentiment_score') is not None),
        'neutral': sum(1 for n in today_news if n.get('sentiment_score') == 0.0),
        'positive': sum(1 for n in today_news if n.get('sentiment_score', 0) > 0),
        'negative': sum(1 for n in today_news if n.get('sentiment_score', 0) < 0),
    }
    
    analyzed_rate = (sentiment_stats['analyzed'] / sentiment_stats['total']) * 100 if sentiment_stats['total'] > 0 else 0
    neutral_rate = (sentiment_stats['neutral'] / sentiment_stats['analyzed']) * 100 if sentiment_stats['analyzed'] > 0 else 0
    
    print(f"감성 분석 완료율: {analyzed_rate:.1f}% ({sentiment_stats['analyzed']}/{sentiment_stats['total']})")
    print(f"  긍정: {sentiment_stats['positive']:4d}개 ({sentiment_stats['positive']/sentiment_stats['analyzed']*100:.1f}%)")
    print(f"  중립: {sentiment_stats['neutral']:4d}개 ({neutral_rate:.1f}%)")
    print(f"  부정: {sentiment_stats['negative']:4d}개 ({sentiment_stats['negative']/sentiment_stats['analyzed']*100:.1f}%)")
    print()
    
    if neutral_rate > 60:
        warnings.append(f"중립 감성이 과도하게 많음 ({neutral_rate:.1f}%)")
        recommendations.append("감성 분석 모델의 민감도 조정 검토 필요")
    
    if analyzed_rate < 95:
        issues.append(f"감성 분석 미완료 뉴스 있음 ({100-analyzed_rate:.1f}%)")
        recommendations.append("감성 분석 프로세스 점검 필요")
    else:
        print("[OK] 감성 분석 완료율 양호")
    print()
    
    # 5. 중복 뉴스 문제
    print("[5] 중복 뉴스 점검")
    print("-" * 80)
    
    # 제목 기반 중복 체크
    title_counts = Counter()
    for news in today_news:
        title = news.get('title', '').strip()
        if title:
            title_counts[title] += 1
    
    duplicates = [(title, count) for title, count in title_counts.items() if count > 1]
    
    if duplicates:
        print(f"[주의] 중복된 제목 발견: {len(duplicates)}개")
        print()
        print("상위 10개 중복 제목:")
        for i, (title, count) in enumerate(sorted(duplicates, key=lambda x: x[1], reverse=True)[:10], 1):
            print(f"  {i}. [{count}회] {title[:60]}")
        
        total_duplicates = sum(count - 1 for _, count in duplicates)
        duplicate_rate = (total_duplicates / len(today_news)) * 100 if len(today_news) > 0 else 0
        
        if duplicate_rate > 5:
            issues.append(f"중복 뉴스 비율 높음 ({duplicate_rate:.1f}%)")
            recommendations.append("중복 제거 로직 강화 필요")
    else:
        print("[OK] 중복 뉴스 없음")
    print()
    
    # 6. 수집 주기 문제
    print("[6] 수집 주기 점검")
    print("-" * 80)
    
    cursor.execute("""
        SELECT source, 
               MAX(datetime(collected_at)) as last_collection,
               julianday('now') - julianday(MAX(datetime(collected_at))) as hours_ago
        FROM collection_log
        WHERE status = 'success'
        GROUP BY source
    """)
    
    last_collections = cursor.fetchall()
    
    print("출처별 마지막 수집 시각:")
    for source, last_time, hours_ago in last_collections:
        hours_ago = hours_ago * 24  # 일을 시간으로 변환
        status = "[OK]" if hours_ago < 1 else "[주의]" if hours_ago < 3 else "[경고]"
        print(f"  {status} {source:20s}: {last_time} ({hours_ago:.1f}시간 전)")
        
        if hours_ago > 3:
            issues.append(f"{source} 수집이 {hours_ago:.1f}시간 전에 멈춤")
            recommendations.append(f"{source} 크롤러 동작 상태 점검 필요")
    print()
    
    # 7. 데이터베이스 크기 점검
    print("[7] 데이터베이스 상태")
    print("-" * 80)
    
    cursor.execute("SELECT COUNT(*) FROM news")
    total_news_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM collection_log")
    total_log_count = cursor.fetchone()[0]
    
    # 7일 이상 된 뉴스
    cursor.execute("""
        SELECT COUNT(*) 
        FROM news 
        WHERE datetime(published_at) < datetime('now', '-7 days')
    """)
    old_news_count = cursor.fetchone()[0]
    
    print(f"전체 뉴스 건수: {total_news_count:,}개")
    print(f"전체 로그 건수: {total_log_count:,}개")
    print(f"7일 이상 된 뉴스: {old_news_count:,}개 ({old_news_count/total_news_count*100:.1f}%)")
    print()
    
    if old_news_count > 10000:
        warnings.append(f"오래된 뉴스 데이터 많음 ({old_news_count:,}개)")
        recommendations.append("데이터 보관 정책 수립 및 정리 필요")
    
    # 8. 시간대별 수집 패턴
    print("[8] 시간대별 수집 패턴")
    print("-" * 80)
    
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
        # 현재 시각
        current_hour = datetime.now().hour
        
        # 최근 3시간 수집량 확인
        recent_3h_count = sum(hour_counts.get(h, 0) for h in range(max(0, current_hour-2), current_hour+1))
        
        print(f"최근 3시간 수집량: {recent_3h_count}개")
        
        if current_hour >= 9 and current_hour <= 15:  # 장중
            if recent_3h_count < 100:
                warnings.append(f"장중 수집량 적음 (최근 3시간: {recent_3h_count}개)")
                recommendations.append("장중 수집 주기 단축 또는 출처 확대 필요")
        
        # 00시에 수집량이 과도하게 많은지 확인
        midnight_count = hour_counts.get(0, 0)
        if midnight_count > 1000:
            warnings.append(f"00시 수집량 과다 ({midnight_count}개) - DART 공시일 가능성")
            print(f"  [참고] 00시 수집량: {midnight_count}개 (DART 공시 일괄 처리)")
    print()
    
    # 종합 결과
    print("=" * 80)
    print("종합 분석 결과")
    print("=" * 80)
    print()
    
    if issues:
        print(f"[심각] 심각한 문제점: {len(issues)}개")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        print()
    else:
        print("[OK] 심각한 문제점 없음")
        print()
    
    if warnings:
        print(f"[경고] 경고 사항: {len(warnings)}개")
        for i, warning in enumerate(warnings, 1):
            print(f"  {i}. {warning}")
        print()
    else:
        print("[OK] 경고 사항 없음")
        print()
    
    if recommendations:
        print(f"[권장] 개선 권장사항: {len(recommendations)}개")
        for i, rec in enumerate(recommendations, 1):
            print(f"  {i}. {rec}")
        print()
    
    # 우선순위 평가
    print("=" * 80)
    print("조치 우선순위")
    print("=" * 80)
    print()
    
    priority_actions = []
    
    # 종목 코드 추출률 문제
    overall_stock_rate = sum(1 for n in today_news if n.get('related_stocks')) / len(today_news) * 100 if today_news else 0
    if overall_stock_rate < 50:
        priority_actions.append({
            'priority': 1,
            'title': '종목 코드 추출률 개선',
            'current': f'{overall_stock_rate:.1f}%',
            'target': '50% 이상',
            'impact': '높음 - 종목 분석의 핵심 기능'
        })
    
    # 중복 뉴스 문제
    if duplicates and len(duplicates) > 50:
        priority_actions.append({
            'priority': 2,
            'title': '중복 뉴스 제거 로직 강화',
            'current': f'{len(duplicates)}개 중복',
            'target': '10개 미만',
            'impact': '중간 - 데이터 품질 개선'
        })
    
    # 감성 분석 중립 비율
    if neutral_rate > 60:
        priority_actions.append({
            'priority': 3,
            'title': '감성 분석 민감도 조정',
            'current': f'중립 {neutral_rate:.1f}%',
            'target': '중립 40% 미만',
            'impact': '중간 - 분석 정확도 향상'
        })
    
    if priority_actions:
        for action in sorted(priority_actions, key=lambda x: x['priority']):
            print(f"[우선순위 {action['priority']}] {action['title']}")
            print(f"  현재 상태: {action['current']}")
            print(f"  목표: {action['target']}")
            print(f"  영향도: {action['impact']}")
            print()
    else:
        print("[OK] 긴급 조치 필요 사항 없음")
        print()
    
    print("=" * 80)
    
    conn.close()

if __name__ == "__main__":
    check_all_issues()
