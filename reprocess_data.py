"""
기존 데이터 재처리 스크립트
- 내용이 없는 뉴스에 대해 상세 내용 크롤링
- 감성 분석이 안 된 뉴스에 대해 감성 분석 수행
- 종목 코드가 없는 뉴스에 대해 종목 코드 재추출
"""

import logging
from datetime import datetime
from news_scraper.database import NewsDatabase
from news_scraper.sentiment_analyzer import SentimentAnalyzer
from news_scraper.crawlers.hankyung_crawler import HankyungCrawler
from news_scraper.crawlers.mk_crawler import MKNewsCrawler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def reprocess_data():
    """기존 데이터 재처리"""
    db = NewsDatabase()
    sentiment_analyzer = SentimentAnalyzer()
    
    # 크롤러 인스턴스 생성 (상세 내용 크롤링용)
    crawlers = {
        'hankyung': HankyungCrawler(),
        'mk_news': MKNewsCrawler()
    }
    
    print("=" * 70)
    print("기존 데이터 재처리 시작")
    print("=" * 70)
    print()
    
    # 전체 뉴스 조회
    all_news = db.get_latest_news(limit=100000)
    total_count = len(all_news)
    
    print(f"전체 뉴스 개수: {total_count:,}개")
    print()
    
    # 통계
    stats = {
        'content_added': 0,
        'sentiment_analyzed': 0,
        'stock_codes_added': 0,
        'updated': 0
    }
    
    for i, news in enumerate(all_news, 1):
        if i % 100 == 0:
            print(f"진행 중... {i}/{total_count} ({i/total_count*100:.1f}%)")
        
        updated = False
        news_id = news.get('id')
        news_url = news.get('url', '')
        source = news.get('source', '')
        title = news.get('title', '')
        content = news.get('content', '')
        sentiment_score = news.get('sentiment_score')
        related_stocks = news.get('related_stocks', '')
        
        # 1. 내용이 없거나 짧은 경우 상세 내용 크롤링
        if not content or len(content) < 50:
            crawler = crawlers.get(source)
            if crawler and news_url:
                try:
                    detail = crawler.crawl_news_detail(news_url)
                    if detail and detail.get('content') and len(detail.get('content', '')) > len(content):
                        content = detail['content']
                        stats['content_added'] += 1
                        updated = True
                except Exception as e:
                    logger.debug(f"상세 내용 크롤링 오류: {news_url} - {e}")
        
        # 2. 감성 분석이 안 된 경우 분석 수행
        if sentiment_score is None:
            try:
                # 제목과 내용으로 감성 분석
                text = f"{title} {content}"
                sentiment = sentiment_analyzer.calculate_sentiment_score(text)
                importance = sentiment_analyzer.calculate_importance_score(text, source, news.get('category', ''))
                impact = sentiment_analyzer.calculate_impact_score(text, related_stocks)
                timeliness = sentiment_analyzer.calculate_timeliness_score(news.get('published_at', ''))
                
                overall_score = (
                    sentiment * 0.5 +
                    importance * 0.2 +
                    impact * 0.2 +
                    timeliness * 0.1
                )
                
                news['sentiment_score'] = round(sentiment, 3)
                news['importance_score'] = round(importance, 3)
                news['impact_score'] = round(impact, 3)
                news['timeliness_score'] = round(timeliness, 3)
                news['overall_score'] = round(overall_score, 3)
                
                stats['sentiment_analyzed'] += 1
                updated = True
            except Exception as e:
                logger.debug(f"감성 분석 오류: {news_id} - {e}")
        
        # 3. 종목 코드가 없거나 적은 경우 재추출
        if not related_stocks or len(related_stocks) < 3:
            try:
                text = f"{title} {content}"
                # BaseCrawler의 extract_stock_codes 사용
                from news_scraper.base_crawler import BaseCrawler
                temp_crawler = BaseCrawler("temp")
                new_stocks = temp_crawler.extract_stock_codes(text)
                
                if new_stocks and len(new_stocks) > len(related_stocks):
                    related_stocks = new_stocks
                    news['related_stocks'] = related_stocks
                    stats['stock_codes_added'] += 1
                    updated = True
            except Exception as e:
                logger.debug(f"종목 코드 추출 오류: {news_id} - {e}")
        
        # 4. 업데이트된 경우 데이터베이스에 저장
        if updated:
            try:
                # 기존 news_id 유지 (INSERT OR REPLACE가 news_id 기준으로 업데이트)
                if content:
                    news['content'] = content
                
                # news_id가 없으면 생성
                if not news.get('news_id'):
                    news['news_id'] = f"{source}_{news_id}"
                
                db.insert_news(news)
                stats['updated'] += 1
            except Exception as e:
                logger.error(f"데이터베이스 업데이트 오류: {news_id} - {e}")
    
    print()
    print("=" * 70)
    print("재처리 완료")
    print("=" * 70)
    print(f"내용 추가: {stats['content_added']:,}개")
    print(f"감성 분석: {stats['sentiment_analyzed']:,}개")
    print(f"종목 코드 추가: {stats['stock_codes_added']:,}개")
    print(f"전체 업데이트: {stats['updated']:,}개")
    print("=" * 70)


if __name__ == "__main__":
    reprocess_data()

