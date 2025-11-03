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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
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
                - sentiment_score: 감성 점수
        
        Returns:
            삽입 성공 여부
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO news 
                (news_id, title, content, published_at, source, category, 
                 url, related_stocks, sentiment_score, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                news_data.get('news_id'),
                news_data.get('title'),
                news_data.get('content', ''),
                news_data.get('published_at'),
                news_data.get('source'),
                news_data.get('category', ''),
                news_data.get('url'),
                news_data.get('related_stocks', ''),
                news_data.get('sentiment_score'),
                datetime.now().isoformat()
            ))
            
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            logger.debug(f"중복 뉴스 건너뜀: {news_data.get('news_id')}")
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

