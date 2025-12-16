"""
저장된 데이터 상세 예시 조회 스크립트
"""

import sys
import io
from datetime import datetime
from news_scraper.database import NewsDatabase

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def show_detailed_samples():
    """저장된 데이터 상세 예시 조회"""
    db = NewsDatabase()
    
    print("=" * 80)
    print("저장된 뉴스 데이터 상세 예시")
    print("=" * 80)
    print(f"조회 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 출처별로 내용이 있는 뉴스 찾기
    sources = ['hankyung', 'mk_news', 'naver_finance']
    
    for source in sources:
        print("=" * 80)
        print(f"[{source}] 출처의 뉴스 예시")
        print("=" * 80)
        
        news_list = db.get_latest_news(limit=20, source=source)
        
        # 내용이 있는 뉴스 찾기
        news_with_content = [n for n in news_list if n.get('content') and len(n.get('content', '').strip()) > 100]
        news_with_stocks = [n for n in news_list if n.get('related_stocks') and len(n.get('related_stocks', '').strip()) > 0]
        
        # 우선순위: 내용 있는 것 > 종목 코드 있는 것 > 그 외
        selected = []
        if news_with_content:
            selected = news_with_content[:2]
        elif news_with_stocks:
            selected = news_with_stocks[:2]
        else:
            selected = news_list[:2]
        
        for idx, news in enumerate(selected, 1):
            print(f"\n--- 예시 {idx} ---")
            print(f"뉴스 ID: {news.get('news_id', 'N/A')}")
            print(f"출처: {news.get('source', 'N/A')}")
            print(f"카테고리: {news.get('category', 'N/A')}")
            print(f"발행일시: {news.get('published_at', 'N/A')}")
            print()
            
            title = news.get('title', '')
            print(f"제목: {title}")
            print()
            
            content = news.get('content', '')
            if content and len(content.strip()) > 0:
                if len(content) > 500:
                    print(f"내용 (일부):\n{content[:500]}...")
                    print(f"\n(전체 길이: {len(content):,}자)")
                else:
                    print(f"내용:\n{content}")
            else:
                print("내용: (없음)")
            print()
            
            url = news.get('url', '')
            print(f"URL: {url}")
            print()
            
            related_stocks = news.get('related_stocks', '')
            if related_stocks and len(related_stocks.strip()) > 0:
                stocks_list = [s.strip() for s in related_stocks.split(',') if s.strip()]
                print(f"관련 종목 코드: {', '.join(stocks_list)} ({len(stocks_list)}개)")
            else:
                print("관련 종목 코드: (없음)")
            print()
            
            print("점수 정보:")
            sentiment_score = news.get('sentiment_score')
            importance_score = news.get('importance_score')
            impact_score = news.get('impact_score')
            timeliness_score = news.get('timeliness_score')
            overall_score = news.get('overall_score')
            
            if sentiment_score is not None:
                sentiment_label = "긍정" if sentiment_score > 0 else "부정" if sentiment_score < 0 else "중립"
                print(f"  감성 점수: {sentiment_score:.3f} ({sentiment_label})")
            else:
                print(f"  감성 점수: (없음)")
            
            if importance_score is not None:
                print(f"  중요도 점수: {importance_score:.3f}")
            else:
                print(f"  중요도 점수: (없음)")
            
            if impact_score is not None:
                print(f"  영향도 점수: {impact_score:.3f}")
            else:
                print(f"  영향도 점수: (없음)")
            
            if timeliness_score is not None:
                print(f"  실시간성 점수: {timeliness_score:.3f}")
            else:
                print(f"  실시간성 점수: (없음)")
            
            if overall_score is not None:
                print(f"  종합 점수: {overall_score:.3f}")
            else:
                print(f"  종합 점수: (없음)")
            
            print()
            print("-" * 80)
        
        print()
    
    # 종목 코드가 있는 뉴스 예시
    print("=" * 80)
    print("[종목 코드가 있는 뉴스 예시]")
    print("=" * 80)
    
    all_news = db.get_latest_news(limit=100)
    news_with_stocks = [n for n in all_news if n.get('related_stocks') and len(n.get('related_stocks', '').strip()) > 0]
    
    if news_with_stocks:
        for idx, news in enumerate(news_with_stocks[:3], 1):
            print(f"\n--- 예시 {idx} ---")
            print(f"출처: {news.get('source', 'N/A')}")
            print(f"제목: {news.get('title', 'N/A')}")
            stocks = news.get('related_stocks', '')
            stocks_list = [s.strip() for s in stocks.split(',') if s.strip()]
            print(f"관련 종목: {', '.join(stocks_list)}")
            print(f"종합 점수: {news.get('overall_score', 'N/A')}")
            print()
    else:
        print("종목 코드가 있는 뉴스가 없습니다.")
    
    print("=" * 80)

if __name__ == "__main__":
    show_detailed_samples()
