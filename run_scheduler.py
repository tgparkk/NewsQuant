import logging
import sys
from news_scraper.scheduler import NewsScheduler

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

if __name__ == "__main__":
    logger.info("뉴스 수집 스케줄러 단독 실행 시작")
    print("뉴스 수집 스케줄러가 시작되었습니다. (로그는 news_scraper.log 파일에 저장됩니다)")
    scheduler = NewsScheduler()
    scheduler.start()
