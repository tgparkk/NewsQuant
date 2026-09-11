"""
데이터베이스 관리 모듈
PostgreSQL을 사용하여 뉴스 데이터 저장 및 조회
"""

import json
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

            # 스펙 B: 섹터 뉴스 점수 표 (실패해도 뉴스 수집은 계속 — 집계 잡이 나중에 다시 실패를 보고한다)
            try:
                self.init_sector_news_tables()
            except Exception as e:
                logger.error(f"[섹터뉴스] 표 초기화 실패(수집은 계속): {e}")

            # 신호 원장 표 (실패해도 뉴스 수집은 계속 — 스냅샷 잡이 나중에 다시 보고한다)
            try:
                self.init_signal_ledger_table()
            except Exception as e:
                logger.error(f"[신호원장] 표 초기화 실패(수집은 계속): {e}")
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

                # UPSERT: 존재하면 duplicate_count 증가, 없으면 INSERT.
                # content 는 «더 긴 쪽» 을 남긴다 - 크롤러가 사이클당 최신 N 건만
                # 전문을 받으므로, 예산 밖이라 목록 요약만 저장됐던 기사가 나중에
                # 전문과 함께 다시 들어오면 채워져야 한다. 구 규칙은 content 를
                # 건드리지 않아 한 번 비면 영구히 비었다 (2026-09-11 한경 사례).
                cursor.execute("""
                    INSERT INTO news
                    (news_id, title, content, published_at, source, category,
                     url, related_stocks, sentiment_score, importance_score,
                     impact_score, timeliness_score, overall_score, duplicate_count, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, NOW())
                    ON CONFLICT (news_id) DO UPDATE SET
                        content = CASE
                            WHEN COALESCE(length(EXCLUDED.content), 0)
                               > COALESCE(length(news.content), 0)
                            THEN EXCLUDED.content ELSE news.content END,
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
                                content = CASE
                                    WHEN COALESCE(length(EXCLUDED.content), 0)
                                       > COALESCE(length(news.content), 0)
                                    THEN EXCLUDED.content ELSE news.content END,
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

    # ------------------------------------------------------------------
    # 섹터 뉴스 점수 (스펙 B, 2026-09-06) — 봇(kis-trading-template)이 읽는다
    # ------------------------------------------------------------------
    # computed_at DEFAULT now() 는 서버 세션 타임존(현재 Asia/Seoul)으로 쓰인다.
    # 봇의 60분 staleness 체크가 이 값을 KST 벽시계와 비교하므로,
    # DB 의 TimeZone GUC 는 Asia/Seoul 로 유지되어야 한다.
    SECTOR_NEWS_DDL = (
        """
        CREATE TABLE IF NOT EXISTS sector_news_score (
            trade_date    date        NOT NULL,
            taxonomy      text        NOT NULL DEFAULT 'ksic3',
            sector_key    text        NOT NULL,
            sector_name   text,
            window_start  timestamp   NOT NULL,
            window_end    timestamp   NOT NULL,
            n_news        integer     NOT NULL,
            n_dir         integer     NOT NULL,
            n_kw          integer     NOT NULL,
            n_stock       integer     NOT NULL,
            n_pos         integer     NOT NULL,
            n_neg         integer     NOT NULL,
            score_raw     double precision NOT NULL,
            score_norm    double precision NOT NULL,
            score_signed  double precision NOT NULL,
            top_news      jsonb,
            dict_version  text,
            computed_at   timestamp   NOT NULL DEFAULT now(),
            PRIMARY KEY (trade_date, taxonomy, sector_key)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_sns_date ON sector_news_score (trade_date, computed_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS news_sector_hit (
            trade_date    date    NOT NULL,
            news_id       text    NOT NULL,
            sector_key    text    NOT NULL,
            route         text    NOT NULL,
            routes        text    NOT NULL,
            matched       text,
            w_match       double precision NOT NULL,
            contribution  double precision NOT NULL,
            computed_at   timestamp NOT NULL DEFAULT now(),
            PRIMARY KEY (trade_date, news_id, sector_key)
        )
        """,
    )
    # DB 관례: 67표 전부 robotrader 소유. NewsQuant 는 postgres 로 붙으므로 만든 뒤 넘긴다.
    SECTOR_NEWS_OWNER_SQL = (
        "ALTER TABLE sector_news_score OWNER TO robotrader",
        "ALTER TABLE news_sector_hit OWNER TO robotrader",
    )

    def init_sector_news_tables(self) -> None:
        """DDL(멱등) + OWNER 변경. OWNER 실패는 WARNING(권한 없는 롤일 때)."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for sql in self.SECTOR_NEWS_DDL:
                    cur.execute(sql)
            conn.commit()
            for sql in self.SECTOR_NEWS_OWNER_SQL:
                try:
                    with conn.cursor() as cur:
                        cur.execute(sql)
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logger.warning(f"[섹터뉴스] OWNER 변경 실패(무시): {sql} → {e}")
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_connection(conn)

    def get_news_in_window(self, start: datetime, end: datetime) -> List[Dict]:
        """창 (start, end] 안의 뉴스. 집계에 필요한 열만."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT news_id, title, content, source, category,
                           sentiment_score, related_stocks, published_at
                    FROM news
                    WHERE published_at > %s AND published_at <= %s
                    ORDER BY published_at, news_id
                """, (start, end))
                return self._rows_to_dicts(cur)
        finally:
            conn.rollback()
            self._put_connection(conn)

    def get_sector_map_as_of(self, as_of, codes: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
        """스펙 A `fn_sector_map_as_of(as_of)` → ({code: ksic3}, {ksic3: name}).
        함수가 없으면 psycopg2.errors.UndefinedFunction 이 그대로 올라간다 — 호출자(잡)가 경로 B 를 끈다."""
        if not codes:
            return {}, {}
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT stock_code, left(ksic_code, 3) AS ksic3, ksic3_name
                    FROM fn_sector_map_as_of(%s)
                    WHERE stock_code = ANY(%s) AND ksic_code IS NOT NULL AND length(ksic_code) >= 3
                """, (as_of, list(codes)))
                code_map: Dict[str, str] = {}
                names: Dict[str, str] = {}
                for stock_code, ksic3, name in cur.fetchall():
                    code_map[stock_code] = ksic3
                    if name and ksic3 not in names:
                        names[ksic3] = name
                return code_map, names
        finally:
            conn.rollback()   # 실패한 트랜잭션을 풀에 돌려보내지 않는다
            self._put_connection(conn)

    def write_sector_news_result(self, trade_date, scores: List[Dict], hits: List[Dict]) -> Tuple[int, int]:
        """한 트랜잭션: news_sector_hit 그 날짜 DELETE+INSERT · sector_news_score UPSERT. (저장 섹터 수, 저장 hit 수)"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM news_sector_hit WHERE trade_date = %s", (trade_date,))
                if hits:
                    extras.execute_values(cur, """
                        INSERT INTO news_sector_hit
                            (trade_date, news_id, sector_key, route, routes, matched, w_match, contribution)
                        VALUES %s
                        ON CONFLICT (trade_date, news_id, sector_key) DO UPDATE SET
                            route = EXCLUDED.route, routes = EXCLUDED.routes, matched = EXCLUDED.matched,
                            w_match = EXCLUDED.w_match, contribution = EXCLUDED.contribution, computed_at = now()
                    """, [(h["trade_date"], h["news_id"], h["sector_key"], h["route"], h["routes"],
                           h["matched"], h["w_match"], h["contribution"]) for h in hits])
                if scores:
                    extras.execute_values(cur, """
                        INSERT INTO sector_news_score
                            (trade_date, taxonomy, sector_key, sector_name, window_start, window_end,
                             n_news, n_dir, n_kw, n_stock, n_pos, n_neg,
                             score_raw, score_norm, score_signed, top_news, dict_version, computed_at)
                        VALUES %s
                        ON CONFLICT (trade_date, taxonomy, sector_key) DO UPDATE SET
                            sector_name = EXCLUDED.sector_name,
                            window_start = EXCLUDED.window_start, window_end = EXCLUDED.window_end,
                            n_news = EXCLUDED.n_news, n_dir = EXCLUDED.n_dir, n_kw = EXCLUDED.n_kw,
                            n_stock = EXCLUDED.n_stock, n_pos = EXCLUDED.n_pos, n_neg = EXCLUDED.n_neg,
                            score_raw = EXCLUDED.score_raw, score_norm = EXCLUDED.score_norm,
                            score_signed = EXCLUDED.score_signed, top_news = EXCLUDED.top_news,
                            dict_version = EXCLUDED.dict_version, computed_at = now()
                    """, [(s["trade_date"], "ksic3", s["sector_key"], s.get("sector_name"),
                           s["window_start"], s["window_end"],
                           s["n_news"], s["n_dir"], s["n_kw"], s["n_stock"], s["n_pos"], s["n_neg"],
                           s["score_raw"], s["score_norm"], s["score_signed"],
                           json.dumps(s.get("top_news") or [], ensure_ascii=False), s.get("dict_version"))
                          for s in scores],
                        # computed_at = now() 는 서버 세션 타임존(Asia/Seoul)으로 기록된다.
                        template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, now())")
            conn.commit()
            return len(scores), len(hits)
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_connection(conn)

    @staticmethod
    def _jsonable(value):
        if isinstance(value, (datetime, )):
            return value.isoformat()
        if hasattr(value, "isoformat"):      # date
            return value.isoformat()
        try:
            from decimal import Decimal
            if isinstance(value, Decimal):
                return float(value)
        except ImportError:
            pass
        return value

    def get_sector_news_scores(self, trade_date) -> List[Dict]:
        """그 거래일의 섹터 점수(JSON 직렬화 가능한 dict). score_signed DESC, n_dir DESC."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT trade_date, taxonomy, sector_key, sector_name, window_start, window_end,
                           n_news, n_dir, n_kw, n_stock, n_pos, n_neg,
                           score_raw, score_norm, score_signed, top_news, dict_version, computed_at
                    FROM sector_news_score
                    WHERE trade_date = %s AND taxonomy = 'ksic3'
                    ORDER BY score_signed DESC, n_dir DESC, sector_key
                """, (trade_date,))
                cols = [d[0] for d in cur.description]
                return [{c: self._jsonable(v) for c, v in zip(cols, row)} for row in cur.fetchall()]
        finally:
            conn.rollback()
            self._put_connection(conn)

    # ------------------------------------------------------------------
    # 신호 원장 (signal ledger, 2026-09-11) — append-only 전향 기록
    # ------------------------------------------------------------------
    # 「어제 시스템이 뭐라고 했는지」를 남기는 표다. 후보뿐 아니라 뉴스가 붙은
    # 모든 종목의 집계값을 스냅샷마다 쌓는다 — 임계값을 바꿔 재평가하려면
    # 후보 밖의 종목도 필요하다. UPDATE/DELETE 경로는 «만들지 않는다».
    # 같은 (as_of, stock_code) 재실행은 ON CONFLICT DO NOTHING 으로 흘린다.
    SIGNAL_LEDGER_DDL = (
        """
        CREATE TABLE IF NOT EXISTS newsquant_signal_ledger (
            id                 bigserial PRIMARY KEY,
            as_of              timestamp NOT NULL,
            signal_date        date      NOT NULL,
            stock_code         text      NOT NULL,
            side               text,
            news_count         integer   NOT NULL,
            avg_sentiment      double precision,
            avg_overall        double precision,
            adjusted_sentiment double precision,
            volume_signal      double precision,
            composite_score    double precision,
            positive_count     integer,
            negative_count     integer,
            neutral_count      integer,
            positive_ratio     double precision,
            evidence_news_ids  jsonb,
            created_at         timestamp NOT NULL DEFAULT now(),
            UNIQUE (as_of, stock_code)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_nsl_date_code ON newsquant_signal_ledger (signal_date, stock_code)",
        "CREATE INDEX IF NOT EXISTS idx_nsl_as_of ON newsquant_signal_ledger (as_of)",
        "CREATE INDEX IF NOT EXISTS idx_nsl_side ON newsquant_signal_ledger (side) WHERE side IS NOT NULL",
    )

    SIGNAL_LEDGER_COLUMNS = (
        "as_of", "signal_date", "stock_code", "side", "news_count",
        "avg_sentiment", "avg_overall", "adjusted_sentiment", "volume_signal",
        "composite_score", "positive_count", "negative_count", "neutral_count",
        "positive_ratio", "evidence_news_ids",
    )

    def init_signal_ledger_table(self) -> None:
        """DDL(멱등). 표 이름에 newsquant_ 접두사를 붙여 소유를 분명히 한다
        (이 DB 는 RoboTrader 와 공유하며 candidate_stocks 등은 robotrader 소유다)."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for sql in self.SIGNAL_LEDGER_DDL:
                    cur.execute(sql)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_connection(conn)

    def insert_signal_ledger(self, rows: List[Dict]) -> int:
        """신호 원장 배치 적재 (append-only). 중복 (as_of, stock_code) 는 무시한다.

        Returns:
            실제로 적재된 행 수 (중복으로 흘린 행은 세지 않는다)
        """
        if not rows:
            return 0

        conn = self.get_connection()
        try:
            values = [
                (
                    r["as_of"], r["signal_date"], r["stock_code"], r.get("side"),
                    r.get("news_count", 0),
                    r.get("avg_sentiment"), r.get("avg_overall"),
                    r.get("adjusted_sentiment"), r.get("volume_signal"),
                    r.get("composite_score"),
                    r.get("positive_count"), r.get("negative_count"), r.get("neutral_count"),
                    r.get("positive_ratio"),
                    json.dumps(r.get("evidence_news_ids") or [], ensure_ascii=False),
                )
                for r in rows
            ]
            with conn.cursor() as cur:
                inserted = extras.execute_values(
                    cur,
                    f"""
                    INSERT INTO newsquant_signal_ledger
                        ({", ".join(self.SIGNAL_LEDGER_COLUMNS)})
                    VALUES %s
                    ON CONFLICT (as_of, stock_code) DO NOTHING
                    RETURNING id
                    """,
                    values,
                    template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                    page_size=500,
                    fetch=True,
                )
            conn.commit()
            return len(inserted)
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_connection(conn)

    def get_signal_ledger(self, signal_date=None, as_of=None,
                          stock_code: Optional[str] = None) -> List[Dict]:
        """원장 조회(읽기 전용). 인자를 준 조건만 걸린다. as_of, stock_code 순."""
        conn = self.get_connection()
        try:
            query = f"SELECT id, {', '.join(self.SIGNAL_LEDGER_COLUMNS)}, created_at FROM newsquant_signal_ledger WHERE TRUE"
            params: List = []
            if signal_date is not None:
                query += " AND signal_date = %s"
                params.append(signal_date)
            if as_of is not None:
                query += " AND as_of = %s"
                params.append(as_of)
            if stock_code is not None:
                query += " AND stock_code = %s"
                params.append(stock_code)
            query += " ORDER BY as_of, stock_code"
            with conn.cursor() as cur:
                cur.execute(query, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.rollback()
            self._put_connection(conn)
