"""
뉴스 수집 스케줄러
시장 운영 시간을 고려한 주기별 뉴스 수집
"""

import logging
from datetime import datetime, time as dt_time, timedelta
from typing import List
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from .database import NewsDatabase
from .sentiment_analyzer import SentimentAnalyzer
from .crawlers.naver_finance_crawler import NaverFinanceCrawler
from .crawlers.krx_crawler import KRXCrawler
from .crawlers.yonhap_crawler import YonhapCrawler
from .crawlers.hankyung_crawler import HankyungCrawler
from .crawlers.mk_crawler import MKNewsCrawler

logger = logging.getLogger(__name__)


class NewsScheduler:
    """뉴스 수집 스케줄러"""
    
    def __init__(self, db_path: str = "news_data.db"):
        """
        Args:
            db_path: 데이터베이스 파일 경로
        """
        self.db = NewsDatabase(db_path)
        self.scheduler = BlockingScheduler(timezone=pytz.timezone('Asia/Seoul'))
        self.sentiment_analyzer = SentimentAnalyzer()
        
        # 크롤러 리스트
        self.crawlers = [
            NaverFinanceCrawler(),
            KRXCrawler(),
            YonhapCrawler(),
            HankyungCrawler(),
            MKNewsCrawler()
        ]
        
        # 마지막 수집 시간 추적
        self.last_collection_time = None
        self.collection_interval = 1  # 기본 1분
    
    def is_market_open(self) -> bool:
        """
        현재 시장이 열려있는지 확인
        
        Returns:
            시장 운영 시간 여부 (월~금 9:00~15:30)
        """
        now = datetime.now(pytz.timezone('Asia/Seoul'))
        
        # 주말 체크
        if now.weekday() >= 5:  # 토요일(5), 일요일(6)
            return False
        
        # 공휴일 체크 (추후 보강 필요)
        # 현재는 주말만 체크
        
        # 시간 체크: 09:00 ~ 15:30
        current_time = now.time()
        market_open = dt_time(9, 0)
        market_close = dt_time(15, 30)
        
        return market_open <= current_time <= market_close
    
    def collect_all_news(self):
        """모든 크롤러로 뉴스 수집"""
        logger.info("=" * 50)
        logger.info(f"뉴스 수집 시작: {datetime.now(pytz.timezone('Asia/Seoul'))}")
        
        total_news_count = 0
        
        for crawler in self.crawlers:
            try:
                logger.info(f"[{crawler.source_name}] 크롤링 시작...")
                
                # 뉴스 목록 크롤링
                news_list = crawler.crawl_news_list(max_pages=3)  # 각 크롤러당 최대 3페이지
                
                if news_list:
                    # 감성 분석 및 점수 계산
                    analyzed_news_list = []
                    for news in news_list:
                        try:
                            analyzed_news = self.sentiment_analyzer.analyze_news(news)
                            analyzed_news_list.append(analyzed_news)
                        except Exception as e:
                            logger.warning(f"[{crawler.source_name}] 감성 분석 오류: {e}")
                            # 분석 실패해도 뉴스는 저장
                            analyzed_news_list.append(news)
                    
                    # 데이터베이스에 저장
                    inserted_count = self.db.insert_news_batch(analyzed_news_list)
                    total_news_count += inserted_count
                    
                    # 수집 로그 기록
                    self.db.log_collection(
                        source=crawler.source_name,
                        news_count=inserted_count,
                        status="success"
                    )
                    
                    logger.info(f"[{crawler.source_name}] {inserted_count}개 뉴스 수집 완료")
                else:
                    logger.warning(f"[{crawler.source_name}] 수집된 뉴스가 없습니다.")
                    self.db.log_collection(
                        source=crawler.source_name,
                        news_count=0,
                        status="success",
                        error_message="수집된 뉴스 없음"
                    )
                    
            except Exception as e:
                logger.error(f"[{crawler.source_name}] 크롤링 오류: {e}", exc_info=True)
                self.db.log_collection(
                    source=crawler.source_name,
                    news_count=0,
                    status="error",
                    error_message=str(e)
                )
        
        logger.info(f"전체 뉴스 수집 완료: 총 {total_news_count}개")
        logger.info("=" * 50)
    
    def get_collection_interval(self) -> int:
        """
        현재 시간에 맞는 수집 주기 반환 (분 단위)
        
        Returns:
            수집 주기 (분)
        """
        if self.is_market_open():
            return 1  # 시장 운영 시간: 1분마다
        else:
            now = datetime.now(pytz.timezone('Asia/Seoul'))
            # 주말인 경우
            if now.weekday() >= 5:
                return 30  # 주말: 30분마다
            # 평일 밤 또는 새벽
            elif now.hour < 9 or now.hour >= 15:
                return 5  # 마감 후: 5분마다
            else:
                return 5
    
    def collect_with_smart_interval(self):
        """스마트 간격으로 수집 (내부에서 주기 결정)"""
        now = datetime.now(pytz.timezone('Asia/Seoul'))
        
        # 주기 계산
        new_interval = self.get_collection_interval()
        
        # 주기가 변경되었거나 첫 실행이면 수집
        should_collect = False
        if self.last_collection_time is None:
            should_collect = True
        elif (now - self.last_collection_time).total_seconds() >= (new_interval * 60):
            should_collect = True
        
        # 주기 변경 시 로그
        if new_interval != self.collection_interval:
            logger.info(f"수집 주기 변경: {self.collection_interval}분 -> {new_interval}분")
            self.collection_interval = new_interval
        
        # 수집 실행
        if should_collect:
            self.collect_all_news()
            self.last_collection_time = now
            logger.info(f"다음 수집 예정: {new_interval}분 후")
    
    def setup_schedule(self):
        """스케줄 설정"""
        # 매분마다 체크하되, 실제 수집은 주기에 따라 결정
        self.scheduler.add_job(
            func=self.collect_with_smart_interval,
            trigger=IntervalTrigger(minutes=1),  # 매분 체크
            id='smart_collection',
            max_instances=1,
            misfire_grace_time=120
        )
        
        logger.info("스케줄 설정 완료")
        logger.info("- 시장 운영 시간 (월~금 09:00~15:30): 1분마다")
        logger.info("- 시장 마감 후 (월~금 15:30~24:00, 00:00~09:00): 5분마다")
        logger.info("- 주말: 30분마다")
    
    def start(self):
        """스케줄러 시작"""
        try:
            logger.info("뉴스 수집 스케줄러를 시작합니다...")
            self.setup_schedule()
            
            # 시작 시 즉시 한 번 수집
            self.collect_all_news()
            
            logger.info("스케줄러가 실행 중입니다. Ctrl+C로 종료할 수 있습니다.")
            self.scheduler.start()
            
        except KeyboardInterrupt:
            logger.info("스케줄러가 사용자에 의해 중지되었습니다.")
            self.scheduler.shutdown()
        except Exception as e:
            logger.error(f"스케줄러 오류: {e}", exc_info=True)
            self.scheduler.shutdown()
    
    def stop(self):
        """스케줄러 중지"""
        logger.info("스케줄러를 중지합니다...")
        self.scheduler.shutdown()

