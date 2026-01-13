"""
데이터베이스 관리 모듈
SQLite를 사용하여 뉴스 데이터 저장 및 조회
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class NewsDatabase:
    """뉴스 데이터베이스 관리 클래스"""
    
    def __init__(self, db_path: str = "news_data.db"):
        """
        Args:
            db_path: 데이터베이스 파일 경로
        """
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self) -> sqlite3.Connection:
        """데이터베이스 연결 반환"""
        conn = sqlite3.connect(self.db_path)
        
        # WAL 모드 활성화 (동시 읽기/쓰기 가능)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")  # 성능 최적화
        
        # 인코딩 명시적 설정
        conn.execute("PRAGMA encoding='UTF-8'")
        
        conn.row_factory = sqlite3.Row  # 딕셔너리 형태로 결과 반환
        return conn
    
    def init_database(self):
        """데이터베이스 초기화 및 테이블 생성"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 뉴스 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                published_at TEXT NOT NULL,
                source TEXT NOT NULL,
                category TEXT,
                url TEXT NOT NULL,
                related_stocks TEXT,
                sentiment_score REAL,
                importance_score REAL,
                impact_score REAL,
                timeliness_score REAL,
                overall_score REAL,
                duplicate_count INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 기존 테이블에 새 컬럼 추가 (마이그레이션)
        try:
            cursor.execute("ALTER TABLE news ADD COLUMN importance_score REAL")
        except sqlite3.OperationalError:
            pass  # 컬럼이 이미 존재하는 경우
        
        try:
            cursor.execute("ALTER TABLE news ADD COLUMN impact_score REAL")
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute("ALTER TABLE news ADD COLUMN timeliness_score REAL")
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute("ALTER TABLE news ADD COLUMN overall_score REAL")
        except sqlite3.OperationalError:
            pass
        
        try:
            cursor.execute("ALTER TABLE news ADD COLUMN duplicate_count INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass
        
        # 인덱스 생성 (조회 성능 향상)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_id ON news(news_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_published_at ON news(published_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_source ON news(source)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_category ON news(category)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_overall_score ON news(overall_score)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sentiment_score ON news(sentiment_score)
        """)
        
        # 뉴스 수집 로그 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collection_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                collected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                news_count INTEGER DEFAULT 0,
                status TEXT,
                error_message TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"데이터베이스 초기화 완료: {self.db_path}")
    
    def insert_news(self, news_data: Dict) -> bool:
        """
        뉴스 데이터 삽입
        
        Args:
            news_data: 뉴스 데이터 딕셔너리
                - news_id: 고유 ID (필수)
                - title: 제목 (필수)
                - content: 본문
                - published_at: 발행일시 (필수)
                - source: 출처 (필수)
                - category: 카테고리
                - url: URL (필수)
                - related_stocks: 관련 종목 코드 (콤마 구분)
                - sentiment_score: 감성 점수 (-1.0 ~ +1.0)
                - importance_score: 중요도 점수 (0.0 ~ 1.0)
                - impact_score: 영향도 점수 (0.0 ~ 1.0)
                - timeliness_score: 실시간성 점수 (0.0 ~ 1.0)
                - overall_score: 종합 점수
        
        Returns:
            삽입 성공 여부
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # 문자열 데이터 정리 및 인코딩 보장
            def ensure_utf8(text):
                """문자열이 올바른 UTF-8인지 확인하고 정리"""
                if not text:
                    return text
                
                if isinstance(text, bytes):
                    # 바이트인 경우 다양한 인코딩으로 디코딩 시도
                    for encoding in ['utf-8', 'euc-kr', 'cp949', 'latin1']:
                        try:
                            return text.decode(encoding, errors='strict')
                        except (UnicodeDecodeError, UnicodeError):
                            continue
                    return text.decode('utf-8', errors='replace')
                
                # 이미 문자열인 경우, 인코딩이 깨졌는지 확인 (latin1로 잘못 디코딩된 경우 등)
                try:
                    # latin1로 인코딩했을 때 다시 복구 가능한지 확인 (일반적인 인코딩 깨짐 현상 복구)
                    if any(ord(c) > 0x7F and ord(c) < 0x100 for c in text):
                        # 깨진 문자열 패턴이 보이면 재인코딩/디코딩 시도
                        for encoding in ['euc-kr', 'cp949']:
                            try:
                                recovered = text.encode('latin1').decode(encoding)
                                if any('\uac00' <= char <= '\ud7a3' for char in recovered):
                                    return recovered
                            except:
                                continue
                except:
                    pass
                
                # replacement character (\ufffd) 처리: 제거하지 않고 유지하거나 공백으로 대체
                # 기존 코드는 무조건 제거했으나, 이는 정보 손실을 초래할 수 있음
                if '\ufffd' in text:
                    # 로깅만 하고 일단 유지
                    logger.debug(f"데이터에 깨진 문자(Replacement Character) 포함됨: {text[:50]}")
                
                return text
            
            title = ensure_utf8(news_data.get('title'))
            content = ensure_utf8(news_data.get('content', ''))
            category = ensure_utf8(news_data.get('category', ''))
            related_stocks = ensure_utf8(news_data.get('related_stocks', ''))
            
            # 먼저 기존 뉴스가 있는지 확인
            news_id = news_data.get('news_id')
            cursor.execute("SELECT id, duplicate_count FROM news WHERE news_id = ?", (news_id,))
            existing = cursor.fetchone()
            
            if existing:
                # 중복 뉴스인 경우 - duplicate_count 증가
                new_count = existing[1] + 1
                cursor.execute("""
                    UPDATE news 
                    SET duplicate_count = ?,
                        updated_at = ?
                    WHERE news_id = ?
                """, (new_count, datetime.now().isoformat(), news_id))
                logger.debug(f"중복 뉴스 카운트 증가: {news_id} (count: {new_count})")
            else:
                # 새로운 뉴스인 경우 - INSERT
                cursor.execute("""
                    INSERT INTO news 
                    (news_id, title, content, published_at, source, category, 
                     url, related_stocks, sentiment_score, importance_score, 
                     impact_score, timeliness_score, overall_score, duplicate_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    news_id,
                    title,
                    content,
                    news_data.get('published_at'),
                    news_data.get('source'),
                    category,
                    news_data.get('url'),
                    related_stocks,
                    news_data.get('sentiment_score'),
                    news_data.get('importance_score'),
                    news_data.get('impact_score'),
                    news_data.get('timeliness_score'),
                    news_data.get('overall_score'),
                    1,  # duplicate_count 초기값
                    datetime.now().isoformat()
                ))
            
            conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            logger.debug(f"중복 뉴스 오류: {news_data.get('news_id')} - {e}")
            return False
        except Exception as e:
            logger.error(f"뉴스 삽입 오류: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def insert_news_batch(self, news_list: List[Dict]) -> int:
        """
        여러 뉴스 데이터 일괄 삽입
        
        Args:
            news_list: 뉴스 데이터 리스트
        
        Returns:
            성공적으로 삽입된 뉴스 개수
        """
        success_count = 0
        for news_data in news_list:
            if self.insert_news(news_data):
                success_count += 1
        return success_count
    
    def get_news_by_date_range(self, start_date: str, end_date: str, 
                                source: Optional[str] = None) -> List[Dict]:
        """
        날짜 범위로 뉴스 조회
        
        Args:
            start_date: 시작일시 (ISO 형식)
            end_date: 종료일시 (ISO 형식)
            source: 출처 필터 (선택)
        
        Returns:
            뉴스 데이터 리스트
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if source:
            cursor.execute("""
                SELECT * FROM news 
                WHERE published_at >= ? AND published_at <= ? AND source = ?
                ORDER BY published_at DESC
            """, (start_date, end_date, source))
        else:
            cursor.execute("""
                SELECT * FROM news 
                WHERE published_at >= ? AND published_at <= ?
                ORDER BY published_at DESC
            """, (start_date, end_date))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_latest_news(self, limit: int = 100, source: Optional[str] = None) -> List[Dict]:
        """
        최신 뉴스 조회
        
        Args:
            limit: 조회 개수
            source: 출처 필터 (선택)
        
        Returns:
            뉴스 데이터 리스트
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if source:
            cursor.execute("""
                SELECT * FROM news 
                WHERE source = ?
                ORDER BY published_at DESC
                LIMIT ?
            """, (source, limit))
        else:
            cursor.execute("""
                SELECT * FROM news 
                ORDER BY published_at DESC
                LIMIT ?
            """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def log_collection(self, source: str, news_count: int, 
                      status: str = "success", error_message: Optional[str] = None):
        """
        수집 로그 기록
        
        Args:
            source: 출처
            news_count: 수집된 뉴스 개수
            status: 상태 (success, error)
            error_message: 오류 메시지
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO collection_log (source, collected_at, news_count, status, error_message)
            VALUES (?, ?, ?, ?, ?)
        """, (source, datetime.now().isoformat(), news_count, status, error_message))
        
        conn.commit()
        conn.close()
    
    def get_collection_stats(self, days: int = 7) -> Dict:
        """
        최근 N일간 수집 통계 조회
        
        Args:
            days: 조회할 일수
        
        Returns:
            통계 딕셔너리
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
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
            WHERE datetime(collected_at) >= datetime('now', '-' || ? || ' days')
            GROUP BY source
        """, (days,))
        
        recent_stats = {row[0]: {'total': row[1], 'attempts': row[2]} 
                       for row in cursor.fetchall()}
        
        conn.close()
        
        return {
            'total_news': total_news,
            'by_source': source_counts,
            'recent_collection': recent_stats
        }
    
    def get_news_by_stock(self, stock_code: str, limit: int = 50) -> List[Dict]:
        """
        특정 종목 관련 뉴스 조회
        
        Args:
            stock_code: 종목 코드 (6자리, 예: "005930")
            limit: 조회 개수
        
        Returns:
            뉴스 데이터 리스트
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 종목 코드로 검색 (related_stocks 필드에 포함된 경우)
        cursor.execute("""
            SELECT * FROM news
            WHERE related_stocks LIKE ?
            ORDER BY published_at DESC
            LIMIT ?
        """, (f'%{stock_code}%', limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_news_by_stocks(self, stock_codes: List[str], limit_per_stock: int = 10) -> Dict[str, List[Dict]]:
        """
        여러 종목의 뉴스를 한 번에 조회
        
        Args:
            stock_codes: 종목 코드 리스트 (6자리, 예: ["005930", "000660"])
            limit_per_stock: 종목당 조회 개수
        
        Returns:
            {종목코드: 뉴스리스트} 형태의 딕셔너리
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        result = {}
        
        # 각 종목별로 조회
        for stock_code in stock_codes:
            cursor.execute("""
                SELECT * FROM news
                WHERE related_stocks LIKE ?
                ORDER BY published_at DESC
                LIMIT ?
            """, (f'%{stock_code}%', limit_per_stock))
            
            rows = cursor.fetchall()
            result[stock_code] = [dict(row) for row in rows]
        
        conn.close()
        return result
    
    def search_news(self, keyword: Optional[str] = None,
                   min_sentiment: Optional[float] = None,
                   max_sentiment: Optional[float] = None,
                   min_overall_score: Optional[float] = None,
                   source: Optional[str] = None,
                   limit: int = 100) -> List[Dict]:
        """
        뉴스 검색 (고급 필터링)
        
        Args:
            keyword: 키워드 검색 (제목, 본문)
            min_sentiment: 최소 감성 점수
            max_sentiment: 최대 감성 점수
            min_overall_score: 최소 종합 점수
            source: 출처 필터
            limit: 조회 개수
        
        Returns:
            뉴스 데이터 리스트
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 기본 쿼리
        query = "SELECT * FROM news WHERE 1=1"
        params = []
        
        # 키워드 검색
        if keyword:
            query += " AND (title LIKE ? OR content LIKE ?)"
            params.extend([f'%{keyword}%', f'%{keyword}%'])
        
        # 감성 점수 필터
        if min_sentiment is not None:
            query += " AND sentiment_score >= ?"
            params.append(min_sentiment)
        
        if max_sentiment is not None:
            query += " AND sentiment_score <= ?"
            params.append(max_sentiment)
        
        # 종합 점수 필터
        if min_overall_score is not None:
            query += " AND overall_score >= ?"
            params.append(min_overall_score)
        
        # 출처 필터
        if source:
            query += " AND source = ?"
            params.append(source)
        
        # 정렬 및 제한
        query += " ORDER BY published_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]

