import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from news_scraper.price_fetcher import PriceFetcher
from news_scraper.database import NewsDatabase
import logging
import sys

# 로깅 끄기 (결과 가독성)
logging.getLogger('news_scraper.price_fetcher').setLevel(logging.ERROR)

def evaluate_performance(target_date=None):
    db = NewsDatabase()
    fetcher = PriceFetcher()
    
    print("=" * 80)
    print("AI 뉴스 분석 성과 검증 (백테스팅)")
    print("=" * 80)
    
    today = datetime.now()
    if target_date is None:
        # 데이터가 많은 1월 6일로 기본 설정
        target_date = "2026-01-06"
    
    # 1. 해당 날짜의 종목별 AI 분석 신호 집계
    query = f"""
        SELECT related_stocks, AVG(sentiment_score) as avg_sentiment, 
               AVG(overall_score) as avg_overall, COUNT(*) as news_count
        FROM news 
        WHERE date(published_at) = '{target_date}' 
          AND related_stocks != '' 
          AND sentiment_score IS NOT NULL
        GROUP BY related_stocks
        HAVING news_count >= 1
        ORDER BY avg_overall DESC
    """
    
    try:
        conn = sqlite3.connect("news_data.db")
        df_signals = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        print(f"디비 조회 오류: {e}")
        return
    
    if df_signals.empty:
        print(f"{target_date}일자의 분석 신호가 없어 검증을 진행할 수 없습니다.")
        return

    print(f"검증 기준일: {target_date}")
    print(f"현재 기준일: {today.strftime('%Y-%m-%d')}")
    print(f"분석 대상 종목 수: {len(df_signals)}개")
    print("-" * 80)
    
    results = []
    print("주가 데이터 수집 및 매칭 중...", end="", flush=True)
    
    for _, row in df_signals.iterrows():
        stock_codes = [s.strip() for s in row['related_stocks'].split(',') if s.strip()]
        for code in stock_codes:
            # 6자리 숫자가 아니면 스킵
            if not (code.isdigit() and len(code) == 6):
                continue
                
            # 과거 시점 주가와 현재 시점 주가 가져오기
            price_past = fetcher.get_price_at_date(code, target_date)
            price_today = fetcher.get_price_at_date(code, today.strftime('%Y-%m-%d'))
            
            if price_past and price_today and price_past['종가'] > 0:
                change_rate = (price_today['종가'] - price_past['종가']) / price_past['종가'] * 100
                results.append({
                    '종목코드': code,
                    'AI감성': row['avg_sentiment'],
                    'AI종합': row['avg_overall'],
                    '뉴스수': row['news_count'],
                    '과거주가': price_past['종가'],
                    '현재주가': price_today['종가'],
                    '수익률': change_rate
                })
        print(".", end="", flush=True)
    print("\n")
    
    if not results:
        print("주가 데이터를 매칭할 수 있는 종목이 없습니다.")
        return

    df_res = pd.DataFrame(results)
    # 중복 종목 제거 (여러 뉴스 그룹에 속할 수 있음)
    df_res = df_res.groupby('종목코드').first().reset_index()
    
    # 성과 분석 출력
    print(f"{'종목코드':<10} {'AI감성':<8} {'AI종합':<8} {'수익률(%)':<10} {'결과'}")
    print("-" * 80)
    
    hit_count = 0
    for _, row in df_res.sort_values('AI종합', ascending=False).iterrows():
        # AI가 긍정(>0.05)인데 실제 주가가 올랐거나(>0)
        # AI가 부정(<-0.05)인데 실제 주가가 내렸으면(<0) 적중!
        is_hit = False
        if row['AI감성'] > 0.05:
            if row['수익률'] > 0: is_hit = True
        elif row['AI감성'] < -0.05:
            if row['수익률'] < 0: is_hit = True
        else:
            # 중립 신호는 수익률이 -0.5% ~ 0.5% 사이면 적중으로 간주 (선택 사항)
            if abs(row['수익률']) < 0.5: is_hit = True
            
        if is_hit: hit_count += 1
        
        hit_str = "적중" if is_hit else "실패"
        print(f"{row['종목코드']:<10} {row['AI감성']:>8.2f} {row['AI종합']:>8.2f} {row['수익률']:>10.2f}% {hit_str}")
        
    print("-" * 80)
    print(f"전체 적중률: {hit_count/len(df_res)*100:.1f}% ({hit_count}/{len(df_res)})")
    
    # 긍정 신호만 따로 분석
    pos_df = df_res[df_res['AI감성'] > 0.05]
    if not pos_df.empty:
        pos_hit = len(pos_df[pos_df['수익률'] > 0])
        print(f"긍정 신호 적중률: {pos_hit/len(pos_df)*100:.1f}% ({pos_hit}/{len(pos_df)})")
        print(f"긍정 신호 평균 수익률: {pos_df['수익률'].mean():.2f}%")
        
    # 부정 신호만 따로 분석
    neg_df = df_res[df_res['AI감성'] < -0.05]
    if not neg_df.empty:
        neg_hit = len(neg_df[neg_df['수익률'] < 0])
        print(f"부정 신호 적중률: {neg_hit/len(neg_df)*100:.1f}% ({neg_hit}/{len(neg_df)})")
        print(f"부정 신호 평균 수익률: {neg_df['수익률'].mean():.2f}%")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    evaluate_performance(target)
