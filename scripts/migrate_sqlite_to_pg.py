"""
SQLite → PostgreSQL 마이그레이션 스크립트
기존 news_data.db의 데이터를 PostgreSQL로 이관

사용법:
    python scripts/migrate_sqlite_to_pg.py

환경변수 (선택):
    NEWSQUANT_DB_HOST, NEWSQUANT_DB_PORT, NEWSQUANT_DB_NAME,
    NEWSQUANT_DB_USER, NEWSQUANT_DB_PASSWORD
"""

import os
import sys
import sqlite3
from datetime import datetime

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2 import extras


def get_pg_config():
    """PostgreSQL 연결 설정"""
    try:
        from news_scraper.config import get_config
        return {
            'host': os.environ.get('NEWSQUANT_DB_HOST', get_config('database.host', 'localhost')),
            'port': int(os.environ.get('NEWSQUANT_DB_PORT', get_config('database.port', 5432))),
            'dbname': os.environ.get('NEWSQUANT_DB_NAME', get_config('database.name', 'newsquant')),
            'user': os.environ.get('NEWSQUANT_DB_USER', get_config('database.user', 'postgres')),
            'password': os.environ.get('NEWSQUANT_DB_PASSWORD', get_config('database.password', 'postgres')),
        }
    except Exception:
        return {
            'host': os.environ.get('NEWSQUANT_DB_HOST', 'localhost'),
            'port': int(os.environ.get('NEWSQUANT_DB_PORT', 5432)),
            'dbname': os.environ.get('NEWSQUANT_DB_NAME', 'newsquant'),
            'user': os.environ.get('NEWSQUANT_DB_USER', 'postgres'),
            'password': os.environ.get('NEWSQUANT_DB_PASSWORD', 'postgres'),
        }


def parse_timestamp(ts_str):
    """ISO 문자열을 datetime으로 변환"""
    if not ts_str:
        return datetime.now()
    try:
        ts_str = ts_str.replace('Z', '+00:00')
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.strptime(ts_str[:19], '%Y-%m-%dT%H:%M:%S')
    except (ValueError, TypeError):
        pass
    return datetime.now()


def create_pg_database(pg_cfg):
    """PostgreSQL 데이터베이스 생성 (없으면)"""
    dbname = pg_cfg['dbname']
    # postgres 데이터베이스에 접속하여 대상 DB 생성
    conn = psycopg2.connect(
        host=pg_cfg['host'],
        port=pg_cfg['port'],
        dbname='postgres',
        user=pg_cfg['user'],
        password=pg_cfg['password'],
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{dbname}" ENCODING \'UTF8\'')
            print(f"  데이터베이스 '{dbname}' 생성 완료")
        else:
            print(f"  데이터베이스 '{dbname}' 이미 존재")
    conn.close()


def migrate():
    sqlite_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'news_data.db')

    if not os.path.exists(sqlite_path):
        print(f"SQLite 파일을 찾을 수 없습니다: {sqlite_path}")
        print("마이그레이션 할 데이터가 없습니다. 새로운 PostgreSQL DB로 시작합니다.")
        return

    pg_cfg = get_pg_config()

    print("=" * 60)
    print("SQLite → PostgreSQL 마이그레이션")
    print("=" * 60)
    print(f"  SQLite: {sqlite_path}")
    print(f"  PostgreSQL: {pg_cfg['host']}:{pg_cfg['port']}/{pg_cfg['dbname']}")
    print()

    # 1. PostgreSQL DB 생성
    print("[1/4] PostgreSQL 데이터베이스 확인...")
    create_pg_database(pg_cfg)

    # 2. PostgreSQL 테이블 생성
    print("[2/4] PostgreSQL 테이블 생성...")
    from news_scraper.database import NewsDatabase
    pg_db = NewsDatabase()
    print("  테이블 생성 완료")

    # 3. SQLite에서 데이터 읽기
    print("[3/4] SQLite에서 데이터 읽는 중...")
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    # news 테이블
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM news")
    total_news = cursor.fetchone()[0]
    print(f"  뉴스 데이터: {total_news:,}건")

    # collection_log 테이블
    cursor.execute("SELECT COUNT(*) FROM collection_log")
    total_logs = cursor.fetchone()[0]
    print(f"  수집 로그: {total_logs:,}건")

    # 4. PostgreSQL로 데이터 이관
    print(f"[4/4] PostgreSQL로 데이터 이관 중...")
    pg_conn = psycopg2.connect(**pg_cfg)

    # news 테이블 이관 (배치)
    batch_size = 1000
    cursor.execute("SELECT * FROM news ORDER BY id")

    migrated = 0
    skipped = 0

    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break

        with pg_conn.cursor() as pg_cur:
            for row in rows:
                row_dict = dict(row)
                try:
                    pg_cur.execute("""
                        INSERT INTO news
                        (news_id, title, content, published_at, source, category,
                         url, related_stocks, sentiment_score, importance_score,
                         impact_score, timeliness_score, overall_score,
                         duplicate_count, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (news_id) DO NOTHING
                    """, (
                        row_dict.get('news_id'),
                        row_dict.get('title'),
                        row_dict.get('content'),
                        parse_timestamp(row_dict.get('published_at')),
                        row_dict.get('source'),
                        row_dict.get('category'),
                        row_dict.get('url'),
                        row_dict.get('related_stocks'),
                        row_dict.get('sentiment_score'),
                        row_dict.get('importance_score'),
                        row_dict.get('impact_score'),
                        row_dict.get('timeliness_score'),
                        row_dict.get('overall_score'),
                        row_dict.get('duplicate_count', 1),
                        parse_timestamp(row_dict.get('created_at')),
                        parse_timestamp(row_dict.get('updated_at')),
                    ))
                    migrated += 1
                except Exception as e:
                    skipped += 1
                    if skipped <= 5:
                        print(f"  경고: {row_dict.get('news_id')} 이관 실패 - {e}")

        pg_conn.commit()
        print(f"  뉴스 이관: {migrated:,}/{total_news:,} ({migrated/total_news*100:.1f}%)", end='\r')

    print(f"\n  뉴스 이관 완료: {migrated:,}건 성공, {skipped:,}건 건너뜀")

    # collection_log 이관
    cursor.execute("SELECT * FROM collection_log ORDER BY id")
    log_migrated = 0

    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break

        with pg_conn.cursor() as pg_cur:
            for row in rows:
                row_dict = dict(row)
                try:
                    pg_cur.execute("""
                        INSERT INTO collection_log
                        (source, collected_at, news_count, status, error_message)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        row_dict.get('source'),
                        parse_timestamp(row_dict.get('collected_at')),
                        row_dict.get('news_count', 0),
                        row_dict.get('status'),
                        row_dict.get('error_message'),
                    ))
                    log_migrated += 1
                except Exception as e:
                    pass

        pg_conn.commit()

    print(f"  수집 로그 이관 완료: {log_migrated:,}건")

    # 정리
    pg_conn.close()
    sqlite_conn.close()

    print()
    print("=" * 60)
    print("마이그레이션 완료!")
    print(f"  뉴스: {migrated:,}건")
    print(f"  수집 로그: {log_migrated:,}건")
    print("=" * 60)


if __name__ == '__main__':
    migrate()
