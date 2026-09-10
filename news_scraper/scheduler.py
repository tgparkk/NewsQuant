"""
뉴스 수집 스케줄러
시장 운영 시간을 고려한 주기별 뉴스 수집
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, time as dt_time, timedelta
from typing import List, Optional, Tuple
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from .database import NewsDatabase
from .sentiment_analyzer import SentimentAnalyzer
from .english_sentiment_analyzer import EnglishSentimentAnalyzer
from .crawlers.naver_finance_crawler import NaverFinanceCrawler
from .crawlers.dart_crawler import DARTCrawler
# from .crawlers.krx_crawler import KRXCrawler  # 비활성화: 접근 불가
# from .crawlers.yonhap_crawler import YonhapCrawler  # 비활성화: 접근 불가
from .crawlers.hankyung_crawler import HankyungCrawler
from .crawlers.mk_crawler import MKNewsCrawler
from .crawlers.global_news_crawler import GlobalNewsCrawler

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
        self.english_sentiment_analyzer = EnglishSentimentAnalyzer()

        # 크롤러 리스트 (국내 + 글로벌)
        self.crawlers = [
            NaverFinanceCrawler(),
            DARTCrawler(),
            # KRXCrawler(),  # 비활성화: 접근 불가 (404 오류)
            # YonhapCrawler(),  # 비활성화: 접근 불가 (400 오류)
            HankyungCrawler(),
            MKNewsCrawler(),
            GlobalNewsCrawler(),  # 글로벌 뉴스 RSS 크롤러
        ]

        # 글로벌 뉴스 출처 (영문 감성 분석기 사용)
        self.global_sources = {
            'global_news', 'cnbc', 'marketwatch', 'investing_com',
            'google_news_finance', 'google_news_asia',
            'google_news_trade', 'google_news_tech',
        }
        
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
    
    # 병렬 크롤링 설정
    MAX_WORKERS = 4           # 최대 동시 크롤러 수
    CRAWLER_TIMEOUT = 300     # 크롤러당 타임아웃 (5분, 초 단위)
    
    def _run_single_crawler(self, crawler) -> Tuple[str, List, Optional[str]]:
        """
        단일 크롤러 실행 (ThreadPoolExecutor에서 호출)
        
        Returns:
            (source_name, news_list, error_message) 튜플
        """
        logger.info(f"[{crawler.source_name}] 크롤링 시작...")
        # 사이클 경계를 연다: 통계 초기화, 시간 예산 시계 시작, 회로 재설정.
        # 구형 크롤러(RSS 기반 등)는 이 훅이 없을 수 있으므로 있을 때만 부른다.
        if hasattr(crawler, 'begin_cycle'):
            crawler.begin_cycle()

        try:
            news_list = crawler.crawl_news_list(max_pages=3)
            return (crawler.source_name, news_list or [], None)
        except Exception as e:
            logger.error(f"[{crawler.source_name}] 크롤링 오류: {e}", exc_info=True)
            return (crawler.source_name, [], str(e))
        finally:
            # 터진 사이클이야말로 «무슨 일이 있었는지»가 필요하다.
            # 143만 줄을 grep 하지 않고 어디가 아픈지 보기 위한 한 줄.
            summary = crawler.cycle_summary() if hasattr(crawler, 'cycle_summary') else ""
            if summary:
                logger.info(summary)
    
    def _handle_crawler_result(self, source_name: str, news_list: List,
                               error_msg: Optional[str], recovered: bool = False) -> int:
        """크롤러 결과 1건을 처리한다: 감성분석 -> insert_news_batch -> log_collection.

        🔑 이 메서드는 한 번 호출될 때마다 log_collection 을 «정확히 한 줄» 남긴다.
           (성공/무수확/오류 어느 분기로 가든 정확히 1회, 예외로 빠져나가지 않는다)
           호출자는 future 하나당 이 메서드를 최대 1회만 부르면
           「사이클당 소스당 한 줄」이 보장된다.

        Args:
            source_name: 크롤러 출처명
            news_list:   수확물
            error_msg:   크롤러 내부 오류 메시지 (없으면 None)
            recovered:   전체 타임아웃 «후» 회수된 수확물인지 여부.
                         True 면 로그/collection_log 에 「타임아웃 후 회수」로 표시한다.

        Returns:
            저장된 뉴스 건수
        """
        prefix = "[타임아웃 후 회수] " if recovered else ""

        def _note(msg: Optional[str] = None) -> Optional[str]:
            """회수분임을 collection_log 에 남기기 위한 error_message 조립"""
            if not recovered:
                return msg
            return f"타임아웃 후 회수: {msg}" if msg else "타임아웃 후 회수"

        if error_msg:
            logger.error(f"{prefix}[{source_name}] 크롤링 오류: {error_msg}")
            self.db.log_collection(
                source=source_name,
                news_count=0,
                status="error",
                error_message=_note(error_msg)
            )
            return 0

        if not news_list:
            logger.warning(f"{prefix}[{source_name}] 수집된 뉴스가 없습니다.")
            self.db.log_collection(
                source=source_name,
                news_count=0,
                status="success",
                error_message=_note("수집된 뉴스 없음")
            )
            return 0

        try:
            # 감성 분석 및 점수 계산
            # 글로벌 뉴스는 영문 분석기, 국내 뉴스는 한글 분석기 사용
            is_global = source_name in self.global_sources
            analyzer = self.english_sentiment_analyzer if is_global else self.sentiment_analyzer

            analyzed_news_list = []
            for news in news_list:
                try:
                    if not news.get('title'):
                        news['title'] = ''
                    if not news.get('content'):
                        news['content'] = ''
                    analyzed_news = analyzer.analyze_news(news)
                    analyzed_news_list.append(analyzed_news)
                except Exception as e:
                    logger.warning(f"[{source_name}] 감성 분석 오류: {e}")
                    news['sentiment_score'] = 0.0
                    news['importance_score'] = 0.0
                    news['impact_score'] = 0.0
                    news['timeliness_score'] = 0.5
                    news['overall_score'] = 0.0
                    analyzed_news_list.append(news)

            # 데이터베이스에 저장
            inserted_count = self.db.insert_news_batch(analyzed_news_list)
        except Exception as e:
            logger.error(f"{prefix}[{source_name}] 저장 처리 오류: {e}", exc_info=True)
            self.db.log_collection(
                source=source_name,
                news_count=0,
                status="error",
                error_message=_note(f"저장 처리 오류: {e}")
            )
            return 0

        self.db.log_collection(
            source=source_name,
            news_count=inserted_count,
            status="success",
            error_message=_note()
        )
        logger.info(f"{prefix}[{source_name}] {inserted_count}개 뉴스 수집 완료")
        return inserted_count

    def _recover_pending_results(self, future_to_crawler: dict, logged_futures: set) -> int:
        """전체 타임아웃 «후», executor shutdown(wait=True) 이 끝난 뒤 호출한다.

        as_completed 전체 타임아웃은 for 루프를 통째로 이탈시키므로,
        그 뒤에 완료된 크롤러의 result() 를 «아무도 읽지 않는다».
        future.cancel() 은 이미 실행 중인 future 에 효과가 없어 크롤러는 끝까지 돌고,
        with 블록이 닫히며 shutdown(wait=True) 가 그 완주를 기다린다.
        => 그 시점엔 수확물이 «메모리에 이미 들어와 있다». 여기서 회수해 정상 경로로 저장한다.

        타임아웃이 없었다면 미처리 future 가 없으므로 no-op 이다.

        Returns:
            회수하여 저장한 뉴스 건수
        """
        pending = [(f, c) for f, c in future_to_crawler.items() if f not in logged_futures]
        if not pending:
            return 0

        logger.warning(f"타임아웃 후 수확물 회수 시도: {len(pending)}개 크롤러 "
                       f"({', '.join(c.source_name for _, c in pending)})")

        recovered_total = 0
        for future, crawler in pending:
            source_name = crawler.source_name
            try:
                if future.cancelled():
                    # 워커를 못 잡아 «시작도 못 한» 크롤러 - 수확물이 존재하지 않는다.
                    logger.error(f"[{source_name}] 전체 타임아웃 - 미실행 취소 (수확물 없음)")
                    self.db.log_collection(
                        source=source_name,
                        news_count=0,
                        status="error",
                        error_message=f"전체 타임아웃 ({self.CRAWLER_TIMEOUT + 30}초) - 미실행 취소"
                    )
                elif not future.done():
                    # shutdown(wait=True) 이후엔 도달하지 않아야 한다 (방어적 분기).
                    logger.error(f"[{source_name}] shutdown 후에도 미완료 - 수확물 회수 불가")
                    self.db.log_collection(
                        source=source_name,
                        news_count=0,
                        status="error",
                        error_message=f"전체 타임아웃 ({self.CRAWLER_TIMEOUT + 30}초) - 회수 실패(미완료)"
                    )
                else:
                    src, news_list, error_msg = future.result(timeout=0)
                    recovered_total += self._handle_crawler_result(
                        src, news_list, error_msg, recovered=True
                    )
            except Exception as e:
                logger.error(f"[{source_name}] 타임아웃 후 회수 처리 오류: {e}", exc_info=True)
                self.db.log_collection(
                    source=source_name,
                    news_count=0,
                    status="error",
                    error_message=f"타임아웃 후 회수 실패: {e}"
                )
            finally:
                logged_futures.add(future)

        logger.warning(f"타임아웃 후 회수 완료: {recovered_total}개 뉴스 저장")
        return recovered_total

    def collect_all_news(self):
        """모든 크롤러로 뉴스 병렬 수집"""
        logger.info("=" * 50)
        logger.info(f"뉴스 수집 시작 (병렬, max_workers={self.MAX_WORKERS}): "
                     f"{datetime.now(pytz.timezone('Asia/Seoul'))}")

        total_news_count = 0
        future_to_crawler = {}
        # 이 사이클에서 log_collection 을 «이미 한 줄» 남긴 future 집합.
        # 크롤러(=소스)당 future 는 정확히 하나이므로, 이 집합이
        # 「사이클당 소스당 collection_log 한 줄」을 보장하는 장치다.
        logged_futures = set()

        # 크롤러들을 병렬로 실행
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_crawler = {
                executor.submit(self._run_single_crawler, crawler): crawler
                for crawler in self.crawlers
            }

            try:
                for future in as_completed(future_to_crawler, timeout=self.CRAWLER_TIMEOUT + 30):
                    crawler = future_to_crawler[future]
                    try:
                        source_name, news_list, error_msg = future.result(timeout=self.CRAWLER_TIMEOUT)
                    except TimeoutError:
                        source_name = crawler.source_name
                        logger.error(f"[{source_name}] 크롤링 타임아웃 ({self.CRAWLER_TIMEOUT}초)")
                        self.db.log_collection(
                            source=source_name,
                            news_count=0,
                            status="error",
                            error_message=f"타임아웃 ({self.CRAWLER_TIMEOUT}초)"
                        )
                    except Exception as e:
                        source_name = crawler.source_name
                        logger.error(f"[{source_name}] 크롤링 처리 오류: {e}", exc_info=True)
                        self.db.log_collection(
                            source=source_name,
                            news_count=0,
                            status="error",
                            error_message=str(e)
                        )
                    else:
                        total_news_count += self._handle_crawler_result(
                            source_name, news_list, error_msg
                        )
                    finally:
                        logged_futures.add(future)
            except TimeoutError:
                # as_completed 전체 타임아웃 - for 루프를 통째로 이탈한다.
                # 🔴 여기서 미완료 future 를 error 로 «확정하지 않는다».
                #    실행 중인 크롤러는 cancel() 이 안 먹고 끝까지 완주하므로,
                #    shutdown(wait=True) 이 끝난 뒤 _recover_pending_results() 에서
                #    수확물을 회수하고 그때 한 줄만 기록한다.
                logger.warning(f"병렬 크롤링 전체 타임아웃 ({self.CRAWLER_TIMEOUT + 30}초) - 미완료 크롤러 확인 중")
                for future, crawler in future_to_crawler.items():
                    if future in logged_futures:
                        continue
                    # cancel() 은 «아직 시작 안 한» future 에만 성공한다.
                    # 실행 중이면 False 를 반환하고 크롤러는 계속 돈다.
                    if future.cancel():
                        logger.error(f"[{crawler.source_name}] 전체 타임아웃 - 미실행 취소")
                    else:
                        logger.warning(f"[{crawler.source_name}] 전체 타임아웃 시점에 실행 중 "
                                       f"- shutdown 후 수확물 회수를 시도한다")
        # ← with 종료 = shutdown(wait=True). 실행 중이던 크롤러가 여기서 완주한다.

        # 타임아웃으로 버려질 뻔한 수확물을 회수한다 (타임아웃이 없었으면 no-op).
        total_news_count += self._recover_pending_results(future_to_crawler, logged_futures)

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

        # 스펙 B: 섹터 뉴스 점수 집계 (10분) — sector_news_score UPSERT. 봇이 09:00 에 읽는다.
        self.scheduler.add_job(
            func=self.run_sector_news_aggregation,
            trigger=IntervalTrigger(minutes=10),
            id='sector_news_aggregation',
            max_instances=1,
            misfire_grace_time=300
        )
        logger.info("- 섹터 뉴스 집계: 10분마다 (평일 09:05~15:30 동결)")

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

            # 첫 수집 직후 섹터 점수 1회 (07:40 기동 → 09:00 전에 8회 더 돈다)
            try:
                self.run_sector_news_aggregation()
            except Exception as e:
                logger.error(f"[섹터뉴스] 기동 시 1회 집계 실패(수집은 계속): {e}", exc_info=True)

            logger.info("스케줄러가 실행 중입니다. Ctrl+C로 종료할 수 있습니다.")
            self.scheduler.start()
            
        except KeyboardInterrupt:
            logger.info("스케줄러가 사용자에 의해 중지되었습니다.")
            self.scheduler.shutdown()
        except Exception as e:
            logger.error(f"스케줄러 오류: {e}", exc_info=True)
            self.scheduler.shutdown()
    
    def run_sector_news_aggregation(self):
        """섹터 뉴스 점수 집계 1회 (스펙 B). 예외는 잡 안에서 처리된다."""
        from .sector_news_job import run_sector_news_job
        return run_sector_news_job(self.db)

    def stop(self):
        """스케줄러 중지"""
        logger.info("스케줄러를 중지합니다...")
        self.scheduler.shutdown()

