"""
오늘자 뉴스 기반 종목 분석 스크립트 (v2 - 확산도 가중치 추가)
매수/매도 후보 종목 추천
"""

from datetime import datetime, timedelta
from news_scraper.database import NewsDatabase
from collections import defaultdict, Counter
import sqlite3
import math

def calculate_spread_weight(duplicate_count):
    """
    중복 횟수를 확산도 가중치로 변환
    
    옵션 A (보수적 접근):
    - 중복 2-3회: 가산점 +10%
    - 중복 4-5회: 가산점 +20%
    - 중복 6회 이상: 가산점 +30% (상한선)
    
    Args:
        duplicate_count: 중복 횟수
    
    Returns:
        가중치 (1.0 = 기본, 1.1 = +10%, 1.2 = +20%, 1.3 = +30%)
    """
    if duplicate_count >= 6:
        return 1.30  # +30%
    elif duplicate_count >= 4:
        return 1.20  # +20%
    elif duplicate_count >= 2:
        return 1.10  # +10%
    else:
        return 1.0   # 기본

def analyze_today_stocks():
    """오늘자 뉴스 기반 종목 분석 (확산도 포함)"""
    db = NewsDatabase()
    
    print("=" * 80)
    print("오늘자 뉴스 기반 종목 분석 리포트 (v2 - 확산도 가중치)")
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
    
    # 확산도 통계
    high_spread_news = [n for n in today_news if n.get('duplicate_count', 1) >= 5]
    total_spread = sum(n.get('duplicate_count', 1) for n in today_news)
    avg_spread = total_spread / len(today_news) if today_news else 0
    
    print(f"총 확산도: {total_spread:,} (평균: {avg_spread:.2f})")
    print(f"고확산 뉴스(5회 이상): {len(high_spread_news):,}개")
    print()
    
    if len(today_news) == 0:
        print("[경고] 오늘자 뉴스가 없습니다.")
        return
    
    # 종목별 뉴스 수집 및 분석
    stock_analysis = defaultdict(lambda: {
        'news_list': [],
        'sentiment_scores': [],
        'overall_scores': [],
        'spread_weights': [],
        'positive_count': 0,
        'negative_count': 0,
        'neutral_count': 0,
        'high_score_count': 0,
        'total_spread': 0,
    })
    
    for news in today_news:
        related_stocks = news.get('related_stocks', '')
        if related_stocks:
            stocks = [s.strip() for s in related_stocks.split(',') if s.strip()]
            sentiment_score = news.get('sentiment_score')
            overall_score = news.get('overall_score')
            duplicate_count = news.get('duplicate_count', 1)
            spread_weight = calculate_spread_weight(duplicate_count)
            
            for stock_code in stocks:
                stock_analysis[stock_code]['news_list'].append(news)
                stock_analysis[stock_code]['spread_weights'].append(spread_weight)
                stock_analysis[stock_code]['total_spread'] += duplicate_count
                
                if sentiment_score is not None:
                    # 확산도를 반영한 감성 점수
                    weighted_sentiment = sentiment_score * spread_weight
                    stock_analysis[stock_code]['sentiment_scores'].append(weighted_sentiment)
                    
                    if sentiment_score > 0:
                        stock_analysis[stock_code]['positive_count'] += 1
                    elif sentiment_score < 0:
                        stock_analysis[stock_code]['negative_count'] += 1
                    else:
                        stock_analysis[stock_code]['neutral_count'] += 1
                
                if overall_score is not None:
                    # 확산도를 반영한 종합 점수
                    weighted_overall = overall_score * spread_weight
                    stock_analysis[stock_code]['overall_scores'].append(weighted_overall)
                    
                    if overall_score >= 0.7:
                        stock_analysis[stock_code]['high_score_count'] += 1
    
    # 종목별 통계 계산
    stock_stats = []
    for stock_code, data in stock_analysis.items():
        news_count = len(data['news_list'])
        if news_count == 0:
            continue
        
        # 확산도 가중 평균 계산
        avg_sentiment = sum(data['sentiment_scores']) / len(data['sentiment_scores']) if data['sentiment_scores'] else 0.0
        avg_overall = sum(data['overall_scores']) / len(data['overall_scores']) if data['overall_scores'] else 0.0
        avg_spread_weight = sum(data['spread_weights']) / len(data['spread_weights']) if data['spread_weights'] else 1.0
        
        # 종합 점수 계산 (확산도 반영)
        news_score = min(news_count / 10.0, 1.0)
        spread_score = min((avg_spread_weight - 1.0) * 2, 0.3)  # 0~0.3 범위
        
        # 가중치: 감성(30%), 종합(30%), 뉴스개수(20%), 확산도(20%)
        composite_score = (avg_sentiment * 0.3) + (avg_overall * 0.3) + (news_score * 0.2) + (spread_score * 0.2)
        
        stock_stats.append({
            'stock_code': stock_code,
            'news_count': news_count,
            'avg_sentiment': avg_sentiment,
            'avg_overall': avg_overall,
            'avg_spread': avg_spread_weight,
            'total_spread': data['total_spread'],
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
    print(f"{'종목코드':<10} {'뉴스수':<8} {'평균감성':<10} {'평균종합':<10} {'확산도':<10} {'종합점수':<10}")
    print("-" * 80)
    for stat in stock_stats[:20]:  # 상위 20개만 표시
        print(f"{stat['stock_code']:<10} {stat['news_count']:<8} "
              f"{stat['avg_sentiment']:>8.3f}  {stat['avg_overall']:>8.3f}  "
              f"{stat['avg_spread']:>8.2f}  {stat['composite_score']:>8.3f}")
    print()
    
    # 매수 후보 종목 (긍정적인 뉴스가 많고 종합 점수가 높은 종목)
    print(f"[3] 매수 후보 종목 (긍정적 신호 + 높은 확산도)")
    print("-" * 80)
    buy_candidates = [
        s for s in stock_stats
        if s['avg_sentiment'] > 0.05
        and s['avg_overall'] > 0.3
        and s['news_count'] >= 3
        and s['positive_ratio'] >= 0.3
        and s['positive_count'] > s['negative_count']
    ]
    
    buy_candidates.sort(key=lambda x: x['composite_score'], reverse=True)
    
    if buy_candidates:
        print(f"총 {len(buy_candidates)}개 종목")
        print()
        print(f"{'순위':<6} {'종목코드':<10} {'뉴스수':<8} {'감성':<8} {'종합':<8} {'확산도':<8} {'점수':<8} {'주요 뉴스'}")
        print("-" * 80)
        
        for i, stat in enumerate(buy_candidates[:15], 1):  # 상위 15개
            stock_code = stat['stock_code']
            stock_news = [n for n in today_news if stock_code in (n.get('related_stocks', '') or '').split(',')]
            stock_news.sort(key=lambda x: x.get('duplicate_count', 1), reverse=True)
            
            # 가장 확산도가 높은 뉴스 제목
            if stock_news:
                top_news = stock_news[0]
                latest_title = top_news.get('title', 'N/A')[:50]
                spread_count = top_news.get('duplicate_count', 1)
                spread_tag = f"[확산x{spread_count}]" if spread_count > 1 else ""
            else:
                latest_title = 'N/A'
                spread_tag = ""
            
            print(f"{i:<6} {stock_code:<10} {stat['news_count']:<8} "
                  f"{stat['avg_sentiment']:>6.3f}  {stat['avg_overall']:>6.3f}  "
                  f"{stat['avg_spread']:>6.2f}  {stat['composite_score']:>6.3f}  "
                  f"{spread_tag} {latest_title}")
    else:
        print("[경고] 매수 후보 종목이 없습니다.")
    
    print()
    
    # 매도 후보 종목
    print(f"[4] 매도 후보 종목 (부정적 신호)")
    print("-" * 80)
    sell_candidates = [
        s for s in stock_stats
        if s['avg_sentiment'] < -0.05
        and s['avg_overall'] < 0.3
        and s['news_count'] >= 3
        and s['negative_count'] > s['positive_count']
    ]
    
    sell_candidates.sort(key=lambda x: x['composite_score'])
    
    if sell_candidates:
        print(f"총 {len(sell_candidates)}개 종목")
        print()
        print(f"{'순위':<6} {'종목코드':<10} {'뉴스수':<8} {'감성':<8} {'종합':<8} {'확산도':<8} {'주요 뉴스'}")
        print("-" * 80)
        
        for i, stat in enumerate(sell_candidates[:10], 1):
            stock_code = stat['stock_code']
            stock_news = [n for n in today_news if stock_code in (n.get('related_stocks', '') or '').split(',')]
            stock_news.sort(key=lambda x: x.get('duplicate_count', 1), reverse=True)
            
            if stock_news:
                top_news = stock_news[0]
                latest_title = top_news.get('title', 'N/A')[:50]
                spread_count = top_news.get('duplicate_count', 1)
                spread_tag = f"[확산x{spread_count}]" if spread_count > 1 else ""
            else:
                latest_title = 'N/A'
                spread_tag = ""
            
            print(f"{i:<6} {stock_code:<10} {stat['news_count']:<8} "
                  f"{stat['avg_sentiment']:>6.3f}  {stat['avg_overall']:>6.3f}  "
                  f"{stat['avg_spread']:>6.2f}  {spread_tag} {latest_title}")
    else:
        print("[OK] 매도 후보 종목이 없습니다.")
    
    print()
    
    # 고확산 종목 (화제성)
    print(f"[5] 고확산 종목 TOP 10 (시장 화제)")
    print("-" * 80)
    high_spread_stocks = sorted(stock_stats, key=lambda x: x['total_spread'], reverse=True)[:10]
    
    print(f"{'순위':<6} {'종목코드':<10} {'총확산도':<10} {'뉴스수':<8} {'평균확산':<10} {'감성':<8}")
    print("-" * 80)
    for i, stat in enumerate(high_spread_stocks, 1):
        print(f"{i:<6} {stat['stock_code']:<10} {stat['total_spread']:<10} "
              f"{stat['news_count']:<8} {stat['total_spread']/stat['news_count']:>8.2f}  "
              f"{stat['avg_sentiment']:>6.3f}")
    
    print()
    
    # 종합 요약
    print(f"[6] 종합 요약")
    print("-" * 80)
    print(f"- 오늘자 뉴스: {len(today_news):,}개 (총 확산도: {total_spread:,})")
    print(f"- 언급된 종목: {len(stock_stats):,}개")
    print(f"- 매수 후보: {len(buy_candidates):,}개")
    print(f"- 매도 후보: {len(sell_candidates):,}개")
    print(f"- 고확산 뉴스(5회+): {len(high_spread_news):,}개")
    print()
    
    print("=" * 80)
    print("[참고] 확산도 가중치 (옵션 A - 보수적)")
    print("=" * 80)
    print("중복 1회: 가중치 1.0 (기본)")
    print("중복 2-3회: 가중치 1.1 (+10% 가산점)")
    print("중복 4-5회: 가중치 1.2 (+20% 가산점)")
    print("중복 6회+: 가중치 1.3 (+30% 가산점, 상한선)")
    print()
    print("[주의] 투자 참고사항")
    print("- 본 분석은 뉴스 기반 감성 분석 + 확산도(시장 관심도) 결과입니다.")
    print("- 확산도는 같은 뉴스가 여러 번 보도될수록 증가합니다.")
    print("- 실제 투자 결정 시에는 추가적인 기술적/기본적 분석이 필요합니다.")
    print("=" * 80)

if __name__ == "__main__":
    analyze_today_stocks()
