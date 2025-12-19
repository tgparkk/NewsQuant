"""
오늘자 뉴스 기반 종목 분석 스크립트
매수/매도 후보 종목 추천
"""

from datetime import datetime, timedelta
from news_scraper.database import NewsDatabase
from collections import defaultdict, Counter
import sqlite3

def analyze_today_stocks():
    """오늘자 뉴스 기반 종목 분석"""
    db = NewsDatabase()
    
    print("=" * 80)
    print("오늘자 뉴스 기반 종목 분석 리포트")
    print("=" * 80)
    print(f"분석 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 오늘 날짜 범위 설정
    today = datetime.now()
    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # 오늘자 뉴스 조회
    today_news = db.get_news_by_date_range(
        start_date.isoformat(),
        end_date.isoformat()
    )
    
    print(f"[1] 오늘자 뉴스 현황")
    print("-" * 80)
    print(f"총 뉴스 개수: {len(today_news):,}개")
    print()
    
    if len(today_news) == 0:
        print("[경고] 오늘자 뉴스가 없습니다.")
        return
    
    # 종목별 뉴스 수집 및 분석
    stock_analysis = defaultdict(lambda: {
        'news_list': [],
        'sentiment_scores': [],
        'overall_scores': [],
        'positive_count': 0,
        'negative_count': 0,
        'neutral_count': 0,
        'high_score_count': 0  # overall_score >= 0.7
    })
    
    for news in today_news:
        related_stocks = news.get('related_stocks', '')
        if related_stocks:
            stocks = [s.strip() for s in related_stocks.split(',') if s.strip()]
            sentiment_score = news.get('sentiment_score')
            overall_score = news.get('overall_score')
            
            for stock_code in stocks:
                stock_analysis[stock_code]['news_list'].append(news)
                
                if sentiment_score is not None:
                    stock_analysis[stock_code]['sentiment_scores'].append(sentiment_score)
                    if sentiment_score > 0:
                        stock_analysis[stock_code]['positive_count'] += 1
                    elif sentiment_score < 0:
                        stock_analysis[stock_code]['negative_count'] += 1
                    else:
                        stock_analysis[stock_code]['neutral_count'] += 1
                
                if overall_score is not None:
                    stock_analysis[stock_code]['overall_scores'].append(overall_score)
                    if overall_score >= 0.7:
                        stock_analysis[stock_code]['high_score_count'] += 1
    
    # 종목별 통계 계산
    stock_stats = []
    for stock_code, data in stock_analysis.items():
        news_count = len(data['news_list'])
        if news_count == 0:
            continue
        
        avg_sentiment = sum(data['sentiment_scores']) / len(data['sentiment_scores']) if data['sentiment_scores'] else 0.0
        avg_overall = sum(data['overall_scores']) / len(data['overall_scores']) if data['overall_scores'] else 0.0
        
        # 종합 점수 계산 (감성 점수 40% + 종합 점수 40% + 뉴스 개수 20%)
        news_score = min(news_count / 10.0, 1.0)  # 최대 10개 뉴스 = 1.0
        composite_score = (avg_sentiment * 0.4) + (avg_overall * 0.4) + (news_score * 0.2)
        
        stock_stats.append({
            'stock_code': stock_code,
            'news_count': news_count,
            'avg_sentiment': avg_sentiment,
            'avg_overall': avg_overall,
            'composite_score': composite_score,
            'positive_count': data['positive_count'],
            'negative_count': data['negative_count'],
            'neutral_count': data['neutral_count'],
            'high_score_count': data['high_score_count'],
            'positive_ratio': data['positive_count'] / news_count if news_count > 0 else 0.0
        })
    
    # 종합 점수 기준으로 정렬
    stock_stats.sort(key=lambda x: x['composite_score'], reverse=True)
    
    print(f"[2] 종목별 뉴스 현황 (총 {len(stock_stats)}개 종목)")
    print("-" * 80)
    print(f"{'종목코드':<10} {'뉴스수':<8} {'평균감성':<10} {'평균종합':<10} {'종합점수':<10} {'긍정비율':<10}")
    print("-" * 80)
    for stat in stock_stats[:20]:  # 상위 20개만 표시
        print(f"{stat['stock_code']:<10} {stat['news_count']:<8} "
              f"{stat['avg_sentiment']:>8.3f}  {stat['avg_overall']:>8.3f}  "
              f"{stat['composite_score']:>8.3f}  {stat['positive_ratio']:>8.1%}")
    print()
    
    # 매수 후보 종목 (긍정적인 뉴스가 많고 종합 점수가 높은 종목)
    print(f"[3] 매수 후보 종목 (긍정적 신호)")
    print("-" * 80)
    buy_candidates = [
        s for s in stock_stats
        if s['avg_sentiment'] > 0.05  # 평균 감성 점수가 0.05 이상
        and s['avg_overall'] > 0.3  # 평균 종합 점수가 0.3 이상
        and s['news_count'] >= 3  # 최소 3개 이상의 뉴스
        and s['positive_ratio'] >= 0.3  # 긍정 뉴스 비율 30% 이상
        and s['positive_count'] > s['negative_count']  # 긍정 뉴스가 부정 뉴스보다 많음
    ]
    
    buy_candidates.sort(key=lambda x: x['composite_score'], reverse=True)
    
    if buy_candidates:
        print(f"총 {len(buy_candidates)}개 종목")
        print()
        print(f"{'종목코드':<10} {'뉴스수':<8} {'평균감성':<10} {'평균종합':<10} {'긍정/부정':<12} {'주요 뉴스 요약'}")
        print("-" * 80)
        
        for i, stat in enumerate(buy_candidates[:10], 1):  # 상위 10개
            stock_code = stat['stock_code']
            # 해당 종목의 최신 뉴스 가져오기
            stock_news = [n for n in today_news if stock_code in (n.get('related_stocks', '') or '').split(',')]
            stock_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)
            
            latest_title = stock_news[0].get('title', 'N/A')[:60] if stock_news else 'N/A'
            
            print(f"{i}. {stock_code:<10} {stat['news_count']:<8} "
                  f"{stat['avg_sentiment']:>8.3f}  {stat['avg_overall']:>8.3f}  "
                  f"{stat['positive_count']}/{stat['negative_count']:<10} "
                  f"{latest_title}")
            # 추가 뉴스 1-2개 더 표시
            if len(stock_news) > 1:
                for j, news in enumerate(stock_news[1:3], 2):  # 최대 2개 더
                    title = news.get('title', 'N/A')[:60]
                    sentiment = news.get('sentiment_score', 0.0)
                    print(f"   [{j}] {title} (감성: {sentiment:.3f})")
    else:
        print("[경고] 매수 후보 종목이 없습니다.")
        print()
        # 상위 종목 중 관심 종목 표시
        print("상위 관심 종목 (매수 후보 조건 미달이지만 긍정적 신호):")
        top_positive = [
            s for s in stock_stats[:20]
            if s['avg_sentiment'] > 0.03
            and s['news_count'] >= 3
            and s not in buy_candidates
        ][:5]  # 최대 5개
        
        if top_positive:
            print(f"{'종목코드':<10} {'뉴스수':<8} {'평균감성':<10} {'평균종합':<10} {'긍정/부정':<12}")
            print("-" * 80)
            for i, stat in enumerate(top_positive, 1):
                print(f"{i}. {stat['stock_code']:<10} {stat['news_count']:<8} "
                      f"{stat['avg_sentiment']:>8.3f}  {stat['avg_overall']:>8.3f}  "
                      f"{stat['positive_count']}/{stat['negative_count']:<10}")
    print()
    
    # 매도 후보 종목 (부정적인 뉴스가 많고 종합 점수가 낮은 종목)
    print(f"[4] 매도 후보 종목 (부정적 신호)")
    print("-" * 80)
    sell_candidates = [
        s for s in stock_stats
        if s['avg_sentiment'] < -0.05  # 평균 감성 점수가 -0.05 미만
        and s['avg_overall'] < 0.3  # 평균 종합 점수가 0.3 미만
        and s['news_count'] >= 3  # 최소 3개 이상의 뉴스
        and s['negative_count'] > s['positive_count']  # 부정 뉴스가 긍정 뉴스보다 많음
    ]
    
    sell_candidates.sort(key=lambda x: x['composite_score'])  # 점수가 낮은 순으로 정렬
    
    if sell_candidates:
        print(f"총 {len(sell_candidates)}개 종목")
        print()
        print(f"{'종목코드':<10} {'뉴스수':<8} {'평균감성':<10} {'평균종합':<10} {'긍정/부정':<12} {'주요 뉴스 요약'}")
        print("-" * 80)
        
        for i, stat in enumerate(sell_candidates[:10], 1):  # 상위 10개
            stock_code = stat['stock_code']
            # 해당 종목의 최신 뉴스 가져오기
            stock_news = [n for n in today_news if stock_code in (n.get('related_stocks', '') or '').split(',')]
            stock_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)
            
            latest_title = stock_news[0].get('title', 'N/A')[:60] if stock_news else 'N/A'
            
            print(f"{i}. {stock_code:<10} {stat['news_count']:<8} "
                  f"{stat['avg_sentiment']:>8.3f}  {stat['avg_overall']:>8.3f}  "
                  f"{stat['positive_count']}/{stat['negative_count']:<10} "
                  f"{latest_title}")
            # 추가 뉴스 1-2개 더 표시
            if len(stock_news) > 1:
                for j, news in enumerate(stock_news[1:3], 2):  # 최대 2개 더
                    title = news.get('title', 'N/A')[:60]
                    sentiment = news.get('sentiment_score', 0.0)
                    print(f"   [{j}] {title} (감성: {sentiment:.3f})")
    else:
        print("[경고] 매도 후보 종목이 없습니다.")
    print()
    
    # 주의 종목 (뉴스는 많지만 감성 점수가 혼재된 종목)
    print(f"[5] 주의 관찰 종목 (신호 혼재)")
    print("-" * 80)
    watch_candidates = [
        s for s in stock_stats
        if s['news_count'] >= 3  # 뉴스가 3개 이상
        and -0.1 <= s['avg_sentiment'] <= 0.1  # 감성 점수가 중립에 가까움
        and s['positive_count'] > 0 and s['negative_count'] > 0  # 긍정/부정 뉴스가 모두 있음
    ]
    
    watch_candidates.sort(key=lambda x: x['news_count'], reverse=True)
    
    if watch_candidates:
        print(f"총 {len(watch_candidates)}개 종목")
        print()
        print(f"{'종목코드':<10} {'뉴스수':<8} {'평균감성':<10} {'평균종합':<10} {'긍정/부정':<12}")
        print("-" * 80)
        
        for i, stat in enumerate(watch_candidates[:10], 1):  # 상위 10개
            print(f"{i}. {stat['stock_code']:<10} {stat['news_count']:<8} "
                  f"{stat['avg_sentiment']:>8.3f}  {stat['avg_overall']:>8.3f}  "
                  f"{stat['positive_count']}/{stat['negative_count']:<10}")
    else:
        print("[경고] 주의 관찰 종목이 없습니다.")
    print()
    
    # 종합 요약
    print(f"[6] 종합 요약")
    print("-" * 80)
    print(f"- 오늘자 뉴스: {len(today_news):,}개")
    print(f"- 언급된 종목: {len(stock_stats):,}개")
    print(f"- 매수 후보: {len(buy_candidates):,}개")
    print(f"- 매도 후보: {len(sell_candidates):,}개")
    print(f"- 주의 관찰: {len(watch_candidates):,}개")
    print()
    
    print("=" * 80)
    print("[주의] 투자 참고사항")
    print("=" * 80)
    print("1. 본 분석은 뉴스 기반 감성 분석 결과입니다.")
    print("2. 실제 투자 결정 시에는 추가적인 기술적/기본적 분석이 필요합니다.")
    print("3. 뉴스 감성은 단기적 시장 심리에 영향을 줄 수 있으나, 장기 투자에는 한계가 있습니다.")
    print("4. 리스크 관리와 분산 투자를 항상 고려하세요.")
    print("=" * 80)

if __name__ == "__main__":
    analyze_today_stocks()
