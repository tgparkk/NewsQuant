"""
매매 판단 분석 모듈
뉴스 기반 종목 분석 및 매매 신호 생성
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
from .database import NewsDatabase
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
        
        # 매수 후보 종목
        buy_candidates = [
            s for s in stock_stats
            if s['avg_sentiment'] > 0.05
            and s['avg_overall'] > 0.3
            and s['news_count'] >= 3
            and s['positive_ratio'] >= 0.3
            and s['positive_count'] > s['negative_count']
        ]
        buy_candidates.sort(key=lambda x: x['composite_score'], reverse=True)
        
        # 매도 후보 종목
        sell_candidates = [
            s for s in stock_stats
            if s['avg_sentiment'] < -0.05
            and s['avg_overall'] < 0.3
            and s['news_count'] >= 3
            and s['negative_count'] > s['positive_count']
        ]
        sell_candidates.sort(key=lambda x: x['composite_score'])
        
        # 주의 관찰 종목
        watch_candidates = [
            s for s in stock_stats
            if s['news_count'] >= 3
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
        
        # 매수 신호 조건
        if (avg_sentiment > 0.1 and avg_overall > 0.4 and 
            positive_count > negative_count and len(filtered_news) >= 2):
            signal = 'buy'
            confidence = min(0.5 + (avg_sentiment * 0.3) + (avg_overall * 0.2), 1.0)
            reason = f'긍정적 뉴스 우세 (평균 감성: {avg_sentiment:.3f}, 종합: {avg_overall:.3f})'
        
        # 매도 신호 조건
        elif (avg_sentiment < -0.1 and avg_overall < 0.3 and 
              negative_count > positive_count and len(filtered_news) >= 2):
            signal = 'sell'
            confidence = min(0.5 + (abs(avg_sentiment) * 0.3) + ((1 - avg_overall) * 0.2), 1.0)
            reason = f'부정적 뉴스 우세 (평균 감성: {avg_sentiment:.3f}, 종합: {avg_overall:.3f})'
        
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




