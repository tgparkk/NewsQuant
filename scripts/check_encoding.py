"""
데이터베이스에 저장된 한글 인코딩 확인 스크립트
"""

import sys
import io
import sqlite3
from news_scraper.database import NewsDatabase

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def check_encoding():
    """데이터베이스에 저장된 한글 인코딩 확인"""
    db = NewsDatabase()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("=" * 80)
    print("데이터베이스 한글 인코딩 확인")
    print("=" * 80)
    print()
    
    # naver_finance 최신 뉴스 5개 조회
    cursor.execute("""
        SELECT news_id, title, content, url, source
        FROM news
        WHERE source = 'naver_finance'
        ORDER BY created_at DESC
        LIMIT 5
    """)
    
    rows = cursor.fetchall()
    
    print(f"[naver_finance] 최신 5개 뉴스의 제목 확인:")
    print("-" * 80)
    
    for idx, row in enumerate(rows, 1):
        news_id, title, content, url, source = row
        print(f"\n{idx}. 뉴스 ID: {news_id}")
        print(f"   제목 (원본): {repr(title)}")
        print(f"   제목 (표시): {title}")
        print(f"   제목 길이: {len(title)} bytes")
        print(f"   URL: {url}")
        
        # 바이트 확인
        if title:
            title_bytes = title.encode('utf-8', errors='replace')
            print(f"   UTF-8 바이트: {title_bytes[:50]}...")
    
    print()
    print("=" * 80)
    print()
    
    # hankyung과 비교
    cursor.execute("""
        SELECT news_id, title, content, url, source
        FROM news
        WHERE source = 'hankyung'
        ORDER BY created_at DESC
        LIMIT 3
    """)
    
    rows = cursor.fetchall()
    
    print(f"[hankyung] 최신 3개 뉴스의 제목 확인 (정상 참고용):")
    print("-" * 80)
    
    for idx, row in enumerate(rows, 1):
        news_id, title, content, url, source = row
        print(f"\n{idx}. 뉴스 ID: {news_id}")
        print(f"   제목: {title}")
        print(f"   제목 길이: {len(title)} bytes")
    
    conn.close()
    print()
    print("=" * 80)

if __name__ == "__main__":
    check_encoding()
