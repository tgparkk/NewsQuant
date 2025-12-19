"""
매매 판단 API 사용 예제
다른 프로그램에서 NewsQuant API를 사용하여 매매 판단에 활용하는 방법
"""

import requests
import json
from typing import List, Dict, Optional


class TradingAPIClient:
    """매매 판단 API 클라이언트"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        """
        Args:
            base_url: API 서버 주소
        """
        self.base_url = base_url.rstrip('/')
    
    def get_today_analysis(self) -> Dict:
        """오늘자 종목 분석 결과 조회"""
        url = f"{self.base_url}/api/trading/analysis/today"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    
    def get_stock_signal(self, stock_code: str, days: int = 1) -> Dict:
        """
        특정 종목의 매매 신호 조회
        
        Args:
            stock_code: 종목 코드 (6자리)
            days: 분석할 일수
        
        Returns:
            {
                "success": True,
                "data": {
                    "stock_code": "005930",
                    "signal": "buy",  # "buy", "sell", "hold"
                    "confidence": 0.75,
                    "news_count": 5,
                    "avg_sentiment": 0.123,
                    "avg_overall": 0.456,
                    "reason": "긍정적 뉴스 우세..."
                }
            }
        """
        url = f"{self.base_url}/api/trading/signal/{stock_code}"
        params = {"days": days}
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    def get_stock_signals_batch(self, stock_codes: List[str], days: int = 1) -> Dict:
        """
        여러 종목의 매매 신호를 한 번에 조회
        
        Args:
            stock_codes: 종목 코드 리스트
            days: 분석할 일수
        
        Returns:
            {
                "success": True,
                "days": 1,
                "count": 2,
                "results": {
                    "005930": {
                        "stock_code": "005930",
                        "signal": "buy",
                        "confidence": 0.75,
                        ...
                    },
                    "000660": {
                        ...
                    }
                }
            }
        """
        url = f"{self.base_url}/api/trading/signals/batch"
        payload = {
            "stock_codes": stock_codes,
            "days": days
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    
    def get_stock_analysis(self, stock_code: str, days: int = 7) -> Dict:
        """
        종목별 상세 분석 조회
        
        Args:
            stock_code: 종목 코드
            days: 분석할 일수
        
        Returns:
            상세 분석 결과 (통계, 최신 뉴스, 매매 신호 등)
        """
        url = f"{self.base_url}/api/trading/stock/{stock_code}/analysis"
        params = {"days": days}
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    def get_buy_candidates(self, min_confidence: float = 0.5, limit: int = 20) -> Dict:
        """
        매수 후보 종목 조회
        
        Args:
            min_confidence: 최소 신뢰도 (0.0 ~ 1.0)
            limit: 조회 개수
        """
        url = f"{self.base_url}/api/trading/buy-candidates"
        params = {
            "min_confidence": min_confidence,
            "limit": limit
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    def get_sell_candidates(self, min_confidence: float = 0.5, limit: int = 20) -> Dict:
        """
        매도 후보 종목 조회
        
        Args:
            min_confidence: 최소 신뢰도 (0.0 ~ 1.0)
            limit: 조회 개수
        """
        url = f"{self.base_url}/api/trading/sell-candidates"
        params = {
            "min_confidence": min_confidence,
            "limit": limit
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()


def example_1_check_single_stock():
    """예제 1: 단일 종목 매매 신호 확인"""
    print("=" * 70)
    print("예제 1: 단일 종목 매매 신호 확인")
    print("=" * 70)
    
    client = TradingAPIClient()
    
    # 삼성전자(005930) 매매 신호 확인
    result = client.get_stock_signal("005930", days=1)
    
    if result['success']:
        data = result['data']
        print(f"종목 코드: {data['stock_code']}")
        print(f"매매 신호: {data['signal']}")
        print(f"신뢰도: {data['confidence']:.2%}")
        print(f"뉴스 개수: {data['news_count']}개")
        print(f"평균 감성: {data['avg_sentiment']:.3f}")
        print(f"이유: {data['reason']}")
    print()


def example_2_check_multiple_stocks():
    """예제 2: 여러 종목의 매매 신호를 한 번에 확인"""
    print("=" * 70)
    print("예제 2: 여러 종목의 매매 신호를 한 번에 확인")
    print("=" * 70)
    
    client = TradingAPIClient()
    
    # 관심 종목 리스트
    stock_codes = ["005930", "000660", "035420", "051910"]
    
    result = client.get_stock_signals_batch(stock_codes, days=1)
    
    if result['success']:
        print(f"조회된 종목 수: {result['count']}개\n")
        
        for stock_code, signal_data in result['results'].items():
            if 'error' not in signal_data:
                print(f"[{stock_code}] {signal_data['signal'].upper()}")
                print(f"  신뢰도: {signal_data['confidence']:.2%}")
                print(f"  뉴스: {signal_data['news_count']}개")
                print(f"  이유: {signal_data['reason']}")
                print()
    print()


def example_3_get_buy_candidates():
    """예제 3: 매수 후보 종목 조회"""
    print("=" * 70)
    print("예제 3: 매수 후보 종목 조회")
    print("=" * 70)
    
    client = TradingAPIClient()
    
    # 신뢰도 0.6 이상인 매수 후보 조회
    result = client.get_buy_candidates(min_confidence=0.6, limit=10)
    
    if result['success']:
        print(f"매수 후보: {result['count']}개\n")
        
        for i, candidate in enumerate(result['data'], 1):
            print(f"{i}. {candidate['stock_code']}")
            print(f"   신뢰도: {candidate['confidence']:.2%}")
            print(f"   뉴스 수: {candidate['news_count']}개")
            print(f"   평균 감성: {candidate['avg_sentiment']:.3f}")
            print(f"   긍정/부정: {candidate['positive_count']}/{candidate['negative_count']}")
            print()
    print()


def example_4_get_detailed_analysis():
    """예제 4: 종목별 상세 분석"""
    print("=" * 70)
    print("예제 4: 종목별 상세 분석")
    print("=" * 70)
    
    client = TradingAPIClient()
    
    # 삼성전자 상세 분석 (최근 7일)
    result = client.get_stock_analysis("005930", days=7)
    
    if result['success']:
        data = result['data']
        print(f"종목 코드: {data['stock_code']}")
        print(f"분석 기간: 최근 {data['analysis_period_days']}일")
        print(f"총 뉴스: {data['total_news']}개")
        print()
        
        stats = data['statistics']
        print("통계:")
        print(f"  평균 감성: {stats['avg_sentiment']:.3f}")
        print(f"  평균 종합 점수: {stats['avg_overall']:.3f}")
        print(f"  긍정: {stats['positive_count']}개")
        print(f"  부정: {stats['negative_count']}개")
        print(f"  긍정 비율: {stats['positive_ratio']:.1%}")
        print()
        
        print(f"매매 신호: {data['signal'].upper()}")
        print(f"신뢰도: {data['signal_confidence']:.2%}")
        print(f"이유: {data['signal_reason']}")
        print()
        
        print("최신 뉴스 (최근 3개):")
        for i, news in enumerate(data['recent_news'][:3], 1):
            print(f"  {i}. {news.get('title', 'N/A')[:60]}")
            print(f"     감성: {news.get('sentiment_score', 0.0):.3f}")
    print()


def example_5_integration_with_trading_system():
    """예제 5: 실제 매매 시스템과 통합 예제"""
    print("=" * 70)
    print("예제 5: 실제 매매 시스템과 통합 예제")
    print("=" * 70)
    
    client = TradingAPIClient()
    
    # 1. 관심 종목 리스트 (예: 보유 종목 또는 관심 종목)
    watchlist = ["005930", "000660", "035420", "051910", "012450"]
    
    # 2. 각 종목의 매매 신호 확인
    signals = client.get_stock_signals_batch(watchlist, days=1)
    
    if signals['success']:
        buy_list = []
        sell_list = []
        hold_list = []
        
        for stock_code, signal_data in signals['results'].items():
            if 'error' not in signal_data:
                signal = signal_data['signal']
                confidence = signal_data['confidence']
                
                # 신뢰도가 0.6 이상인 경우만 매매 신호로 간주
                if confidence >= 0.6:
                    if signal == 'buy':
                        buy_list.append({
                            'stock_code': stock_code,
                            'confidence': confidence,
                            'reason': signal_data['reason']
                        })
                    elif signal == 'sell':
                        sell_list.append({
                            'stock_code': stock_code,
                            'confidence': confidence,
                            'reason': signal_data['reason']
                        })
                else:
                    hold_list.append(stock_code)
        
        # 3. 매매 신호 출력
        print("매수 신호 종목:")
        if buy_list:
            for item in sorted(buy_list, key=lambda x: x['confidence'], reverse=True):
                print(f"  [{item['stock_code']}] 신뢰도: {item['confidence']:.2%}")
                print(f"    이유: {item['reason']}")
        else:
            print("  없음")
        print()
        
        print("매도 신호 종목:")
        if sell_list:
            for item in sorted(sell_list, key=lambda x: x['confidence'], reverse=True):
                print(f"  [{item['stock_code']}] 신뢰도: {item['confidence']:.2%}")
                print(f"    이유: {item['reason']}")
        else:
            print("  없음")
        print()
        
        print(f"보류 종목: {len(hold_list)}개")
    print()


if __name__ == "__main__":
    print("\n매매 판단 API 사용 예제\n")
    
    try:
        # 예제 실행
        example_1_check_single_stock()
        example_2_check_multiple_stocks()
        example_3_get_buy_candidates()
        example_4_get_detailed_analysis()
        example_5_integration_with_trading_system()
        
        print("=" * 70)
        print("모든 예제 실행 완료!")
        print("=" * 70)
        
    except requests.exceptions.ConnectionError:
        print("오류: API 서버에 연결할 수 없습니다.")
        print("API 서버가 실행 중인지 확인하세요: python -m news_scraper.api.server")
    except Exception as e:
        print(f"오류 발생: {e}")
