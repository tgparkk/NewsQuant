"""
수집 로그 확인 스크립트
"""

from datetime import datetime, timedelta
from news_scraper.database import NewsDatabase
import sqlite3

def check_collection_log():
    """수집 로그 확인"""
    db = NewsDatabase()
    
    print("=" * 70)
    print("수집 로그 확인 리포트")
    print("=" * 70)
    print(f"조회 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # 최근 24시간 수집 로그
    print("[1] 최근 24시간 수집 로그")
    print("-" * 70)
    cursor.execute("""
        SELECT source, collected_at, news_count, status, error_message
        FROM collection_log
        WHERE datetime(collected_at) >= datetime('now', '-1 day')
        ORDER BY collected_at DESC
        LIMIT 50
    """)
    
    logs = cursor.fetchall()
    if logs:
        print(f"총 {len(logs)}개의 수집 기록")
        print()
        for log in logs:
            source, collected_at, news_count, status, error_message = log
            status_icon = "[OK]" if status == "success" else "[ERR]"
            print(f"{status_icon} [{source:15s}] {collected_at[:19]} | {news_count:4d}개 | {status}")
            if error_message:
                print(f"    오류: {error_message}")
    else:
        print("최근 24시간 수집 기록이 없습니다.")
    print()
    
    # 출처별 최근 수집 통계
    print("[2] 출처별 최근 수집 통계 (최근 7일)")
    print("-" * 70)
    cursor.execute("""
        SELECT source, 
               COUNT(*) as attempts,
               SUM(news_count) as total_news,
               SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
               SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count
        FROM collection_log
        WHERE datetime(collected_at) >= datetime('now', '-7 days')
        GROUP BY source
        ORDER BY total_news DESC
    """)
    
    stats = cursor.fetchall()
    if stats:
        for stat in stats:
            source, attempts, total_news, success_count, error_count = stat
            success_rate = (success_count / attempts * 100) if attempts > 0 else 0
            avg_per_collection = (total_news / attempts) if attempts > 0 else 0
            print(f"  {source:20s}:")
            print(f"    시도 횟수: {attempts:4d}회")
            print(f"    성공 횟수: {success_count:4d}회 ({success_rate:.1f}%)")
            print(f"    실패 횟수: {error_count:4d}회")
            print(f"    총 수집: {total_news:6,}개")
            print(f"    평균 수집: {avg_per_collection:.1f}개/회")
            print()
    else:
        print("최근 7일 수집 기록이 없습니다.")
    print()
    
    # 시간대별 수집 현황 (최근 24시간)
    print("[3] 시간대별 수집 현황 (최근 24시간)")
    print("-" * 70)
    cursor.execute("""
        SELECT strftime('%Y-%m-%d %H:00', collected_at) as hour,
               COUNT(*) as attempts,
               SUM(news_count) as total_news
        FROM collection_log
        WHERE datetime(collected_at) >= datetime('now', '-1 day')
        GROUP BY hour
        ORDER BY hour DESC
        LIMIT 24
    """)
    
    hourly_stats = cursor.fetchall()
    if hourly_stats:
        for hour_stat in hourly_stats:
            hour, attempts, total_news = hour_stat
            print(f"  {hour}: {attempts:3d}회 시도, {total_news:5,}개 수집")
    else:
        print("최근 24시간 수집 기록이 없습니다.")
    print()
    
    # 오류 발생 기록
    print("[4] 최근 오류 발생 기록")
    print("-" * 70)
    cursor.execute("""
        SELECT source, collected_at, error_message
        FROM collection_log
        WHERE status = 'error'
        ORDER BY collected_at DESC
        LIMIT 20
    """)
    
    errors = cursor.fetchall()
    if errors:
        print(f"총 {len(errors)}개의 오류 기록")
        print()
        for error in errors:
            source, collected_at, error_message = error
            print(f"  [{source:15s}] {collected_at[:19]}")
            print(f"    {error_message}")
            print()
    else:
        print("최근 오류 기록이 없습니다. [OK]")
    print()
    
    # 전체 통계
    print("[5] 전체 수집 통계")
    print("-" * 70)
    cursor.execute("SELECT COUNT(*) FROM collection_log")
    total_logs = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM collection_log WHERE status = 'success'")
    total_success = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM collection_log WHERE status = 'error'")
    total_errors = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(news_count) FROM collection_log")
    total_collected = cursor.fetchone()[0] or 0
    
    print(f"전체 수집 시도: {total_logs:,}회")
    print(f"성공: {total_success:,}회 ({total_success/total_logs*100:.1f}%)" if total_logs > 0 else "성공: 0회")
    print(f"실패: {total_errors:,}회 ({total_errors/total_logs*100:.1f}%)" if total_logs > 0 else "실패: 0회")
    print(f"총 수집된 뉴스: {total_collected:,}개")
    print()
    
    conn.close()
    print("=" * 70)

if __name__ == "__main__":
    check_collection_log()
