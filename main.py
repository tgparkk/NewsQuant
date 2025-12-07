"""
뉴스 수집 시스템 메인 실행 파일
"""

import logging
import sys
from pathlib import Path
from threading import Thread

from news_scraper.scheduler import NewsScheduler
from news_scraper.database import NewsDatabase

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('news_scraper.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def show_statistics():
    """수집 통계 출력"""
    try:
        db = NewsDatabase()
        stats = db.get_collection_stats(days=7)
        
        print("\n" + "=" * 50)
        print("뉴스 수집 통계 (최근 7일)")
        print("=" * 50)
        print(f"전체 뉴스 개수: {stats['total_news']:,}개")
        print("\n출처별 뉴스 개수:")
        for source, count in stats['by_source'].items():
            print(f"  - {source}: {count:,}개")
        
        print("\n최근 수집 현황:")
        for source, info in stats['recent_collection'].items():
            print(f"  - {source}: {info['total']:,}개 (시도: {info['attempts']}회)")
        print("=" * 50 + "\n")
        
    except Exception as e:
        logger.error(f"통계 조회 오류: {e}")


def main():
    """메인 함수"""
    print("=" * 60)
    print("주식 뉴스 수집 시스템 v1.0")
    print("=" * 60)
    print("\n지원하는 뉴스 소스:")
    print("  - 네이버 금융")
    print("  - 한국거래소 공시")
    print("  - 연합인포맥스")
    print("  - 한국경제")
    print("  - 매일경제")
    print("\n수집 주기:")
    print("  - 시장 운영 시간 (월~금 09:00~15:30): 1분마다")
    print("  - 시장 마감 후 (월~금 15:30~24:00): 5분마다")
    print("  - 주말/새벽: 30분마다")
    print("\nAPI 서버:")
    print("  - REST API 제공: http://127.0.0.1:8000")
    print("  - API 문서: http://127.0.0.1:8000/docs")
    print("\n" + "=" * 60 + "\n")
    
    try:
        # 데이터베이스 초기화
        db = NewsDatabase()
        logger.info("데이터베이스 연결 완료")
        
        # 통계 출력
        show_statistics()
        
        # API 서버 시작 (별도 스레드)
        from news_scraper.api.server import start_api_server
        api_thread = Thread(
            target=start_api_server,
            args=("127.0.0.1", 8000),
            daemon=True  # 메인 프로세스 종료 시 함께 종료
        )
        api_thread.start()
        logger.info("=" * 60)
        logger.info("NewsQuant API 서버 시작")
        logger.info(f"  - API 서버: http://127.0.0.1:8000")
        logger.info(f"  - API 문서: http://127.0.0.1:8000/docs")
        logger.info(f"  - ReDoc 문서: http://127.0.0.1:8000/redoc")
        logger.info("=" * 60)
        
        # 스케줄러 시작 (메인 스레드, 블로킹)
        scheduler = NewsScheduler()
        logger.info("뉴스 수집 스케줄러를 시작합니다...")
        scheduler.start()
        
    except Exception as e:
        logger.error(f"프로그램 실행 오류: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

