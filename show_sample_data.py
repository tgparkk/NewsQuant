"""
저장된 데이터 예시 조회 스크립트
"""

import sys
import io
from datetime import datetime
from news_scraper.database import NewsDatabase
import json

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def show_sample_data(limit=10):
    """저장된 데이터 예시 조회"""
    db = NewsDatabase()
    
    print("=" * 80)
    print("저장된 뉴스 데이터 예시")
    print("=" * 80)
    print(f"조회 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 최신 뉴스 조회
    latest_news = db.get_latest_news(limit=limit * 3)  # 더 많이 가져와서 필터링
    
    # 내용이 있는 뉴스 우선 선택
    news_with_content = [n for n in latest_news if n.get('content') and len(n.get('content', '')) > 50]
    news_without_content = [n for n in latest_news if not n.get('content') or len(n.get('content', '')) <= 50]
    
    # 내용 있는 것 몇 개, 없는 것 몇 개 섞어서 보여주기
    selected_news = news_with_content[:limit//2] + news_without_content[:limit//2]
    if len(selected_news) < limit:
        selected_news = latest_news[:limit]
    
    if not selected_news:
        print("데이터베이스에 뉴스가 없습니다.")
        return
    
    print(f"총 {len(selected_news)}개의 뉴스 예시를 보여드립니다.")
    print(f"(내용 있는 뉴스: {len(news_with_content)}개, 내용 없는 뉴스: {len(news_without_content)}개)\n")
    
    for idx, news in enumerate(selected_news, 1):
        print("-" * 80)
        print(f"[예시 {idx}]")
        print("-" * 80)
        print(f"뉴스 ID: {news.get('news_id', 'N/A')}")
        print(f"출처: {news.get('source', 'N/A')}")
        print(f"카테고리: {news.get('category', 'N/A')}")
        print(f"발행일시: {news.get('published_at', 'N/A')}")
        print(f"생성일시: {news.get('created_at', 'N/A')}")
        print()
        print(f"제목: {news.get('title', 'N/A')}")
        print()
        
        content = news.get('content', '')
        if content:
            # 내용이 길면 앞부분만 표시
            if len(content) > 300:
                print(f"내용 (일부): {content[:300]}...")
                print(f"(전체 길이: {len(content)}자)")
            else:
                print(f"내용: {content}")
        else:
            print("내용: (없음)")
        print()
        
        print(f"URL: {news.get('url', 'N/A')}")
        print()
        
        related_stocks = news.get('related_stocks', '')
        if related_stocks:
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
        print()
    
    print("=" * 80)
    print()
    
    # 출처별로도 몇 개씩 보여주기
    print("=" * 80)
    print("출처별 데이터 예시")
    print("=" * 80)
    
    sources = ['naver_finance', 'hankyung', 'mk_news']
    for source in sources:
        source_news = db.get_latest_news(limit=2, source=source)
        if source_news:
            print(f"\n[{source}] - 최신 {len(source_news)}개")
            for news in source_news:
                print(f"  - {news.get('title', 'N/A')[:60]}...")
                print(f"    발행: {news.get('published_at', 'N/A')[:19]}")
                print(f"    종목: {news.get('related_stocks', '없음')[:30]}")
                print(f"    종합점수: {news.get('overall_score', 'N/A')}")
                print()
    
    print("=" * 80)

if __name__ == "__main__":
    show_sample_data(limit=5)
