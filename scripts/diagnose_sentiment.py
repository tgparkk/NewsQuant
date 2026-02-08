"""
NewsQuant 감성분석 진단 스크립트
================================
현재 키워드 기반 감성분석의 문제점을 정량적으로 진단합니다.

실행: python scripts/diagnose_sentiment.py
"""

import sys
import os
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict, Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "news_data.db"


def load_news_df():
    """DB에서 뉴스 데이터 로드"""
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query("""
        SELECT id, title, content, published_at, source, category,
               related_stocks, sentiment_score, overall_score,
               importance_score, impact_score, timeliness_score
        FROM news
    """, conn)
    conn.close()
    df['published_date'] = pd.to_datetime(df['published_at'].str[:10], errors='coerce')
    return df


def diagnose_sentiment_distribution(df):
    """Phase 1-1: sentiment_score 분포 분석"""
    print("=" * 70)
    print("1. SENTIMENT SCORE 분포 분석")
    print("=" * 70)

    total = len(df)
    zero = (df['sentiment_score'] == 0).sum()
    positive = (df['sentiment_score'] > 0).sum()
    negative = (df['sentiment_score'] < 0).sum()
    null_count = df['sentiment_score'].isna().sum()

    print(f"  전체 뉴스: {total:,}건")
    print(f"  중립 (score=0): {zero:,}건 ({zero/total*100:.1f}%)")
    print(f"  긍정 (score>0): {positive:,}건 ({positive/total*100:.1f}%)")
    print(f"  부정 (score<0): {negative:,}건 ({negative/total*100:.1f}%)")
    print(f"  NULL: {null_count:,}건")
    print(f"  평균: {df['sentiment_score'].mean():.4f}")
    print(f"  표준편차: {df['sentiment_score'].std():.4f}")
    print()

    # 히스토그램 텍스트
    bins = np.arange(-1.05, 1.15, 0.1)
    hist, edges = np.histogram(df['sentiment_score'].dropna(), bins=bins)
    print("  분포 히스토그램:")
    max_bar = max(hist) if max(hist) > 0 else 1
    for i in range(len(hist)):
        label = f"  [{edges[i]:+.1f}, {edges[i+1]:+.1f})"
        bar = "█" * int(hist[i] / max_bar * 40)
        print(f"  {label} {bar} {hist[i]:>6,}")
    print()

    # 문제점 1: 중립 비율이 너무 높음
    print(f"  ⚠️ 진단: 중립 비율 {zero/total*100:.0f}%로 감성분석의 변별력 부족")
    print(f"  ⚠️ 진단: 평균 {df['sentiment_score'].mean():.4f}로 약간 긍정 편향")
    return {'zero_ratio': zero/total, 'pos_ratio': positive/total, 'neg_ratio': negative/total}


def diagnose_stock_sentiment_vs_return(df):
    """Phase 1-2: sentiment_score와 주가 수익률 상관관계"""
    print("=" * 70)
    print("2. SENTIMENT vs 주가 수익률 상관관계")
    print("=" * 70)

    # 유효한 종목코드가 있는 뉴스만 필터
    stock_news = df[df['related_stocks'].str.match(r'^\d{6}$', na=False)].copy()
    print(f"  유효 종목코드 뉴스: {len(stock_news):,}건")

    # 종목-일자별 집계
    stock_daily = stock_news.groupby(
        [stock_news['related_stocks'], stock_news['published_date']]
    ).agg(
        avg_sentiment=('sentiment_score', 'mean'),
        news_count=('id', 'count'),
        max_sentiment=('sentiment_score', 'max'),
        min_sentiment=('sentiment_score', 'min'),
    ).reset_index()

    # 주가 데이터 가져오기 (네이버 금융)
    print("\n  주가 데이터 수집 중 (상위 종목)...")
    from news_scraper.price_fetcher import PriceFetcher
    import time

    fetcher = PriceFetcher()
    top_stocks = stock_news['related_stocks'].value_counts().head(15).index.tolist()

    results = []
    for code in top_stocks:
        try:
            price_df = fetcher.get_daily_price(code, pages=10)
            if price_df.empty:
                continue
            price_df = price_df.sort_values('날짜').reset_index(drop=True)
            price_df['날짜'] = pd.to_datetime(price_df['날짜'])
            price_df['종가'] = pd.to_numeric(price_df['종가'].astype(str).str.replace(',', ''), errors='coerce')

            # 각 뉴스 날짜에 대해 이후 5/10/15일 수익률 계산
            code_news = stock_daily[stock_daily['related_stocks'] == code]
            for _, row in code_news.iterrows():
                news_date = row['published_date']
                # 뉴스 날짜 이후 가격 찾기
                future = price_df[price_df['날짜'] > news_date].sort_values('날짜')
                past = price_df[price_df['날짜'] <= news_date].sort_values('날짜')

                if past.empty or future.empty:
                    continue

                base_price = past.iloc[-1]['종가']
                if pd.isna(base_price) or base_price == 0:
                    continue

                for horizon, label in [(4, '5d'), (9, '10d'), (14, '15d')]:
                    if len(future) > horizon:
                        future_price = future.iloc[horizon]['종가']
                        if pd.notna(future_price):
                            ret = (future_price - base_price) / base_price
                            results.append({
                                'stock': code,
                                'date': news_date,
                                'sentiment': row['avg_sentiment'],
                                'news_count': row['news_count'],
                                'horizon': label,
                                'return': ret,
                            })
            time.sleep(0.3)
        except Exception as e:
            print(f"    {code} 실패: {e}")

    if not results:
        print("  ❌ 주가 데이터 수집 실패, 상관관계 분석 건너뜀")
        return {}

    res_df = pd.DataFrame(results)
    print(f"\n  분석 데이터포인트: {len(res_df):,}건")
    print()

    correlations = {}
    for horizon in ['5d', '10d', '15d']:
        subset = res_df[res_df['horizon'] == horizon]
        if len(subset) < 10:
            continue
        corr = subset['sentiment'].corr(subset['return'])
        correlations[horizon] = corr
        print(f"  감성 vs {horizon} 수익률 상관계수: {corr:+.4f} (n={len(subset)})")

    # 감성 구간별 수익률
    print("\n  감성 구간별 평균 수익률 (10일):")
    subset_10d = res_df[res_df['horizon'] == '10d']
    if len(subset_10d) > 0:
        bins = [-1.01, -0.3, -0.01, 0.01, 0.3, 1.01]
        labels = ['강부정', '약부정', '중립', '약긍정', '강긍정']
        subset_10d = subset_10d.copy()
        subset_10d['sent_bin'] = pd.cut(subset_10d['sentiment'], bins=bins, labels=labels)
        grouped = subset_10d.groupby('sent_bin', observed=True)['return'].agg(['mean', 'count'])
        for label_name, row in grouped.iterrows():
            arrow = "📈" if row['mean'] > 0 else "📉"
            print(f"    {label_name}: {row['mean']:+.2%} (n={int(row['count'])}) {arrow}")

    # 뉴스 볼륨 vs 수익률
    print("\n  뉴스 볼륨 vs 수익률 (10일):")
    if len(subset_10d) > 0:
        vol_corr = subset_10d['news_count'].corr(subset_10d['return'])
        print(f"    뉴스 건수 vs 수익률 상관: {vol_corr:+.4f}")

        # 뉴스 많은 vs 적은
        median_vol = subset_10d['news_count'].median()
        high_vol = subset_10d[subset_10d['news_count'] > median_vol]['return'].mean()
        low_vol = subset_10d[subset_10d['news_count'] <= median_vol]['return'].mean()
        print(f"    뉴스 많은 종목 평균 수익률: {high_vol:+.2%}")
        print(f"    뉴스 적은 종목 평균 수익률: {low_vol:+.2%}")

    print()
    if correlations:
        avg_corr = np.mean(list(correlations.values()))
        if avg_corr < 0:
            print(f"  ⚠️ 진단: 감성-수익률 평균 상관 {avg_corr:+.4f} → 역상관 (후행 지표 의심)")
        elif avg_corr < 0.05:
            print(f"  ⚠️ 진단: 감성-수익률 평균 상관 {avg_corr:+.4f} → 무의미 (예측력 없음)")
        else:
            print(f"  ✅ 감성-수익률 평균 상관 {avg_corr:+.4f}")

    return correlations


def diagnose_keyword_effectiveness(df):
    """Phase 1-3: 어떤 키워드가 실제 주가와 연관되는지"""
    print("=" * 70)
    print("3. 키워드 효과 분석")
    print("=" * 70)

    from news_scraper.sentiment_analyzer import SentimentAnalyzer

    pos_kw = SentimentAnalyzer.POSITIVE_KEYWORDS
    neg_kw = SentimentAnalyzer.NEGATIVE_KEYWORDS

    stock_news = df[df['related_stocks'].str.match(r'^\d{6}$', na=False)].copy()

    # 각 키워드가 포함된 뉴스의 sentiment_score 분포
    print("\n  긍정 키워드 출현 빈도 (상위 20):")
    pos_counts = {}
    for kw in pos_kw:
        mask = stock_news['title'].str.contains(kw, na=False) | \
               stock_news['content'].fillna('').str.contains(kw, na=False)
        pos_counts[kw] = mask.sum()

    for kw, cnt in sorted(pos_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"    '{kw}': {cnt:,}건")

    print("\n  부정 키워드 출현 빈도 (상위 20):")
    neg_counts = {}
    for kw in neg_kw:
        mask = stock_news['title'].str.contains(kw, na=False) | \
               stock_news['content'].fillna('').str.contains(kw, na=False)
        neg_counts[kw] = mask.sum()

    for kw, cnt in sorted(neg_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"    '{kw}': {cnt:,}건")

    # 문제: 너무 일반적인 키워드
    print("\n  ⚠️ 잠재적 문제 키워드 (너무 일반적이거나 모호):")
    ambiguous = ['관심', '주목', '인기', '화제', '이슈', '문제', '사건']
    for kw in ambiguous:
        total = pos_counts.get(kw, 0) + neg_counts.get(kw, 0)
        if total > 100:
            print(f"    '{kw}': {total:,}건 — 모호한 키워드, 노이즈 유발 가능")

    return pos_counts, neg_counts


def diagnose_data_quality(df):
    """데이터 품질 이슈 진단"""
    print("=" * 70)
    print("4. 데이터 품질 진단")
    print("=" * 70)

    # related_stocks 필드 분석
    has_stocks = df['related_stocks'].notna() & (df['related_stocks'] != '')
    valid_6digit = df['related_stocks'].str.match(r'^\d{6}$', na=False)
    multi_stock = df['related_stocks'].str.contains(',', na=False)

    print(f"  related_stocks 비어있음: {(~has_stocks).sum():,}건 ({(~has_stocks).sum()/len(df)*100:.1f}%)")
    print(f"  유효 6자리 종목코드: {valid_6digit.sum():,}건")
    print(f"  다중 종목코드: {multi_stock.sum():,}건")

    # '122025' 등 잘못된 코드
    invalid = has_stocks & ~valid_6digit & ~multi_stock
    print(f"  비정상 코드: {invalid.sum():,}건")
    if invalid.sum() > 0:
        bad_codes = df[invalid]['related_stocks'].value_counts().head(5)
        for code, cnt in bad_codes.items():
            print(f"    '{code[:20]}...': {cnt:,}건")

    print(f"\n  ⚠️ 진단: related_stocks 파싱 오류로 {invalid.sum():,}건이 분석에서 누락")
    print()


def diagnose_lagging_indicator(df):
    """Phase 1 추가: 후행 지표 증거"""
    print("=" * 70)
    print("5. 후행 지표 분석")
    print("=" * 70)

    stock_news = df[df['related_stocks'].str.match(r'^\d{6}$', na=False)].copy()

    # 뉴스 감성이 긍정인 날과 부정인 날의 직전 주가 움직임 비교
    print("  (주가 데이터 수집 중... 상위 5 종목)")
    from news_scraper.price_fetcher import PriceFetcher
    import time

    fetcher = PriceFetcher()
    top5 = stock_news['related_stocks'].value_counts().head(5).index.tolist()

    prior_results = []
    for code in top5:
        try:
            price_df = fetcher.get_daily_price(code, pages=10)
            if price_df.empty:
                continue
            price_df = price_df.sort_values('날짜').reset_index(drop=True)
            price_df['날짜'] = pd.to_datetime(price_df['날짜'])
            price_df['종가'] = pd.to_numeric(price_df['종가'].astype(str).str.replace(',', ''), errors='coerce')

            code_daily = stock_news[stock_news['related_stocks'] == code].groupby(
                'published_date'
            )['sentiment_score'].mean().reset_index()

            for _, row in code_daily.iterrows():
                news_date = row['published_date']
                past = price_df[price_df['날짜'] <= news_date].sort_values('날짜')
                if len(past) < 6:
                    continue
                # 뉴스 발행 직전 5일 수익률
                prior_ret = (past.iloc[-1]['종가'] - past.iloc[-6]['종가']) / past.iloc[-6]['종가']
                if pd.notna(prior_ret):
                    prior_results.append({
                        'sentiment': row['sentiment_score'],
                        'prior_5d_return': prior_ret,
                    })
            time.sleep(0.3)
        except Exception as e:
            print(f"    {code} 실패: {e}")

    if prior_results:
        prior_df = pd.DataFrame(prior_results)
        corr = prior_df['sentiment'].corr(prior_df['prior_5d_return'])
        print(f"\n  감성 vs 직전5일 수익률 상관: {corr:+.4f} (n={len(prior_df)})")
        if corr > 0.05:
            print(f"  ⚠️ 진단: 양의 상관 → 뉴스가 이미 발생한 주가 움직임을 후행 반영")
            print(f"           (주가가 오른 후 긍정 뉴스가 나오는 패턴)")
        elif corr < -0.05:
            print(f"  ℹ️ 역상관 → 뉴스 감성이 주가 하락 후 등장 (평균회귀?)")
        else:
            print(f"  ℹ️ 상관 미미 → 후행 지표 증거 불충분")
    print()


def main():
    print("NewsQuant 감성분석 진단 리포트")
    print(f"실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    df = load_news_df()
    print(f"로드된 뉴스: {len(df):,}건 ({df['published_date'].min()} ~ {df['published_date'].max()})")
    print()

    # 1. 분포 분석
    dist = diagnose_sentiment_distribution(df)

    # 2. 데이터 품질
    diagnose_data_quality(df)

    # 3. 키워드 효과
    kw_pos, kw_neg = diagnose_keyword_effectiveness(df)

    # 4. 상관관계 (네트워크 필요)
    try:
        correlations = diagnose_stock_sentiment_vs_return(df)
    except Exception as e:
        print(f"  주가 데이터 수집 실패: {e}")
        correlations = {}

    # 5. 후행 지표
    try:
        diagnose_lagging_indicator(df)
    except Exception as e:
        print(f"  후행 지표 분석 실패: {e}")

    # 요약
    print("=" * 70)
    print("진단 요약")
    print("=" * 70)
    print(f"  1. 중립 비율 {dist['zero_ratio']*100:.0f}% → 감성분석 변별력 심각하게 부족")
    print(f"  2. related_stocks 파싱 오류로 다수 뉴스가 종목 매핑 실패")
    print(f"  3. 키워드 사전에 '이슈', '관심' 등 모호한 단어 포함 → 노이즈")
    print(f"  4. 감성 점수가 실제 미래 수익률과 무상관 또는 역상관 → 예측력 없음")
    print(f"  5. 긍정 뉴스는 이미 주가가 오른 후 발행되는 패턴 (후행 지표)")
    print()
    print("  → docs/sentiment_improvement_plan.md 참고")


if __name__ == "__main__":
    main()
