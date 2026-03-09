"""
데이터베이스 관리 모듈
PostgreSQL을 사용하여 뉴스 데이터 저장 및 조회
"""

import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import logging

import psycopg2
from psycopg2 import pool, extras, errors

logger = logging.getLogger(__name__)


def _get_pg_config() -> Dict:
    """PostgreSQL 연결 설정을 config.yaml 또는 환경변수에서 로드"""
    try:
        from .config import get_config
        pg_cfg = {
            'host': get_config('database.host', 'localhost'),
            'port': int(get_config('database.port', 5432)),
            'dbname': get_config('database.name', 'newsquant'),
            'user': get_config('database.user', 'postgres'),
            'password': get_config('database.password', 'postgres'),
        }
    except Exception:
        pg_cfg = {
            'host': 'localhost',
            'port': 5432,
            'dbname': 'newsquant',
            'user': 'postgres',
            'password': 'postgres',
        }

    # 환경변수 오버라이드
    pg_cfg['host'] = os.environ.get('NEWSQUANT_DB_HOST', pg_cfg['host'])
    pg_cfg['port'] = int(os.environ.get('NEWSQUANT_DB_PORT', pg_cfg['port']))
    pg_cfg['dbname'] = os.environ.get('NEWSQUANT_DB_NAME', pg_cfg['dbname'])
    pg_cfg['user'] = os.environ.get('NEWSQUANT_DB_USER', pg_cfg['user'])
    pg_cfg['password'] = os.environ.get('NEWSQUANT_DB_PASSWORD', pg_cfg['password'])

    return pg_cfg


class NewsDatabase:
    """뉴스 데이터베이스 관리 클래스 (PostgreSQL)"""

    _pool = None  # 클래스 레벨 커넥션 풀

    def __init__(self, db_path: str = "news_data.db"):
        """
        Args:
            db_path: 하위호환용 파라미터 (무시됨, PostgreSQL 사용)
        """
        self.db_path = db_path  # 하위호환용
        self._ensure_pool()
        self.init_database()

    @classmethod
    def _ensure_pool(cls):
        """커넥션 풀 초기화 (싱글톤)"""
        if cls._pool is None or cls._pool.closed:
            pg_cfg = _get_pg_config()
            try:
                cls._pool = pool.ThreadedConnectionPool(
                    minconn=2,
                    maxconn=10,
                    host=pg_cfg['host'],
                    port=pg_cfg['port'],
                    dbname=pg_cfg['dbname'],
                    user=pg_cfg['user'],
                    password=pg_cfg['password'],
                )
                logger.info(f"PostgreSQL 커넥션 풀 생성: {pg_cfg['host']}:{pg_cfg['port']}/{pg_cfg['dbname']}")
            except psycopg2.OperationalError as e:
                logger.error(f"PostgreSQL 연결 실패: {e}")
                raise

    def get_connection(self):
        """커넥션 풀에서 연결 반환"""
        self._ensure_pool()
        conn = self._pool.getconn()
        conn.autocommit = False
        return conn

    def _put_connection(self, conn):
        """커넥션을 풀에 반환"""
        if conn and self._pool and not self._pool.closed:
            self._pool.putconn(conn)

    def init_database(self):
        """데이터베이스 초기화 및 테이블 생성"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                # 뉴스 테이블 생성
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS news (
                        id SERIAL PRIMARY KEY,
                        news_id TEXT UNIQUE NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT,
                        published_at TIMESTAMP NOT NULL,
                        source TEXT NOT NULL,
                        category TEXT,
                        url TEXT NOT NULL,
                        related_stocks TEXT,
                        sentiment_score DOUBLE PRECISION,
                        importance_score DOUBLE PRECISION,
                        impact_score DOUBLE PRECISION,
                        timeliness_score DOUBLE PRECISION,
                        overall_score DOUBLE PRECISION,
                        duplicate_count INTEGER DEFAULT 1,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """)

                # 인덱스 생성
                indexes = [
                    ("idx_news_news_id", "news", "news_id"),
                    ("idx_news_published_at", "news", "published_at"),
                    ("idx_news_source", "news", "source"),
                    ("idx_news_category", "news", "category"),
                    ("idx_news_overall_score", "news", "overall_score"),
                    ("idx_news_sentiment_score", "news", "sentiment_score"),
                ]
                for idx_name, table, column in indexes:
                    cursor.execute(f"""
                        CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})
                    """)

                # 뉴스 수집 로그 테이블
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS collection_log (
                        id SERIAL PRIMARY KEY,
                        source TEXT NOT NULL,
                        collected_at TIMESTAMP DEFAULT NOW(),
                        news_count INTEGER DEFAULT 0,
                        status TEXT,
                        error_message TEXT
                    )
                """)

            conn.commit()
            logger.info("PostgreSQL 데이터베이스 초기화 완료")
        except Exception as e:
            conn.rollback()
            logger.error(f"데이터베이스 초기화 오류: {e}")
            raise
        finally:
            self._put_connection(conn)

    @staticmethod
    def _ensure_utf8(text):
        """문자열이 올바른 UTF-8인지 확인하고 정리"""
        if not text:
            return text
        if isinstance(text, bytes):
            for encoding in ['utf-8', 'euc-kr', 'cp949', 'latin1']:
                try:
                    return text.decode(encoding, errors='strict')
                except (UnicodeDecodeError, UnicodeError):
                    continue
            return text.decode('utf-8', errors='replace')
        try:
            if any(ord(c) > 0x7F and ord(c) < 0x100 for c in text):
                for encoding in ['euc-kr', 'cp949']:
                    try:
                        recovered = text.encode('latin1').decode(encoding)
                        if any('\uac00' <= char <= '\ud7a3' for char in recovered):
                            return recovered
                    except Exception:
                        continue
        except Exception:
            pass
        return text

    @staticmethod
    def _parse_timestamp(ts_str: str) -> Optional[datetime]:
        """ISO 문자열 또는 다양한 형식을 datetime으로 변환"""
        if not ts_str:
            return datetime.now()
        if isinstance(ts_str, datetime):
            return ts_str
        try:
            # ISO 형식 파싱
            ts_str = ts_str.replace('Z', '+00:00')
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            pass
        try:
            # "2024-01-15 14:30:00" 형식
            return datetime.strptime(ts_str[:19], '%Y-%m-%dT%H:%M:%S')
        except (ValueError, TypeError):
            pass
        return datetime.now()

    def insert_news(self, news_data: Dict) -> bool:
        """뉴스 데이터 삽입"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                title = self._ensure_utf8(news_data.get('title'))
                content = self._ensure_utf8(news_data.get('content', ''))
                category = self._ensure_utf8(news_data.get('category', ''))
                related_stocks = self._ensure_utf8(news_data.get('related_stocks', ''))
                news_id = news_data.get('news_id')
                published_at = self._parse_timestamp(news_data.get('published_at'))

                # UPSERT: 존재하면 duplicate_count 증가, 없으면 INSERT
                cursor.execute("""
                    INSERT INTO news
                    (news_id, title, content, published_at, source, category,
                     url, related_stocks, sentiment_score, importance_score,
                     impact_score, timeliness_score, overall_score, duplicate_count, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, NOW())
                    ON CONFLICT (news_id) DO UPDATE SET
                        duplicate_count = news.duplicate_count + 1,
                        updated_at = NOW()
                """, (
                    news_id, title, content, published_at,
                    news_data.get('source'), category,
                    news_data.get('url'), related_stocks,
                    news_data.get('sentiment_score'),
                    news_data.get('importance_score'),
                    news_data.get('impact_score'),
                    news_data.get('timeliness_score'),
                    news_data.get('overall_score'),
                ))

            conn.commit()
            return True
        except errors.UniqueViolation as e:
            conn.rollback()
            logger.debug(f"중복 뉴스 오류: {news_data.get('news_id')} - {e}")
            return False
        except Exception as e:
            conn.rollback()
            logger.error(f"뉴스 삽입 오류: {e}")
            return False
        finally:
            self._put_connection(conn)

    def insert_news_batch(self, news_list: List[Dict]) -> int:
        """여러 뉴스 데이터 일괄 삽입 (단일 트랜잭션)"""
        if not news_list:
            return 0

        conn = self.get_connection()
        success_count = 0

        try:
            with conn.cursor() as cursor:
                for news_data in news_list:
                    try:
                        title = self._ensure_utf8(news_data.get('title'))
                        content = self._ensure_utf8(news_data.get('content', ''))
                        category = self._ensure_utf8(news_data.get('category', ''))
                        related_stocks = self._ensure_utf8(news_data.get('related_stocks', ''))
                        news_id = news_data.get('news_id')
                        published_at = self._parse_timestamp(news_data.get('published_at'))

                        cursor.execute("""
                            INSERT INTO news
                            (news_id, title, content, published_at, source, category,
                             url, related_stocks, sentiment_score, importance_score,
                             impact_score, timeliness_score, overall_score, duplicate_count, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, NOW())
                            ON CONFLICT (news_id) DO UPDATE SET
                                duplicate_count = news.duplicate_count + 1,
                                updated_at = NOW()
                        """, (
                            news_id, title, content, published_at,
                            news_data.get('source'), category,
                            news_data.get('url'), related_stocks,
                            news_data.get('sentiment_score'),
                            news_data.get('importance_score'),
                            news_data.get('impact_score'),
                            news_data.get('timeliness_score'),
                            news_data.get('overall_score'),
                        ))
                        success_count += 1
                    except errors.UniqueViolation as e:
                        logger.debug(f"중복 뉴스: {news_data.get('news_id')} - {e}")
                    except Exception as e:
                        logger.error(f"뉴스 삽입 오류: {e}")

            conn.commit()
        except Exception as e:
            logger.error(f"배치 삽입 트랜잭션 오류: {e}")
            conn.rollback()
        finally:
            self._put_connection(conn)

        return success_count

    def _rows_to_dicts(self, cursor) -> List[Dict]:
        """커서 결과를 딕셔너리 리스트로 변환"""
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        result = []
        for row in rows:
            d = dict(zip(columns, row))
            # datetime을 ISO 문자열로 변환 (하위호환)
            for key in ('published_at', 'created_at', 'updated_at', 'collected_at'):
                if key in d and isinstance(d[key], datetime):
                    d[key] = d[key].isoformat()
            result.append(d)
        return result

    def get_news_by_date_range(self, start_date: str, end_date: str,
                                source: Optional[str] = None) -> List[Dict]:
        """날짜 범위로 뉴스 조회"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                start_ts = self._parse_timestamp(start_date)
                end_ts = self._parse_timestamp(end_date)

                if source:
                    cursor.execute("""
                        SELECT * FROM news
                        WHERE published_at >= %s AND published_at <= %s AND source = %s
                        ORDER BY published_at DESC
                    """, (start_ts, end_ts, source))
                else:
                    cursor.execute("""
                        SELECT * FROM news
                        WHERE published_at >= %s AND published_at <= %s
                        ORDER BY published_at DESC
                    """, (start_ts, end_ts))

                return self._rows_to_dicts(cursor)
        except Exception as e:
            logger.error(f"날짜 범위 조회 오류: {e}")
            return []
        finally:
            self._put_connection(conn)

    def get_latest_news(self, limit: int = 100, source: Optional[str] = None) -> List[Dict]:
        """최신 뉴스 조회"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                if source:
                    cursor.execute("""
                        SELECT * FROM news
                        WHERE source = %s
                        ORDER BY published_at DESC
                        LIMIT %s
                    """, (source, limit))
                else:
                    cursor.execute("""
                        SELECT * FROM news
                        ORDER BY published_at DESC
                        LIMIT %s
                    """, (limit,))

                return self._rows_to_dicts(cursor)
        except Exception as e:
            logger.error(f"최신 뉴스 조회 오류: {e}")
            return []
        finally:
            self._put_connection(conn)

    def log_collection(self, source: str, news_count: int,
                      status: str = "success", error_message: Optional[str] = None):
        """수집 로그 기록"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO collection_log (source, collected_at, news_count, status, error_message)
                    VALUES (%s, NOW(), %s, %s, %s)
                """, (source, news_count, status, error_message))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"수집 로그 기록 오류: {e}")
        finally:
            self._put_connection(conn)

    def get_collection_stats(self, days: int = 7) -> Dict:
        """최근 N일간 수집 통계 조회"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                # 전체 뉴스 개수
                cursor.execute("SELECT COUNT(*) FROM news")
                total_news = cursor.fetchone()[0]

                # 출처별 뉴스 개수
                cursor.execute("""
                    SELECT source, COUNT(*) as count
                    FROM news
                    GROUP BY source
                """)
                source_counts = {row[0]: row[1] for row in cursor.fetchall()}

                # 최근 수집 로그
                cursor.execute("""
                    SELECT source, SUM(news_count) as total, COUNT(*) as attempts
                    FROM collection_log
                    WHERE collected_at >= NOW() - INTERVAL '%s days'
                    GROUP BY source
                """, (days,))

                recent_stats = {row[0]: {'total': row[1], 'attempts': row[2]}
                               for row in cursor.fetchall()}

            return {
                'total_news': total_news,
                'by_source': source_counts,
                'recent_collection': recent_stats
            }
        except Exception as e:
            logger.error(f"통계 조회 오류: {e}")
            return {'total_news': 0, 'by_source': {}, 'recent_collection': {}}
        finally:
            self._put_connection(conn)

    def get_news_by_stock(self, stock_code: str, limit: int = 50) -> List[Dict]:
        """특정 종목 관련 뉴스 조회"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM news
                    WHERE related_stocks LIKE %s
                    ORDER BY published_at DESC
                    LIMIT %s
                """, (f'%{stock_code}%', limit))

                return self._rows_to_dicts(cursor)
        except Exception as e:
            logger.error(f"종목 뉴스 조회 오류: {e}")
            return []
        finally:
            self._put_connection(conn)

    def get_news_by_stocks(self, stock_codes: List[str], limit_per_stock: int = 10) -> Dict[str, List[Dict]]:
        """여러 종목의 뉴스를 한 번에 조회"""
        conn = self.get_connection()
        try:
            result = {}
            with conn.cursor() as cursor:
                for stock_code in stock_codes:
                    cursor.execute("""
                        SELECT * FROM news
                        WHERE related_stocks LIKE %s
                        ORDER BY published_at DESC
                        LIMIT %s
                    """, (f'%{stock_code}%', limit_per_stock))
                    result[stock_code] = self._rows_to_dicts(cursor)
            return result
        except Exception as e:
            logger.error(f"멀티 종목 뉴스 조회 오류: {e}")
            return {}
        finally:
            self._put_connection(conn)

    def search_news(self, keyword: Optional[str] = None,
                   min_sentiment: Optional[float] = None,
                   max_sentiment: Optional[float] = None,
                   min_overall_score: Optional[float] = None,
                   source: Optional[str] = None,
                   limit: int = 100) -> List[Dict]:
        """뉴스 검색 (고급 필터링)"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                query = "SELECT * FROM news WHERE 1=1"
                params = []

                if keyword:
                    query += " AND (title ILIKE %s OR content ILIKE %s)"
                    params.extend([f'%{keyword}%', f'%{keyword}%'])

                if min_sentiment is not None:
                    query += " AND sentiment_score >= %s"
                    params.append(min_sentiment)

                if max_sentiment is not None:
                    query += " AND sentiment_score <= %s"
                    params.append(max_sentiment)

                if min_overall_score is not None:
                    query += " AND overall_score >= %s"
                    params.append(min_overall_score)

                if source:
                    query += " AND source = %s"
                    params.append(source)

                query += " ORDER BY published_at DESC LIMIT %s"
                params.append(limit)

                cursor.execute(query, params)
                return self._rows_to_dicts(cursor)
        except Exception as e:
            logger.error(f"뉴스 검색 오류: {e}")
            return []
        finally:
            self._put_connection(conn)
