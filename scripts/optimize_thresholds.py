"""
NewsQuant 매매 시그널 임계값 최적화 (Grid Search)
==================================================
1) DB에서 모든 날짜별 종목 통계를 미리 추출
2) 모든 후보 종목의 주가를 한번에 크롤링 & 캐시
3) Grid search로 임계값 조합별 성과 평가 (캐시만 사용, 빠름)

사용법:
    python scripts/optimize_thresholds.py
    python scripts/optimize_thresholds.py --start 2025-12-12 --end 2026-02-06
"""

import sys
import os
import argparse
import time
import json
import pickle
import logging
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from itertools import product

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from news_scraper.database import NewsDatabase
from news_scraper.price_fetcher import PriceFetcher

logging.basicConfig(level=logging.WARNING, format='%(message)s')
logger = logging.getLogger(__name__)

HOLDING_DAYS = [1, 3, 5, 7, 10]

# ─── Grid search 파라미터 ───────────────────────────────────────

BUY_GRID = {
    'avg_sentiment': [0.05, 0.1, 0.15, 0.2, 0.25, 0.3],
    'avg_overall': [0.3, 0.4, 0.5, 0.6],
    'news_count': [3, 5, 7, 10],
    'positive_ratio': [0.3, 0.5, 0.6, 0.7, 0.8],
}

SELL_GRID = {
    'avg_sentiment': [-0.05, -0.1, -0.15, -0.2, -0.25, -0.3],
    'avg_overall': [0.3, 0.25, 0.2, 0.15, 0.1],
    'news_count': [3, 5, 7, 10],
    'negative_ratio': [0.3, 0.5, 0.6, 0.7, 0.8],
}


# ─── 1단계: 전체 날짜별 종목 통계 추출 ──────────────────────────

def extract_all_stock_stats(db: NewsDatabase, start_date: str, end_date: str) -> Dict[str, List[Dict]]:
    """날짜별 모든 종목의 뉴스 통계를 추출. {date: [stock_stat, ...]}"""
    trading_days = get_trading_days(db, start_date, end_date)
    print(f"📊 {len(trading_days)}개 거래일에서 종목 통계 추출 중...")

    daily_stats = {}
    for date in trading_days:
        stats = analyze_stocks_for_date(db, date)
        daily_stats[date] = stats
    
    total_stocks = sum(len(v) for v in daily_stats.values())
    print(f"   총 {total_stocks}건 종목-날짜 조합 추출 완료")
    return daily_stats


def analyze_stocks_for_date(db: NewsDatabase, target_date: str) -> List[Dict]:
    """특정 날짜의 모든 종목 통계 (필터링 없이)"""
    start = f"{target_date}T00:00:00"
    end = f"{target_date}T23:59:59.999999"
    today_news = db.get_news_by_date_range(start, end)

    if not today_news:
        return []

    stock_analysis = defaultdict(lambda: {
        'sentiment_scores': [], 'overall_scores': [],
        'positive_count': 0, 'negative_count': 0, 'news_count': 0,
    })

    for news in today_news:
        related_stocks = news.get('related_stocks', '')
        if not related_stocks:
            continue
        stocks = [s.strip() for s in related_stocks.split(',') if s.strip()]
        sentiment = news.get('sentiment_score')
        overall = news.get('overall_score')

        for code in stocks:
            if not (len(code) == 6 and code.isdigit()):
                continue
            sa = stock_analysis[code]
            sa['news_count'] += 1
            if sentiment is not None:
                sa['sentiment_scores'].append(sentiment)
                if sentiment > 0:
                    sa['positive_count'] += 1
                elif sentiment < 0:
                    sa['negative_count'] += 1
            if overall is not None:
                sa['overall_scores'].append(overall)

    results = []
    for code, data in stock_analysis.items():
        n = data['news_count']
        if n == 0:
            continue
        avg_sent = sum(data['sentiment_scores']) / len(data['sentiment_scores']) if data['sentiment_scores'] else 0.0
        avg_overall = sum(data['overall_scores']) / len(data['overall_scores']) if data['overall_scores'] else 0.0
        pos_ratio = data['positive_count'] / n if n > 0 else 0.0
        neg_ratio = data['negative_count'] / n if n > 0 else 0.0

        results.append({
            'stock_code': code,
            'news_count': n,
            'avg_sentiment': avg_sent,
            'avg_overall': avg_overall,
            'positive_count': data['positive_count'],
            'negative_count': data['negative_count'],
            'positive_ratio': pos_ratio,
            'negative_ratio': neg_ratio,
        })
    return results


def get_trading_days(db: NewsDatabase, start_date: str, end_date: str) -> List[str]:
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATE(published_at) as d, COUNT(*) as cnt
        FROM news
        WHERE DATE(published_at) >= ? AND DATE(published_at) <= ?
          AND related_stocks IS NOT NULL AND related_stocks != ''
        GROUP BY d HAVING cnt >= 10
        ORDER BY d
    """, (start_date, end_date))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


# ─── 2단계: 주가 일괄 크롤링 & 캐시 ────────────────────────────

def collect_all_prices(daily_stats: Dict[str, List[Dict]], cache_path: str) -> Dict[str, any]:
    """모든 종목의 주가를 크롤링하여 캐시. 이미 캐시가 있으면 로드."""
    if os.path.exists(cache_path):
        print(f"💾 주가 캐시 로드: {cache_path}")
        with open(cache_path, 'rb') as f:
            return pickle.load(f)

    # 빈출 종목만 크롤링 (상위 300개 제한 — 메모리/시간 관리)
    from collections import Counter
    code_freq = Counter()
    for date, stocks in daily_stats.items():
        for s in stocks:
            code_freq[s['stock_code']] += 1
    
    MAX_STOCKS = 300
    all_codes = {code for code, _ in code_freq.most_common(MAX_STOCKS)}

    print(f"📈 {len(all_codes)}개 종목 주가 크롤링 중 (전체 {len(code_freq)}개 중 상위 빈출, 캐시 없음)...")
    fetcher = PriceFetcher()
    price_cache = {}
    
    for i, code in enumerate(sorted(all_codes)):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"   [{i+1}/{len(all_codes)}] {code}...")
        try:
            time.sleep(0.15)
            df = fetcher.get_daily_price(code, pages=3)  # ~30일치
            price_cache[code] = df
        except Exception as e:
            logger.warning(f"주가 조회 실패: {code} - {e}")
            price_cache[code] = None

    # 캐시 저장
    with open(cache_path, 'wb') as f:
        pickle.dump(price_cache, f)
    print(f"   캐시 저장: {cache_path}")
    return price_cache


def get_returns(price_cache: Dict, stock_code: str, signal_date: str) -> Dict[int, Optional[float]]:
    """캐시된 주가에서 수익률 계산"""
    df = price_cache.get(stock_code)
    if df is None or df.empty:
        return {d: None for d in HOLDING_DAYS}

    df = df.copy()
    df['날짜'] = df['날짜'].dt.normalize()
    df = df.sort_values('날짜').reset_index(drop=True)
    signal_dt = datetime.strptime(signal_date, '%Y-%m-%d')

    future_days = df[df['날짜'] > signal_dt]
    if future_days.empty:
        return {d: None for d in HOLDING_DAYS}

    entry_price = future_days.iloc[0]['시가']
    if entry_price is None or entry_price <= 0:
        return {d: None for d in HOLDING_DAYS}

    results = {}
    for hd in HOLDING_DAYS:
        if hd <= len(future_days):
            exit_price = future_days.iloc[hd - 1]['종가']
            results[hd] = (exit_price - entry_price) / entry_price if exit_price and exit_price > 0 else None
        else:
            results[hd] = None
    return results


# ─── 3단계: 수익률 매트릭스 사전계산 ───────────────────────────

def precompute_returns(daily_stats: Dict, price_cache: Dict) -> Dict[Tuple[str, str], Dict[int, Optional[float]]]:
    """(date, stock_code) → {hd: return} 매핑을 사전계산"""
    print("📐 수익률 사전계산 중...")
    returns_map = {}
    total = sum(len(stocks) for stocks in daily_stats.values())
    done = 0
    
    for date, stocks in daily_stats.items():
        for s in stocks:
            code = s['stock_code']
            returns_map[(date, code)] = get_returns(price_cache, code, date)
            done += 1
            if done % 500 == 0:
                print(f"   [{done}/{total}]")
    
    print(f"   {len(returns_map)}건 완료")
    return returns_map


# ─── 4단계: Grid Search ────────────────────────────────────────

def grid_search_buy(daily_stats: Dict, returns_map: Dict, benchmark_returns: Dict[int, float]):
    """BUY 임계값 grid search"""
    print("\n🔍 BUY 임계값 Grid Search...")
    
    combos = list(product(
        BUY_GRID['avg_sentiment'],
        BUY_GRID['avg_overall'],
        BUY_GRID['news_count'],
        BUY_GRID['positive_ratio'],
    ))
    print(f"   {len(combos)}개 조합 테스트")

    results = []
    for sent_th, overall_th, count_th, ratio_th in combos:
        # 이 조합으로 선택되는 종목들
        selected = []
        for date, stocks in daily_stats.items():
            for s in stocks:
                if (s['avg_sentiment'] > sent_th
                    and s['avg_overall'] > overall_th
                    and s['news_count'] >= count_th
                    and s['positive_ratio'] >= ratio_th
                    and s['positive_count'] > s['negative_count']):
                    ret = returns_map.get((date, s['stock_code']))
                    if ret:
                        selected.append(ret)

        if len(selected) < 10:  # 최소 샘플 수
            continue

        # 보유기간별 통계
        stats = {}
        best_excess = -999
        for hd in HOLDING_DAYS:
            rets = [r[hd] for r in selected if r.get(hd) is not None]
            if not rets:
                continue
            avg_ret = sum(rets) / len(rets)
            hit_rate = sum(1 for r in rets if r > 0) / len(rets)
            excess = avg_ret - benchmark_returns.get(hd, 0)
            stats[hd] = {
                'n': len(rets), 'avg': avg_ret, 'hit_rate': hit_rate, 'excess': excess
            }
            if excess > best_excess:
                best_excess = excess

        if stats:
            results.append({
                'sentiment': sent_th, 'overall': overall_th,
                'count': count_th, 'ratio': ratio_th,
                'stats': stats, 'best_excess': best_excess,
                'n': len(selected),
            })

    return results


def grid_search_sell(daily_stats: Dict, returns_map: Dict, benchmark_returns: Dict[int, float]):
    """SELL 임계값 grid search"""
    print("\n🔍 SELL 임계값 Grid Search...")
    
    combos = list(product(
        SELL_GRID['avg_sentiment'],
        SELL_GRID['avg_overall'],
        SELL_GRID['news_count'],
        SELL_GRID['negative_ratio'],
    ))
    print(f"   {len(combos)}개 조합 테스트")

    results = []
    for sent_th, overall_th, count_th, neg_ratio_th in combos:
        selected = []
        for date, stocks in daily_stats.items():
            for s in stocks:
                if (s['avg_sentiment'] < sent_th
                    and s['avg_overall'] < overall_th
                    and s['news_count'] >= count_th
                    and s['negative_ratio'] >= neg_ratio_th
                    and s['negative_count'] > s['positive_count']):
                    ret = returns_map.get((date, s['stock_code']))
                    if ret:
                        selected.append(ret)

        if len(selected) < 5:
            continue

        stats = {}
        best_excess = -999
        for hd in HOLDING_DAYS:
            rets = [r[hd] for r in selected if r.get(hd) is not None]
            if not rets:
                continue
            avg_ret = sum(rets) / len(rets)
            hit_rate = sum(1 for r in rets if r < 0) / len(rets)  # SELL은 하락이 적중
            # SELL 초과수익 = 벤치마크 수익 - SELL 종목 수익 (하락할수록 좋음)
            excess = benchmark_returns.get(hd, 0) - avg_ret
            stats[hd] = {
                'n': len(rets), 'avg': avg_ret, 'hit_rate': hit_rate, 'excess': excess
            }
            if excess > best_excess:
                best_excess = excess

        if stats:
            results.append({
                'sentiment': sent_th, 'overall': overall_th,
                'count': count_th, 'neg_ratio': neg_ratio_th,
                'stats': stats, 'best_excess': best_excess,
                'n': len(selected),
            })

    return results


def calc_benchmark(daily_stats: Dict, returns_map: Dict) -> Dict[int, float]:
    """벤치마크: 뉴스가 있는 모든 종목의 평균 수익률"""
    all_rets = {hd: [] for hd in HOLDING_DAYS}
    for date, stocks in daily_stats.items():
        for s in stocks:
            ret = returns_map.get((date, s['stock_code']))
            if ret:
                for hd in HOLDING_DAYS:
                    if ret.get(hd) is not None:
                        all_rets[hd].append(ret[hd])
    
    benchmark = {}
    for hd in HOLDING_DAYS:
        if all_rets[hd]:
            benchmark[hd] = sum(all_rets[hd]) / len(all_rets[hd])
        else:
            benchmark[hd] = 0.0
    return benchmark


# ─── 5단계: 결과 출력 ──────────────────────────────────────────

def print_top_results(results: List[Dict], signal_type: str, benchmark: Dict, top_n: int = 10):
    """상위 결과 출력"""
    # 각 보유기간별로 최적 조합 출력
    for hd in HOLDING_DAYS:
        # 해당 보유기간 excess 기준 정렬
        valid = [r for r in results if hd in r['stats']]
        valid.sort(key=lambda x: x['stats'][hd]['excess'], reverse=True)

        if not valid:
            continue

        print(f"\n{'='*70}")
        if signal_type == 'BUY':
            print(f"  📈 BUY 최적 임계값 TOP {min(top_n, len(valid))} — {hd}일 보유")
        else:
            print(f"  📉 SELL 최적 임계값 TOP {min(top_n, len(valid))} — {hd}일 보유")
        print(f"  벤치마크 {hd}일 평균: {benchmark[hd]*100:+.2f}%")
        print(f"{'='*70}")

        for i, r in enumerate(valid[:top_n]):
            s = r['stats'][hd]
            if signal_type == 'BUY':
                print(f"  #{i+1}: sentiment>{r['sentiment']:.2f}, overall>{r['overall']:.1f}, "
                      f"count>={r['count']}, pos_ratio>={r['ratio']:.1f}")
            else:
                print(f"  #{i+1}: sentiment<{r['sentiment']:.2f}, overall<{r['overall']:.2f}, "
                      f"count>={r['count']}, neg_ratio>={r['neg_ratio']:.1f}")
            print(f"      {hd}일 적중률 {s['hit_rate']*100:.1f}%, "
                  f"평균 {s['avg']*100:+.2f}%, "
                  f"초과수익 {s['excess']*100:+.2f}%p "
                  f"(n={s['n']})")


def print_summary_table(results: List[Dict], signal_type: str, benchmark: Dict):
    """전 보유기간에 걸쳐 안정적으로 좋은 조합 찾기"""
    # 모든 보유기간의 초과수익 합계 기준
    scored = []
    for r in results:
        total_excess = 0
        valid_periods = 0
        for hd in HOLDING_DAYS:
            if hd in r['stats']:
                total_excess += r['stats'][hd]['excess']
                valid_periods += 1
        if valid_periods >= 3:  # 최소 3개 보유기간 데이터
            scored.append((total_excess / valid_periods, r))
    
    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"\n{'='*70}")
    print(f"  🏆 {signal_type} 종합 최적 (전 보유기간 평균 초과수익 기준) TOP 10")
    print(f"{'='*70}")

    for i, (avg_excess, r) in enumerate(scored[:10]):
        if signal_type == 'BUY':
            print(f"\n  #{i+1}: sentiment>{r['sentiment']:.2f}, overall>{r['overall']:.1f}, "
                  f"count>={r['count']}, pos_ratio>={r['ratio']:.1f}")
        else:
            print(f"\n  #{i+1}: sentiment<{r['sentiment']:.2f}, overall<{r['overall']:.2f}, "
                  f"count>={r['count']}, neg_ratio>={r['neg_ratio']:.1f}")
        
        for hd in HOLDING_DAYS:
            if hd in r['stats']:
                s = r['stats'][hd]
                print(f"      {hd:2d}일: 적중률 {s['hit_rate']*100:5.1f}%  "
                      f"평균 {s['avg']*100:+6.2f}%  "
                      f"초과 {s['excess']*100:+6.2f}%p  (n={s['n']})")


# ─── 메인 ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='NewsQuant 임계값 최적화')
    parser.add_argument('--start', type=str, default='2025-12-12')
    parser.add_argument('--end', type=str, default='2026-02-06')
    parser.add_argument('--db', type=str, default=str(PROJECT_ROOT / 'news_data.db'))
    parser.add_argument('--no-cache', action='store_true', help='주가 캐시 무시')
    parser.add_argument('--top', type=int, default=10)
    args = parser.parse_args()

    cache_path = str(PROJECT_ROOT / 'scripts' / 'price_cache.pkl')
    if args.no_cache and os.path.exists(cache_path):
        os.remove(cache_path)

    print(f"🚀 NewsQuant 임계값 최적화")
    print(f"   기간: {args.start} ~ {args.end}")
    print(f"   보유 기간: {HOLDING_DAYS}일\n")

    # 1) 종목 통계 추출
    db = NewsDatabase(args.db)
    daily_stats = extract_all_stock_stats(db, args.start, args.end)

    # 검증용: 마지막 max(HOLDING_DAYS)일 제외
    all_dates = sorted(daily_stats.keys())
    max_hold = max(HOLDING_DAYS)
    if len(all_dates) > max_hold:
        cutoff_dates = set(all_dates[-max_hold:])
        signal_stats = {d: v for d, v in daily_stats.items() if d not in cutoff_dates}
    else:
        signal_stats = daily_stats
    print(f"   시그널 검증 대상: {len(signal_stats)}일 (마지막 {max_hold}일 제외)")

    # 2) 주가 크롤링 (전체 daily_stats 기준 — 수익률 계산에 필요)
    price_cache = collect_all_prices(daily_stats, cache_path)

    # 3) 수익률 사전계산
    returns_map = precompute_returns(signal_stats, price_cache)

    # 4) 벤치마크
    benchmark = calc_benchmark(signal_stats, returns_map)
    print(f"\n⚖️  벤치마크 (전체 뉴스 종목 평균):")
    for hd in HOLDING_DAYS:
        print(f"   {hd}일: {benchmark[hd]*100:+.3f}%")

    # 5) Grid Search
    buy_results = grid_search_buy(signal_stats, returns_map, benchmark)
    sell_results = grid_search_sell(signal_stats, returns_map, benchmark)

    # 6) 결과 출력
    print_summary_table(buy_results, 'BUY', benchmark)
    print_summary_table(sell_results, 'SELL', benchmark)

    # 보유기간별 TOP도 출력
    for hd in [5, 7, 10]:  # 가장 유의미한 기간만
        print_top_results(buy_results, 'BUY', benchmark, args.top)
        print_top_results(sell_results, 'SELL', benchmark, args.top)
        break  # 한번만 (전체 기간 다 출력됨)

    print(f"\n✅ 완료! Grid search: BUY {len(buy_results)}개, SELL {len(sell_results)}개 유효 조합")


if __name__ == '__main__':
    main()
