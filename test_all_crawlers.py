import logging
import sys
from news_scraper.crawlers.naver_finance_crawler import NaverFinanceCrawler
from news_scraper.crawlers.dart_crawler import DARTCrawler
from news_scraper.crawlers.hankyung_crawler import HankyungCrawler
from news_scraper.crawlers.mk_crawler import MKNewsCrawler
from news_scraper.database import NewsDatabase
from news_scraper.sentiment_analyzer import SentimentAnalyzer

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_crawlers():
    db = NewsDatabase()
    analyzer = SentimentAnalyzer()
    
    crawlers = [
        NaverFinanceCrawler(),
        DARTCrawler(),
        HankyungCrawler(),
        MKNewsCrawler()
    ]
    
    for crawler in crawlers:
        try:
            print(f"\n--- Testing {crawler.source_name} ---")
            news_list = crawler.crawl_news_list(max_pages=1)
            print(f"Collected {len(news_list)} news from {crawler.source_name}")
            
            if news_list:
                # Test first 3 items for analysis and DB insertion
                test_items = news_list[:3]
                for news in test_items:
                    analyzed = analyzer.analyze_news(news)
                    db.insert_news(analyzed)
                    print(f"  [OK] {news['title'][:50]}...")
            
        except Exception as e:
            print(f"  [ERROR] {crawler.source_name}: {e}")

if __name__ == "__main__":
    test_crawlers()

