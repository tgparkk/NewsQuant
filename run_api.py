import logging
import sys
from news_scraper.api.server import start_api_server

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
    logger.info("API 서버 단독 실행 시작")
    print("API 서버가 시작되었습니다. http://127.0.0.1:8000 (로그는 news_scraper.log 파일에 저장됩니다)")
    start_api_server('127.0.0.1', 8000)
