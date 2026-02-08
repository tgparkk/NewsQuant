"""
매매 판단 분석 모듈
뉴스 기반 종목 분석 및 매매 신호 생성

개선사항 (2026-02-08):
- 주가 선반영 체크: 뉴스 발행 전 이미 주가가 움직였으면 감성 가중치 하향
- 뉴스 볼륨 역발상 시그널: 관심도 급증 = 과열 경고
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
from .database import NewsDatabase
from .price_fetcher import PriceFetcher
import logging

logger = logging.getLogger(__name__)


class TradingAnalyzer:
    """매매 판단 분석기"""
    
    def __init__(self, db_path: str = "news_data.db"):
        """
        Args:
            db_path: 데이터베이스 파일 경로
        """
        self.db = NewsDatabase(db_path)
        self.price_fetcher = PriceFetcher()
    
    def analyze_today_stocks(self) -> Dict:
        """
        오늘자 뉴스 기반 종목 분석
        
        Returns:
            분석 결과 딕셔너리
        """
        # 오늘 날짜 범위 설정
        today = datetime.now()
        start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # 오늘자 뉴스 조회
        today_news = self.db.get_news_by_date_range(
            start_date.isoformat(),
            end_date.isoformat()
        )
        
        if len(today_news) == 0:
            return {
                'total_news': 0,
                'stocks_mentioned': 0,
                'buy_candidates': [],
                'sell_candidates': [],
                'watch_candidates': [],
                'stock_stats': []
            }
        
        # 종목별 뉴스 수집 및 분석
        stock_analysis = defaultdict(lambda: {
            'news_list': [],
            'sentiment_scores': [],
            'overall_scores': [],
            'positive_count': 0,
            'negative_count': 0,
            'neutral_count': 0,
            'high_score_count': 0
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
            
            # 주가 선반영 체크: 이미 주가가 움직였으면 감성 가중치 조정
            adjusted_sentiment = self._adjust_for_price_reaction(
                avg_sentiment, stock_code
            )
            
            # 뉴스 볼륨 시그널: 관심도 급증 = 과열 경고
            volume_adj = self._volume_signal(stock_code, news_count)
            
            # 종합 점수 계산 (조정된 감성 35% + 종합 점수 35% + 뉴스 개수 15% + 볼륨 시그널 15%)
            news_score = min(news_count / 10.0, 1.0)
            composite_score = (
                adjusted_sentiment * 0.35
                + avg_overall * 0.35
                + news_score * 0.15
                + volume_adj * 0.15
            )
            
            stock_stats.append({
                'stock_code': stock_code,
                'news_count': news_count,
                'avg_sentiment': avg_sentiment,
                'adjusted_sentiment': adjusted_sentiment,
                'avg_overall': avg_overall,
                'composite_score': composite_score,
                'volume_signal': volume_adj,
                'positive_count': data['positive_count'],
                'negative_count': data['negative_count'],
                'neutral_count': data['neutral_count'],
                'high_score_count': data['high_score_count'],
                'positive_ratio': data['positive_count'] / news_count if news_count > 0 else 0.0
            })
        
        # 종합 점수 기준으로 정렬
        stock_stats.sort(key=lambda x: x['composite_score'], reverse=True)
        
        # 매수 후보 종목 (최적화된 임계값: 2026-02-08 grid search 결과)
        # 이전: sent>0.05, overall>0.3, count>=3, ratio>=0.3
        # 최적: sent>0.30, overall>0.3, count>=10, ratio>=0.8 → 5일 적중률 84.6%, 초과수익 +3.75%p
        buy_candidates = [
            s for s in stock_stats
            if s['avg_sentiment'] > 0.30
            and s['avg_overall'] > 0.3
            and s['news_count'] >= 10
            and s['positive_ratio'] >= 0.8
            and s['positive_count'] > s['negative_count']
        ]
        buy_candidates.sort(key=lambda x: x['composite_score'], reverse=True)
        
        # 매도 후보 종목 (최적화된 임계값)
        # 이전: sent<-0.05, overall<0.3, count>=3
        # 최적: sent<-0.25, overall<0.25, count>=7, neg_ratio>=0.7 → 10일 적중률 75%, 초과수익 +8.74%p
        negative_ratio = lambda s: s['negative_count'] / s['news_count'] if s['news_count'] > 0 else 0
        sell_candidates = [
            s for s in stock_stats
            if s['avg_sentiment'] < -0.25
            and s['avg_overall'] < 0.25
            and s['news_count'] >= 7
            and negative_ratio(s) >= 0.7
        ]
        sell_candidates.sort(key=lambda x: x['composite_score'])
        
        # 주의 관찰 종목
        watch_candidates = [
            s for s in stock_stats
            if s['news_count'] >= 5
            and -0.1 <= s['avg_sentiment'] <= 0.1
            and s['positive_count'] > 0 and s['negative_count'] > 0
        ]
        watch_candidates.sort(key=lambda x: x['news_count'], reverse=True)
        
        return {
            'total_news': len(today_news),
            'stocks_mentioned': len(stock_stats),
            'buy_candidates': buy_candidates,
            'sell_candidates': sell_candidates,
            'watch_candidates': watch_candidates,
            'stock_stats': stock_stats,
            'analysis_date': today.strftime('%Y-%m-%d')
        }
    
    def get_stock_signal(self, stock_code: str, days: int = 1) -> Dict:
        """
        특정 종목의 매매 신호 분석
        
        Args:
            stock_code: 종목 코드 (6자리)
            days: 분석할 일수 (기본값: 1, 오늘만)
        
        Returns:
            매매 신호 딕셔너리
        """
        # 날짜 범위 설정
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # 해당 종목의 뉴스 조회
        news_list = self.db.get_news_by_stock(stock_code, limit=100)
        
        # 날짜 필터링
        filtered_news = [
            n for n in news_list
            if start_date.isoformat() <= n.get('published_at', '') <= end_date.isoformat()
        ]
        
        if len(filtered_news) == 0:
            return {
                'stock_code': stock_code,
                'signal': 'hold',
                'confidence': 0.0,
                'news_count': 0,
                'avg_sentiment': 0.0,
                'avg_overall': 0.0,
                'reason': '뉴스 없음'
            }
        
        # 통계 계산
        sentiment_scores = [n.get('sentiment_score', 0.0) for n in filtered_news if n.get('sentiment_score') is not None]
        overall_scores = [n.get('overall_score', 0.0) for n in filtered_news if n.get('overall_score') is not None]
        
        avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0.0
        avg_overall = sum(overall_scores) / len(overall_scores) if overall_scores else 0.0
        
        positive_count = sum(1 for s in sentiment_scores if s > 0)
        negative_count = sum(1 for s in sentiment_scores if s < 0)
        
        # 매매 신호 결정
        signal = 'hold'
        confidence = 0.0
        reason = ''
        
        # 매수 신호 조건 (최적화된 임계값)
        pos_ratio = positive_count / len(filtered_news) if filtered_news else 0
        neg_ratio = negative_count / len(filtered_news) if filtered_news else 0
        
        if (avg_sentiment > 0.30 and avg_overall > 0.3 and 
            len(filtered_news) >= 10 and pos_ratio >= 0.8):
            signal = 'buy'
            confidence = min(0.5 + (avg_sentiment * 0.3) + (avg_overall * 0.2), 1.0)
            reason = f'강한 긍정 (감성: {avg_sentiment:.3f}, 종합: {avg_overall:.3f}, 긍정률: {pos_ratio:.0%}, 뉴스: {len(filtered_news)}건)'
        
        # 매도 신호 조건 (최적화된 임계값)
        elif (avg_sentiment < -0.25 and avg_overall < 0.25 and 
              len(filtered_news) >= 7 and neg_ratio >= 0.7):
            signal = 'sell'
            confidence = min(0.5 + (abs(avg_sentiment) * 0.3) + ((1 - avg_overall) * 0.2), 1.0)
            reason = f'강한 부정 (감성: {avg_sentiment:.3f}, 종합: {avg_overall:.3f}, 부정률: {neg_ratio:.0%}, 뉴스: {len(filtered_news)}건)'
        
        # 보류 신호
        else:
            signal = 'hold'
            confidence = 0.3
            reason = '신호 혼재 또는 뉴스 부족'
        
        return {
            'stock_code': stock_code,
            'signal': signal,
            'confidence': round(confidence, 3),
            'news_count': len(filtered_news),
            'avg_sentiment': round(avg_sentiment, 3),
            'avg_overall': round(avg_overall, 3),
            'positive_count': positive_count,
            'negative_count': negative_count,
            'reason': reason,
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def get_stock_analysis(self, stock_code: str, days: int = 7) -> Dict:
        """
        종목별 상세 분석
        
        Args:
            stock_code: 종목 코드 (6자리)
            days: 분석할 일수 (기본값: 7)
        
        Returns:
            상세 분석 결과
        """
        # 날짜 범위 설정
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # 뉴스 조회
        news_list = self.db.get_news_by_stock(stock_code, limit=200)
        
        # 날짜 필터링
        filtered_news = [
            n for n in news_list
            if start_date.isoformat() <= n.get('published_at', '') <= end_date.isoformat()
        ]
        
        if len(filtered_news) == 0:
            return {
                'stock_code': stock_code,
                'analysis_period_days': days,
                'total_news': 0,
                'statistics': {},
                'recent_news': [],
                'signal': 'hold'
            }
        
        # 통계 계산
        sentiment_scores = [n.get('sentiment_score', 0.0) for n in filtered_news if n.get('sentiment_score') is not None]
        overall_scores = [n.get('overall_score', 0.0) for n in filtered_news if n.get('overall_score') is not None]
        
        positive_count = sum(1 for s in sentiment_scores if s > 0)
        negative_count = sum(1 for s in sentiment_scores if s < 0)
        neutral_count = sum(1 for s in sentiment_scores if s == 0)
        
        avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0.0
        avg_overall = sum(overall_scores) / len(overall_scores) if overall_scores else 0.0
        
        # 최신 뉴스 (최근 5개)
        recent_news = sorted(filtered_news, key=lambda x: x.get('published_at', ''), reverse=True)[:5]
        
        # 매매 신호
        signal_info = self.get_stock_signal(stock_code, days=1)
        
        return {
            'stock_code': stock_code,
            'analysis_period_days': days,
            'total_news': len(filtered_news),
            'statistics': {
                'avg_sentiment': round(avg_sentiment, 3),
                'avg_overall': round(avg_overall, 3),
                'positive_count': positive_count,
                'negative_count': negative_count,
                'neutral_count': neutral_count,
                'positive_ratio': round(positive_count / len(filtered_news), 3) if filtered_news else 0.0
            },
            'recent_news': recent_news,
            'signal': signal_info['signal'],
            'signal_confidence': signal_info['confidence'],
            'signal_reason': signal_info['reason'],
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

    # ─── 주가 선반영 체크 ─────────────────────────────────────

    def _adjust_for_price_reaction(self, sentiment: float, stock_code: str, days: int = 3) -> float:
        """
        뉴스 발행 전 주가 움직임으로 이미 반영 여부 판단.
        긍정 뉴스인데 이미 올랐으면 가중치 하향, 빠졌는데 긍정이면 상향.

        Args:
            sentiment: 원본 감성 점수
            stock_code: 종목코드
            days: 주가 확인 기간

        Returns:
            조정된 감성 점수
        """
        if sentiment == 0:
            return 0.0

        try:
            df = self.price_fetcher.get_daily_price(stock_code, pages=1)
            if df is None or len(df) < 2:
                return sentiment

            # 최근 종가 vs N일 전 종가
            df = df.sort_values('날짜', ascending=False)
            current = df.iloc[0]['종가']
            prior = df.iloc[min(days, len(df) - 1)]['종가']

            if prior is None or prior <= 0 or current is None:
                return sentiment

            prior_return = (current - prior) / prior

            # 긍정 뉴스인데 이미 3% 이상 올랐으면 → 이미 반영됨, 가중치 하향
            if sentiment > 0 and prior_return > 0.03:
                return sentiment * 0.3
            # 부정 뉴스인데 이미 3% 이상 빠졌으면 → 이미 반영됨
            if sentiment < 0 and prior_return < -0.03:
                return sentiment * 0.3
            # 긍정 뉴스인데 주가가 빠졌으면 → 아직 미반영, 기회
            if sentiment > 0 and prior_return < -0.01:
                return sentiment * 1.5
            # 부정 뉴스인데 주가가 올랐으면 → 아직 미반영, 위험
            if sentiment < 0 and prior_return > 0.01:
                return sentiment * 1.5

            return sentiment

        except Exception as e:
            logger.debug(f"주가 선반영 체크 실패 {stock_code}: {e}")
            return sentiment

    # ─── 뉴스 볼륨 역발상 시그널 ─────────────────────────────

    # 종목별 일평균 뉴스 수 캐시 (세션 내 재사용)
    _volume_cache: Dict = {}
    _volume_cache_loaded: bool = False

    def _load_volume_cache(self):
        """전 종목의 일별 뉴스 수를 한 번에 로드 (LIKE 반복 대신 한 번 풀스캔)"""
        if self._volume_cache_loaded:
            return

        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DATE(published_at) as d, related_stocks
                FROM news
                WHERE related_stocks IS NOT NULL AND related_stocks != ''
                ORDER BY d DESC
            """)
            rows = cursor.fetchall()
            conn.close()

            # 종목별 날짜별 카운트 집계
            stock_daily: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for d, rs in rows:
                for code in rs.split(','):
                    code = code.strip()
                    if len(code) == 6 and code.isdigit():
                        stock_daily[code][d] += 1

            # 종목별 일평균 (최근 20일, 오늘 제외)
            for code, daily in stock_daily.items():
                dates = sorted(daily.keys(), reverse=True)
                if len(dates) <= 1:
                    self._volume_cache[code] = 0
                else:
                    counts = [daily[d] for d in dates[1:21]]  # 오늘 제외, 최근 20일
                    self._volume_cache[code] = sum(counts) / len(counts) if counts else 0

            self._volume_cache_loaded = True
        except Exception as e:
            logger.warning(f"볼륨 캐시 로드 실패: {e}")
            self._volume_cache_loaded = True  # 실패해도 재시도 방지

    def _volume_signal(self, stock_code: str, today_count: int) -> float:
        """
        뉴스 볼륨 급증을 과열 시그널로 활용 (역발상).

        - 평소 대비 3배 이상 → 과열 경고 (-0.5)
        - 평소 대비 2배 이상 → 약한 경고 (-0.2)
        - 평소보다 적음 → 약한 긍정 (+0.1)

        Returns:
            볼륨 시그널 점수 (-0.5 ~ +0.1)
        """
        self._load_volume_cache()

        avg_count = self._volume_cache.get(stock_code, 0)
        if avg_count <= 0:
            return 0.0

        ratio = today_count / avg_count

        if ratio >= 3.0:
            return -0.5
        elif ratio >= 2.0:
            return -0.2
        elif ratio < 0.5:
            return 0.1

        return 0.0


