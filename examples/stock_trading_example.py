"""
실전 주식 거래 시스템 예제
1차 필터: 주식 데이터 → 2차 필터: 뉴스 데이터
"""

import requests
from typing import List, Dict, Optional
import time

API_BASE = "http://127.0.0.1:8000"


class StockTradingSystem:
    """주식 거래 시스템 (1차 필터 + 2차 뉴스 분석)"""
    
    def __init__(self):
        self.api_base = API_BASE
    
    def filter_by_stock_data(self) -> List[str]:
        """
        1차 필터: 주식 데이터로 종목 필터링
        
        실제로는 주식 API나 데이터베이스에서 조건에 맞는 종목을 조회합니다.
        예: "시가총액 1조 이상, PER 10 이하, 최근 3일 상승률 5% 이상"
        
        여기서는 예시로 하드코딩합니다.
        """
        # 실제 구현 시:
        # - 키움증권 API, 이베스트투자증권 API 등 사용
        # - 또는 자체 데이터베이스에서 조건 검색
        
        filtered_stocks = [
            "005930",  # 삼성전자
            "000660",  # SK하이닉스
            "035420",  # NAVER
            "035720",  # 카카오
            "051910",  # LG화학
        ]
        
        return filtered_stocks
    
    def get_news_for_stocks(self, stock_codes: List[str], 
                           limit_per_stock: int = 10,
                           min_score: Optional[float] = None) -> Optional[Dict]:
        """
        2차 필터: 여러 종목의 뉴스를 한 번에 조회 (배치)
        
        Args:
            stock_codes: 종목 코드 리스트
            limit_per_stock: 종목당 조회 개수
            min_score: 최소 종합 점수
        
        Returns:
            API 응답 데이터 또는 None
        """
        try:
            response = requests.post(
                f"{self.api_base}/api/news/stocks/batch",
                json={
                    "stock_codes": stock_codes,
                    "limit_per_stock": limit_per_stock,
                    "min_score": min_score
                },
                timeout=5
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ 뉴스 조회 실패: {e}")
            return None
    
    def analyze_news_sentiment(self, news_list: List[Dict]) -> Dict:
        """
        뉴스 리스트를 분석하여 감성 정보 추출
        
        Returns:
            {
                "avg_sentiment": 평균 감성 점수,
                "avg_overall": 평균 종합 점수,
                "positive_count": 긍정적 뉴스 개수,
                "negative_count": 부정적 뉴스 개수,
                "latest_sentiment": 최신 뉴스 감성 점수
            }
        """
        if not news_list:
            return {
                "avg_sentiment": 0.0,
                "avg_overall": 0.0,
                "positive_count": 0,
                "negative_count": 0,
                "latest_sentiment": 0.0
            }
        
        sentiments = [n.get("sentiment_score", 0) for n in news_list if n.get("sentiment_score")]
        overalls = [n.get("overall_score", 0) for n in news_list if n.get("overall_score")]
        
        positive = sum(1 for s in sentiments if s > 0.3)
        negative = sum(1 for s in sentiments if s < -0.3)
        
        return {
            "avg_sentiment": sum(sentiments) / len(sentiments) if sentiments else 0.0,
            "avg_overall": sum(overalls) / len(overalls) if overalls else 0.0,
            "positive_count": positive,
            "negative_count": negative,
            "latest_sentiment": sentiments[0] if sentiments else 0.0
        }
    
    def make_trading_decision(self, stock_code: str, news_data: Dict) -> str:
        """
        뉴스 분석 후 매매 결정
        
        Returns:
            "buy", "sell", "hold"
        """
        news_list = news_data.get("news", [])
        if not news_list:
            return "hold"
        
        analysis = self.analyze_news_sentiment(news_list)
        
        # 매매 결정 로직
        # 1. 최신 뉴스가 매우 긍정적이고 중요한 경우
        if analysis["latest_sentiment"] > 0.6 and analysis["avg_overall"] > 0.7:
            return "buy"
        
        # 2. 최신 뉴스가 매우 부정적인 경우
        elif analysis["latest_sentiment"] < -0.6:
            return "sell"
        
        # 3. 평균적으로 긍정적인 경우
        elif analysis["avg_sentiment"] > 0.4 and analysis["positive_count"] >= 3:
            return "buy"
        
        # 4. 평균적으로 부정적인 경우
        elif analysis["avg_sentiment"] < -0.4 and analysis["negative_count"] >= 3:
            return "sell"
        
        # 5. 기타: 보류
        else:
            return "hold"
    
    def run(self):
        """메인 실행 로직"""
        print("=" * 70)
        print("주식 거래 시스템: 1차 필터(주식 데이터) → 2차 필터(뉴스 데이터)")
        print("=" * 70)
        
        # 1차 필터링: 주식 데이터로 종목 선택
        print("\n[1단계] 주식 데이터로 종목 필터링...")
        filtered_stocks = self.filter_by_stock_data()
        print(f"✅ 선택된 종목: {len(filtered_stocks)}개")
        for i, code in enumerate(filtered_stocks, 1):
            print(f"   {i}. {code}")
        
        # 2차 필터링: 뉴스 데이터 조회 (배치)
        print(f"\n[2단계] {len(filtered_stocks)}개 종목의 뉴스 데이터 조회 (배치)...")
        start_time = time.time()
        
        news_data = self.get_news_for_stocks(
            stock_codes=filtered_stocks,
            limit_per_stock=10,
            min_score=0.5  # 중요한 뉴스만
        )
        
        elapsed_time = (time.time() - start_time) * 1000  # 밀리초
        
        if not news_data:
            print("❌ 뉴스 데이터를 가져올 수 없습니다.")
            return
        
        print(f"✅ 조회 완료! (소요 시간: {elapsed_time:.0f}ms)")
        print(f"   총 뉴스 개수: {news_data.get('total_news_count', 0)}개")
        
        # 각 종목별 분석
        print("\n[3단계] 종목별 뉴스 분석 및 매매 결정...")
        print("-" * 70)
        
        decisions = {}
        
        for stock_code in filtered_stocks:
            result = news_data.get("results", {}).get(stock_code, {})
            news_list = result.get("news", [])
            count = result.get("count", 0)
            
            # 분석
            analysis = self.analyze_news_sentiment(news_list)
            decision = self.make_trading_decision(stock_code, result)
            decisions[stock_code] = decision
            
            # 출력
            print(f"\n📊 {stock_code}: {count}개 뉴스")
            
            if count > 0:
                latest = news_list[0]
                print(f"   최신: {latest.get('title', 'N/A')[:60]}...")
                print(f"   감성 분석:")
                print(f"     - 평균 감성: {analysis['avg_sentiment']:+.2f}")
                print(f"     - 최신 감성: {analysis['latest_sentiment']:+.2f}")
                print(f"     - 긍정적: {analysis['positive_count']}개 / 부정적: {analysis['negative_count']}개")
                print(f"     - 평균 종합 점수: {analysis['avg_overall']:.2f}")
            
            # 결정 표시
            decision_icon = {
                "buy": "✅ 매수",
                "sell": "❌ 매도",
                "hold": "⏸ 보류"
            }
            print(f"   결정: {decision_icon.get(decision, decision)}")
        
        # 최종 결과 요약
        print("\n" + "=" * 70)
        print("[최종 매매 결정 요약]")
        print("=" * 70)
        
        buy_stocks = [code for code, d in decisions.items() if d == "buy"]
        sell_stocks = [code for code, d in decisions.items() if d == "sell"]
        hold_stocks = [code for code, d in decisions.items() if d == "hold"]
        
        if buy_stocks:
            print(f"\n✅ 매수 고려 ({len(buy_stocks)}개):")
            for code in buy_stocks:
                result = news_data.get("results", {}).get(code, {})
                count = result.get("count", 0)
                print(f"   • {code} ({count}개 뉴스)")
        
        if sell_stocks:
            print(f"\n❌ 매도 고려 ({len(sell_stocks)}개):")
            for code in sell_stocks:
                result = news_data.get("results", {}).get(code, {})
                count = result.get("count", 0)
                print(f"   • {code} ({count}개 뉴스)")
        
        if hold_stocks:
            print(f"\n⏸ 보류 ({len(hold_stocks)}개):")
            for code in hold_stocks:
                result = news_data.get("results", {}).get(code, {})
                count = result.get("count", 0)
                print(f"   • {code} ({count}개 뉴스)")
        
        print("\n" + "=" * 70)
        print("분석 완료!")
        print("=" * 70)


# 간단한 사용 예제
def simple_example():
    """간단한 사용 예제"""
    print("\n" + "=" * 70)
    print("간단한 사용 예제")
    print("=" * 70)
    
    # 1차 필터링: 주식 프로그램에서 선택한 종목들
    filtered_stocks = ["005930", "000660", "035420"]
    
    # 2차 필터링: 배치 API로 뉴스 조회
    response = requests.post(
        f"{API_BASE}/api/news/stocks/batch",
        json={
            "stock_codes": filtered_stocks,
            "limit_per_stock": 5,
            "min_score": 0.6
        },
        timeout=5
    )
    
    if response.status_code == 200:
        data = response.json()
        
        print(f"\n조회된 종목: {len(data['stock_codes'])}개")
        print(f"총 뉴스: {data['total_news_count']}개\n")
        
        for stock_code, result in data["results"].items():
            count = result["count"]
            print(f"{stock_code}: {count}개 뉴스")
            
            if count > 0:
                latest = result["news"][0]
                sentiment = latest.get("sentiment_score", 0)
                print(f"  최신: {latest['title'][:50]}...")
                print(f"  감성: {sentiment:+.2f}")
    else:
        print(f"오류: {response.status_code}")


if __name__ == "__main__":
    # 간단한 예제 실행
    simple_example()
    
    print("\n" * 2)
    
    # 전체 시스템 실행
    system = StockTradingSystem()
    system.run()
