"""
NewsQuant 시그널 사후검증 스크립트
===================================
과거 기간 동안 NewsQuant의 buy/sell 시그널이 실제 주가와 일치했는지 검증합니다.

사용법:
    python scripts/validate_signals.py                    # 최근 20거래일
    python scripts/validate_signals.py --days 30          # 최근 30거래일
    python scripts/validate_signals.py --start 2026-01-06 --end 2026-02-06
"""

import sys
import os
import argparse
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from news_scraper.database import NewsDatabase
from news_scraper.price_fetcher import PriceFetcher

logging.basicConfig(level=logging.WARNING, format='%(message)s')
logger = logging.getLogger(__name__)

# ─── 볼륨 캐시 (전역, 한 번만 로드) ───────────────────────────────

_volume_avg_cache: Dict[str, float] = {}
_volume_loaded = False


def _load_volume_cache(db: NewsDatabase):
    """전 종목 일평균 뉴스 수를 한 번에 계산"""
    global _volume_avg_cache, _volume_loaded
    if _volume_loaded:
        return
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATE(published_at) as d, related_stocks
        FROM news
        WHERE related_stocks IS NOT NULL AND related_stocks != ''
    """)
    rows = cursor.fetchall()
    conn.close()

    stock_daily: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d, rs in rows:
        for code in rs.split(','):
            code = code.strip()
            if len(code) == 6 and code.isdigit():
                stock_daily[code][d] += 1

    for code, daily in stock_daily.items():
        dates = sorted(daily.keys(), reverse=True)
        if len(dates) <= 1:
            _volume_avg_cache[code] = 0
        else:
            counts = [daily[d] for d in dates[1:21]]
            _volume_avg_cache[code] = sum(counts) / len(counts) if counts else 0

    _volume_loaded = True


def _get_volume_signal(stock_code: str, today_count: int) -> float:
    """볼륨 역발상 시그널 (-0.5 ~ +0.1)"""
    avg = _volume_avg_cache.get(stock_code, 0)
    if avg <= 0:
        return 0.0
    ratio = today_count / avg
    if ratio >= 3.0:
        return -0.5
    elif ratio >= 2.0:
        return -0.2
    elif ratio < 0.5:
        return 0.1
    return 0.0


# ─── 주가 선반영 캐시 (price_cache 재사용) ─────────────────────────

def _adjust_for_price_reaction(sentiment: float, stock_code: str,
                                signal_date: str, price_cache: Dict) -> float:
    """뉴스 발행 전 주가가 이미 움직였으면 감성 가중치 조정"""
    if sentiment == 0 or stock_code not in price_cache:
        return sentiment

    df = price_cache[stock_code]
    if df is None or df.empty or len(df) < 2:
        return sentiment

    try:
        import pandas as pd
        df = df.copy()
        df['날짜'] = df['날짜'].dt.normalize()
        df = df.sort_values('날짜')
        signal_dt = pd.Timestamp(signal_date)

        # signal_date 이전 데이터만
        prior = df[df['날짜'] <= signal_dt]
        if len(prior) < 2:
            return sentiment

        current = prior.iloc[-1]['종가']
        ref = prior.iloc[-min(4, len(prior))]['종가']  # 3일 전
        if ref is None or ref <= 0 or current is None:
            return sentiment

        prior_return = (current - ref) / ref

        if sentiment > 0 and prior_return > 0.03:
            return sentiment * 0.3
        if sentiment < 0 and prior_return < -0.03:
            return sentiment * 0.3
        if sentiment > 0 and prior_return < -0.01:
            return sentiment * 1.5
        if sentiment < 0 and prior_return > 0.01:
            return sentiment * 1.5
    except Exception:
        pass

    return sentiment


# ─── 1단계: 과거 날짜별 시그널 재현 ────────────────────────────────

def analyze_stocks_for_date(db: NewsDatabase, target_date: str,
                            price_cache: Dict = None) -> Dict:
    """
    특정 날짜의 뉴스를 기반으로 buy/sell 시그널을 생성합니다.
    TradingAnalyzer.analyze_today_stocks()와 동일한 로직, 날짜만 파라미터화.

    Args:
        db: NewsDatabase 인스턴스
        target_date: 분석 대상 날짜 (YYYY-MM-DD)

    Returns:
        {'buy_candidates': [...], 'sell_candidates': [...], 'all_stocks': [...]}
    """
    start = f"{target_date}T00:00:00"
    end = f"{target_date}T23:59:59.999999"

    today_news = db.get_news_by_date_range(start, end)

    if not today_news:
        return {'buy_candidates': [], 'sell_candidates': [], 'all_stocks': []}

    # 종목별 뉴스 집계
    stock_analysis = defaultdict(lambda: {
        'sentiment_scores': [],
        'overall_scores': [],
        'positive_count': 0,
        'negative_count': 0,
        'news_count': 0,
    })

    for news in today_news:
        related_stocks = news.get('related_stocks', '')
        if not related_stocks:
            continue

        stocks = [s.strip() for s in related_stocks.split(',') if s.strip()]
        sentiment = news.get('sentiment_score')
        overall = news.get('overall_score')

        for code in stocks:
            # 유효한 6자리 종목코드만
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

    # 종목별 통계
    all_stocks = []
    for code, data in stock_analysis.items():
        n = data['news_count']
        if n == 0:
            continue

        avg_sent = (sum(data['sentiment_scores']) / len(data['sentiment_scores'])
                    if data['sentiment_scores'] else 0.0)
        avg_overall = (sum(data['overall_scores']) / len(data['overall_scores'])
                       if data['overall_scores'] else 0.0)

        # 볼륨 시그널
        vol_signal = _get_volume_signal(code, n)

        # 주가 선반영 체크 (price_cache가 있을 때만)
        adjusted_sent = avg_sent
        if price_cache is not None:
            adjusted_sent = _adjust_for_price_reaction(
                avg_sent, code, target_date, price_cache
            )

        news_score = min(n / 10.0, 1.0)
        composite = (adjusted_sent * 0.35 + avg_overall * 0.35
                     + news_score * 0.15 + vol_signal * 0.15)
        pos_ratio = data['positive_count'] / n if n > 0 else 0.0

        all_stocks.append({
            'stock_code': code,
            'news_count': n,
            'avg_sentiment': avg_sent,
            'adjusted_sentiment': adjusted_sent,
            'avg_overall': avg_overall,
            'composite_score': composite,
            'volume_signal': vol_signal,
            'positive_count': data['positive_count'],
            'negative_count': data['negative_count'],
            'positive_ratio': pos_ratio,
        })

    # buy/sell 조건 (최적화된 임계값 2026-02-08)
    buy_candidates = [
        s for s in all_stocks
        if s['avg_sentiment'] > 0.30
        and s['avg_overall'] > 0.3
        and s['news_count'] >= 10
        and s['positive_ratio'] >= 0.8
        and s['positive_count'] > s['negative_count']
    ]
    buy_candidates.sort(key=lambda x: x['composite_score'], reverse=True)

    neg_ratio = lambda s: s['negative_count'] / s['news_count'] if s['news_count'] > 0 else 0
    sell_candidates = [
        s for s in all_stocks
        if s['avg_sentiment'] < -0.25
        and s['avg_overall'] < 0.25
        and s['news_count'] >= 7
        and neg_ratio(s) >= 0.7
    ]
    sell_candidates.sort(key=lambda x: x['composite_score'])

    return {
        'buy_candidates': buy_candidates,
        'sell_candidates': sell_candidates,
        'all_stocks': all_stocks,
    }


# ─── 2단계: 시그널 이후 실제 수익률 조회 ──────────────────────────

def get_returns_after_signal(
    fetcher: PriceFetcher,
    stock_code: str,
    signal_date: str,
    holding_days: List[int] = [1, 3, 5],
    price_cache: Dict = None,
) -> Dict[int, Optional[float]]:
    """
    시그널 다음 거래일 시가 매수 → N일 후 종가 기준 수익률 계산.

    Args:
        fetcher: PriceFetcher 인스턴스
        stock_code: 종목코드
        signal_date: 시그널 발생 날짜 (YYYY-MM-DD)
        holding_days: 보유 기간 리스트
        price_cache: {stock_code: DataFrame} 캐시 (외부 공유)

    Returns:
        {1: 0.023, 3: -0.011, 5: 0.045} 또는 데이터 없으면 {1: None, ...}
    """
    if price_cache is None:
        price_cache = {}

    # 캐시에서 조회 또는 크롤링
    if stock_code not in price_cache:
        time.sleep(0.2)  # rate limit
        try:
            df = fetcher.get_daily_price(stock_code, pages=3)  # ~30일치
            price_cache[stock_code] = df
        except Exception as e:
            logger.warning(f"주가 조회 실패: {stock_code} - {e}")
            price_cache[stock_code] = None

    df = price_cache[stock_code]
    if df is None or df.empty:
        return {d: None for d in holding_days}

    # 날짜 정규화
    df = df.copy()
    df['날짜'] = df['날짜'].dt.normalize()
    df = df.sort_values('날짜').reset_index(drop=True)

    signal_dt = datetime.strptime(signal_date, '%Y-%m-%d')

    # 시그널 다음 거래일 찾기 (시가 매수)
    future_days = df[df['날짜'] > signal_dt]
    if future_days.empty:
        return {d: None for d in holding_days}

    entry_row = future_days.iloc[0]
    entry_price = entry_row['시가']

    if entry_price is None or entry_price <= 0:
        return {d: None for d in holding_days}

    # N거래일 후 종가 수익률
    results = {}
    for hd in holding_days:
        if hd <= len(future_days):
            exit_price = future_days.iloc[hd - 1]['종가']
            if exit_price and exit_price > 0:
                results[hd] = (exit_price - entry_price) / entry_price
            else:
                results[hd] = None
        else:
            results[hd] = None

    return results


# ─── 3단계: 전체 기간 루프 ─────────────────────────────────────

def get_trading_days(db: NewsDatabase, start_date: str, end_date: str) -> List[str]:
    """
    뉴스가 존재하는 거래일 목록을 반환합니다 (주말/공휴일 자동 제외).
    뉴스 3건 이상인 날만 유효 거래일로 취급합니다.
    """
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATE(published_at) as d, COUNT(*) as cnt
        FROM news
        WHERE DATE(published_at) >= ? AND DATE(published_at) <= ?
          AND related_stocks IS NOT NULL AND related_stocks != ''
        GROUP BY d
        HAVING cnt >= 10
        ORDER BY d
    """, (start_date, end_date))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


def run_validation(
    db_path: str,
    start_date: str,
    end_date: str,
    holding_days: List[int] = [1, 3, 5],
    top_n: int = 10,
) -> Dict:
    """
    전체 검증을 실행합니다.

    Args:
        db_path: news_data.db 경로
        start_date: 검증 시작 날짜
        end_date: 검증 종료 날짜
        holding_days: 보유 기간 리스트
        top_n: 날짜별 상위 N개 buy 종목만 검증 (크롤링 부하 관리)

    Returns:
        검증 결과 딕셔너리
    """
    db = NewsDatabase(db_path)
    fetcher = PriceFetcher()
    price_cache = {}

    # 볼륨 캐시 로드 (한 번)
    print("📦 볼륨 캐시 로드 중...")
    _load_volume_cache(db)
    print(f"   {len(_volume_avg_cache)}개 종목 볼륨 평균 로드 완료")

    trading_days = get_trading_days(db, start_date, end_date)
    # 마지막 N거래일은 holding_days 수익률 계산 불가 → 제외
    max_hold = max(holding_days)
    signal_days = trading_days[:-max_hold] if len(trading_days) > max_hold else trading_days

    print(f"\n📊 NewsQuant 시그널 검증 (v2: 키워드개선 + 볼륨시그널 + 선반영체크)")
    print(f"   기간: {start_date} ~ {end_date}")
    print(f"   거래일: {len(trading_days)}일 (시그널 검증: {len(signal_days)}일)")
    print(f"   보유 기간: {holding_days}일")
    print(f"   날짜별 상위 {top_n}개 종목 검증")
    print()

    buy_results = []
    sell_results = []
    no_signal_results = []

    for i, date in enumerate(signal_days):
        # price_cache를 전달하여 선반영 체크 활성화
        signals = analyze_stocks_for_date(db, date, price_cache=price_cache)
        buy_count = len(signals['buy_candidates'])
        sell_count = len(signals['sell_candidates'])

        # 진행률 표시
        print(f"\r   [{i+1}/{len(signal_days)}] {date}  BUY:{buy_count} SELL:{sell_count}", end='', flush=True)

        # BUY 시그널 상위 N개 검증
        for stock in signals['buy_candidates'][:top_n]:
            returns = get_returns_after_signal(
                fetcher, stock['stock_code'], date, holding_days, price_cache
            )
            buy_results.append({
                'date': date,
                'stock_code': stock['stock_code'],
                'composite_score': stock['composite_score'],
                'avg_sentiment': stock['avg_sentiment'],
                'news_count': stock['news_count'],
                'returns': returns,
            })

        # SELL 시그널 검증
        for stock in signals['sell_candidates'][:top_n]:
            returns = get_returns_after_signal(
                fetcher, stock['stock_code'], date, holding_days, price_cache
            )
            sell_results.append({
                'date': date,
                'stock_code': stock['stock_code'],
                'composite_score': stock['composite_score'],
                'avg_sentiment': stock['avg_sentiment'],
                'news_count': stock['news_count'],
                'returns': returns,
            })

        # 벤치마크: 시그널 없는 종목 중 랜덤 3개
        buy_codes = {s['stock_code'] for s in signals['buy_candidates']}
        sell_codes = {s['stock_code'] for s in signals['sell_candidates']}
        signal_codes = buy_codes | sell_codes

        neutral = [s for s in signals['all_stocks']
                   if s['stock_code'] not in signal_codes and s['news_count'] >= 2]

        import random
        sample = random.sample(neutral, min(3, len(neutral)))
        for stock in sample:
            returns = get_returns_after_signal(
                fetcher, stock['stock_code'], date, holding_days, price_cache
            )
            no_signal_results.append({
                'date': date,
                'stock_code': stock['stock_code'],
                'returns': returns,
            })

    print("\n")

    return {
        'buy_results': buy_results,
        'sell_results': sell_results,
        'no_signal_results': no_signal_results,
        'holding_days': holding_days,
        'start_date': start_date,
        'end_date': end_date,
        'trading_days': len(trading_days),
        'signal_days': len(signal_days),
    }


# ─── 4단계: 통계 출력 ──────────────────────────────────────────

def calc_stats(results: List[Dict], holding_days: List[int], signal_type: str) -> Dict:
    """수익률 통계 계산"""
    stats = {}
    for hd in holding_days:
        returns = [r['returns'][hd] for r in results if r['returns'].get(hd) is not None]
        if not returns:
            stats[hd] = {'count': 0, 'hit_rate': 0, 'avg_return': 0, 'median_return': 0}
            continue

        if signal_type == 'buy':
            hits = [r for r in returns if r > 0]
        else:  # sell → 하락해야 적중
            hits = [r for r in returns if r < 0]

        sorted_returns = sorted(returns)
        median = sorted_returns[len(sorted_returns) // 2]

        stats[hd] = {
            'count': len(returns),
            'hit_rate': len(hits) / len(returns) * 100,
            'avg_return': sum(returns) / len(returns) * 100,
            'median_return': median * 100,
            'max_return': max(returns) * 100,
            'min_return': min(returns) * 100,
        }
    return stats


def print_report(validation: Dict):
    """검증 결과 리포트 출력"""
    buy = validation['buy_results']
    sell = validation['sell_results']
    neutral = validation['no_signal_results']
    hds = validation['holding_days']

    print("=" * 70)
    print(f"  NewsQuant 시그널 검증 리포트")
    print(f"  기간: {validation['start_date']} ~ {validation['end_date']}")
    print(f"  거래일: {validation['trading_days']}일 | 검증일: {validation['signal_days']}일")
    print("=" * 70)

    # ── BUY 시그널 ──
    buy_stats = calc_stats(buy, hds, 'buy')
    print(f"\n📈 BUY 시그널  (총 {len(buy)}건)")
    print("-" * 50)
    for hd in hds:
        s = buy_stats[hd]
        if s['count'] == 0:
            print(f"  {hd}일 후: 데이터 없음")
            continue
        print(f"  {hd}일 후: 적중률 {s['hit_rate']:5.1f}%  "
              f"평균 {s['avg_return']:+6.2f}%  "
              f"중앙값 {s['median_return']:+6.2f}%  "
              f"(n={s['count']})")

    # ── SELL 시그널 ──
    sell_stats = calc_stats(sell, hds, 'sell')
    print(f"\n📉 SELL 시그널  (총 {len(sell)}건)")
    print("-" * 50)
    for hd in hds:
        s = sell_stats[hd]
        if s['count'] == 0:
            print(f"  {hd}일 후: 데이터 없음")
            continue
        print(f"  {hd}일 후: 적중률 {s['hit_rate']:5.1f}%  "
              f"평균 {s['avg_return']:+6.2f}%  "
              f"중앙값 {s['median_return']:+6.2f}%  "
              f"(n={s['count']})")

    # ── 벤치마크 ──
    neutral_stats = calc_stats(neutral, hds, 'buy')
    print(f"\n⚖️  벤치마크 (시그널 없는 종목)  (총 {len(neutral)}건)")
    print("-" * 50)
    for hd in hds:
        s = neutral_stats[hd]
        if s['count'] == 0:
            continue
        print(f"  {hd}일 후: 상승률 {s['hit_rate']:5.1f}%  "
              f"평균 {s['avg_return']:+6.2f}%  "
              f"중앙값 {s['median_return']:+6.2f}%  "
              f"(n={s['count']})")

    # ── BUY vs 벤치마크 초과수익 ──
    print(f"\n🎯 BUY 시그널 초과수익 (vs 벤치마크)")
    print("-" * 50)
    for hd in hds:
        bs = buy_stats[hd]
        ns = neutral_stats[hd]
        if bs['count'] == 0 or ns['count'] == 0:
            continue
        excess = bs['avg_return'] - ns['avg_return']
        print(f"  {hd}일 후: {excess:+6.2f}%p  "
              f"(BUY {bs['avg_return']:+.2f}% vs 벤치마크 {ns['avg_return']:+.2f}%)")

    # ── 점수 구간별 성과 ──
    if buy:
        print(f"\n📊 BUY 시그널 - composite_score 구간별 1일 수익률")
        print("-" * 50)

        scored = [(r['composite_score'], r['returns'].get(1))
                  for r in buy if r['returns'].get(1) is not None]
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            n = len(scored)
            top_20 = scored[:max(1, n // 5)]
            bottom_20 = scored[-max(1, n // 5):]

            top_returns = [r for _, r in top_20]
            bot_returns = [r for _, r in bottom_20]

            top_avg = sum(top_returns) / len(top_returns) * 100
            bot_avg = sum(bot_returns) / len(bot_returns) * 100
            top_hit = sum(1 for r in top_returns if r > 0) / len(top_returns) * 100
            bot_hit = sum(1 for r in bot_returns if r > 0) / len(bot_returns) * 100

            top_score_min = min(s for s, _ in top_20)
            bot_score_max = max(s for s, _ in bottom_20)

            print(f"  상위 20% (score >= {top_score_min:.3f}): "
                  f"적중률 {top_hit:.1f}%  평균 {top_avg:+.2f}%  (n={len(top_20)})")
            print(f"  하위 20% (score <= {bot_score_max:.3f}): "
                  f"적중률 {bot_hit:.1f}%  평균 {bot_avg:+.2f}%  (n={len(bottom_20)})")

    # ── 날짜별 요약 ──
    print(f"\n📅 날짜별 BUY 시그널 1일 적중률 (상위 5 / 하위 5)")
    print("-" * 50)

    daily = defaultdict(list)
    for r in buy:
        ret_1d = r['returns'].get(1)
        if ret_1d is not None:
            daily[r['date']].append(ret_1d)

    daily_stats = []
    for date, returns in daily.items():
        hit = sum(1 for r in returns if r > 0) / len(returns) * 100
        avg = sum(returns) / len(returns) * 100
        daily_stats.append((date, hit, avg, len(returns)))

    daily_stats.sort(key=lambda x: x[2], reverse=True)

    if daily_stats:
        print("  [Best]")
        for date, hit, avg, n in daily_stats[:5]:
            print(f"    {date}: 적중률 {hit:5.1f}%  평균 {avg:+6.2f}%  (n={n})")
        print("  [Worst]")
        for date, hit, avg, n in daily_stats[-5:]:
            print(f"    {date}: 적중률 {hit:5.1f}%  평균 {avg:+6.2f}%  (n={n})")

    print("\n" + "=" * 70)


# ─── 메인 ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='NewsQuant 시그널 사후검증')
    parser.add_argument('--days', type=int, default=20, help='최근 N거래일 검증 (기본: 20)')
    parser.add_argument('--start', type=str, help='시작 날짜 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='종료 날짜 (YYYY-MM-DD)')
    parser.add_argument('--db', type=str, default=str(PROJECT_ROOT / 'news_data.db'),
                        help='DB 경로')
    parser.add_argument('--top', type=int, default=10, help='날짜별 상위 N개 종목 (기본: 10)')
    parser.add_argument('--hold', type=str, default='1,3,5',
                        help='보유 기간 (콤마 구분, 기본: 1,3,5)')
    args = parser.parse_args()

    holding_days = [int(d) for d in args.hold.split(',')]

    if args.start and args.end:
        start_date = args.start
        end_date = args.end
    else:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=args.days + 15)).strftime('%Y-%m-%d')

    result = run_validation(
        db_path=args.db,
        start_date=start_date,
        end_date=end_date,
        holding_days=holding_days,
        top_n=args.top,
    )

    print_report(result)


if __name__ == '__main__':
    main()
