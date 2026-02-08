# 매매 판단 API 사용 가이드

NewsQuant API를 사용하여 다른 프로그램에서 매매 판단에 활용하는 방법을 안내합니다.

## 목차
1. [API 서버 시작](#api-서버-시작)
2. [API 엔드포인트](#api-엔드포인트)
3. [사용 예제](#사용-예제)
4. [실전 활용 방법](#실전-활용-방법)

## API 서버 시작

### 방법 1: 배치 파일 사용
```bash
start_api_only.bat
```

### 방법 2: Python 직접 실행
```bash
python -m news_scraper.api.server
```

기본 주소: `http://127.0.0.1:8000`
API 문서: `http://127.0.0.1:8000/docs`

## API 엔드포인트

### 1. 오늘자 종목 분석 결과 조회
**GET** `/api/trading/analysis/today`

오늘자 뉴스를 기반으로 한 전체 종목 분석 결과를 반환합니다.

**응답 예시:**
```json
{
  "success": true,
  "data": {
    "total_news": 509,
    "stocks_mentioned": 82,
    "buy_candidates": [
      {
        "stock_code": "051900",
        "news_count": 95,
        "avg_sentiment": 0.105,
        "avg_overall": 0.326,
        "composite_score": 0.373,
        "positive_count": 32,
        "negative_count": 11
      }
    ],
    "sell_candidates": [],
    "watch_candidates": [...],
    "stock_stats": [...]
  }
}
```

### 2. 특정 종목의 매매 신호 조회
**GET** `/api/trading/signal/{stock_code}?days=1`

특정 종목의 매매 신호를 반환합니다.

**파라미터:**
- `stock_code`: 종목 코드 (6자리, 예: 005930)
- `days`: 분석할 일수 (기본값: 1, 오늘만)

**응답 예시:**
```json
{
  "success": true,
  "data": {
    "stock_code": "005930",
    "signal": "buy",
    "confidence": 0.75,
    "news_count": 5,
    "avg_sentiment": 0.123,
    "avg_overall": 0.456,
    "positive_count": 3,
    "negative_count": 1,
    "reason": "긍정적 뉴스 우세 (평균 감성: 0.123, 종합: 0.456)"
  }
}
```

**신호 종류:**
- `buy`: 매수 신호 (긍정적 뉴스 우세)
- `sell`: 매도 신호 (부정적 뉴스 우세)
- `hold`: 보류 (신호 혼재 또는 뉴스 부족)

### 3. 여러 종목의 매매 신호 배치 조회
**POST** `/api/trading/signals/batch`

여러 종목의 매매 신호를 한 번에 조회합니다.

**요청 본문:**
```json
{
  "stock_codes": ["005930", "000660", "035420"],
  "days": 1
}
```

**응답 예시:**
```json
{
  "success": true,
  "days": 1,
  "count": 3,
  "results": {
    "005930": {
      "stock_code": "005930",
      "signal": "buy",
      "confidence": 0.75,
      ...
    },
    "000660": {
      "stock_code": "000660",
      "signal": "hold",
      "confidence": 0.3,
      ...
    }
  }
}
```

### 4. 종목별 상세 분석
**GET** `/api/trading/stock/{stock_code}/analysis?days=7`

종목별 상세 분석 결과를 반환합니다.

**파라미터:**
- `stock_code`: 종목 코드 (6자리)
- `days`: 분석할 일수 (기본값: 7)

**응답 예시:**
```json
{
  "success": true,
  "data": {
    "stock_code": "005930",
    "analysis_period_days": 7,
    "total_news": 15,
    "statistics": {
      "avg_sentiment": 0.123,
      "avg_overall": 0.456,
      "positive_count": 8,
      "negative_count": 3,
      "neutral_count": 4,
      "positive_ratio": 0.533
    },
    "recent_news": [...],
    "signal": "buy",
    "signal_confidence": 0.75,
    "signal_reason": "긍정적 뉴스 우세..."
  }
}
```

### 5. 매수 후보 종목 조회
**GET** `/api/trading/buy-candidates?min_confidence=0.5&limit=20`

매수 후보 종목 목록을 반환합니다.

**파라미터:**
- `min_confidence`: 최소 신뢰도 (0.0 ~ 1.0, 기본값: 0.5)
- `limit`: 조회 개수 (1-100, 기본값: 20)

### 6. 매도 후보 종목 조회
**GET** `/api/trading/sell-candidates?min_confidence=0.5&limit=20`

매도 후보 종목 목록을 반환합니다.

**파라미터:**
- `min_confidence`: 최소 신뢰도 (0.0 ~ 1.0, 기본값: 0.5)
- `limit`: 조회 개수 (1-100, 기본값: 20)

## 사용 예제

### Python 예제

```python
import requests

# API 서버 주소
BASE_URL = "http://127.0.0.1:8000"

# 1. 특정 종목의 매매 신호 확인
def check_stock_signal(stock_code):
    url = f"{BASE_URL}/api/trading/signal/{stock_code}"
    response = requests.get(url, params={"days": 1})
    data = response.json()
    
    if data['success']:
        signal_data = data['data']
        print(f"종목: {signal_data['stock_code']}")
        print(f"신호: {signal_data['signal']}")
        print(f"신뢰도: {signal_data['confidence']:.2%}")
        return signal_data['signal']
    return None

# 2. 여러 종목의 신호 확인
def check_multiple_stocks(stock_codes):
    url = f"{BASE_URL}/api/trading/signals/batch"
    payload = {
        "stock_codes": stock_codes,
        "days": 1
    }
    response = requests.post(url, json=payload)
    data = response.json()
    
    if data['success']:
        buy_signals = []
        sell_signals = []
        
        for code, signal_data in data['results'].items():
            if signal_data['confidence'] >= 0.6:
                if signal_data['signal'] == 'buy':
                    buy_signals.append(code)
                elif signal_data['signal'] == 'sell':
                    sell_signals.append(code)
        
        return buy_signals, sell_signals
    return [], []

# 3. 매수 후보 조회
def get_buy_candidates():
    url = f"{BASE_URL}/api/trading/buy-candidates"
    response = requests.get(url, params={"min_confidence": 0.6, "limit": 10})
    data = response.json()
    
    if data['success']:
        return [item['stock_code'] for item in data['data']]
    return []

# 사용 예시
if __name__ == "__main__":
    # 단일 종목 확인
    signal = check_stock_signal("005930")
    
    # 여러 종목 확인
    watchlist = ["005930", "000660", "035420"]
    buy_list, sell_list = check_multiple_stocks(watchlist)
    print(f"매수 신호: {buy_list}")
    print(f"매도 신호: {sell_list}")
    
    # 매수 후보 조회
    candidates = get_buy_candidates()
    print(f"매수 후보: {candidates}")
```

### JavaScript/Node.js 예제

```javascript
const axios = require('axios');

const BASE_URL = 'http://127.0.0.1:8000';

// 특정 종목의 매매 신호 확인
async function checkStockSignal(stockCode) {
    try {
        const response = await axios.get(`${BASE_URL}/api/trading/signal/${stockCode}`, {
            params: { days: 1 }
        });
        
        if (response.data.success) {
            const data = response.data.data;
            console.log(`종목: ${data.stock_code}`);
            console.log(`신호: ${data.signal}`);
            console.log(`신뢰도: ${(data.confidence * 100).toFixed(2)}%`);
            return data.signal;
        }
    } catch (error) {
        console.error('오류:', error.message);
    }
    return null;
}

// 여러 종목의 신호 확인
async function checkMultipleStocks(stockCodes) {
    try {
        const response = await axios.post(`${BASE_URL}/api/trading/signals/batch`, {
            stock_codes: stockCodes,
            days: 1
        });
        
        if (response.data.success) {
            const buySignals = [];
            const sellSignals = [];
            
            for (const [code, signalData] of Object.entries(response.data.results)) {
                if (signalData.confidence >= 0.6) {
                    if (signalData.signal === 'buy') {
                        buySignals.push(code);
                    } else if (signalData.signal === 'sell') {
                        sellSignals.push(code);
                    }
                }
            }
            
            return { buySignals, sellSignals };
        }
    } catch (error) {
        console.error('오류:', error.message);
    }
    return { buySignals: [], sellSignals: [] };
}

// 사용 예시
(async () => {
    const signal = await checkStockSignal('005930');
    
    const watchlist = ['005930', '000660', '035420'];
    const { buySignals, sellSignals } = await checkMultipleStocks(watchlist);
    console.log('매수 신호:', buySignals);
    console.log('매도 신호:', sellSignals);
})();
```

## 실전 활용 방법

### 1. 자동 매매 시스템과 통합

```python
import requests
import time

def trading_decision_loop():
    """매매 결정 루프"""
    BASE_URL = "http://127.0.0.1:8000"
    watchlist = ["005930", "000660", "035420"]  # 관심 종목
    
    while True:
        try:
            # 매매 신호 확인
            url = f"{BASE_URL}/api/trading/signals/batch"
            response = requests.post(url, json={
                "stock_codes": watchlist,
                "days": 1
            })
            
            data = response.json()
            if data['success']:
                for code, signal_data in data['results'].items():
                    if signal_data['confidence'] >= 0.7:
                        signal = signal_data['signal']
                        if signal == 'buy':
                            # 매수 로직 실행
                            print(f"[매수] {code} - 신뢰도: {signal_data['confidence']:.2%}")
                        elif signal == 'sell':
                            # 매도 로직 실행
                            print(f"[매도] {code} - 신뢰도: {signal_data['confidence']:.2%}")
            
            # 1분마다 확인
            time.sleep(60)
            
        except Exception as e:
            print(f"오류: {e}")
            time.sleep(10)
```

### 2. 포트폴리오 모니터링

```python
def monitor_portfolio(portfolio):
    """보유 종목 모니터링"""
    BASE_URL = "http://127.0.0.1:8000"
    
    url = f"{BASE_URL}/api/trading/signals/batch"
    response = requests.post(url, json={
        "stock_codes": portfolio,
        "days": 1
    })
    
    data = response.json()
    if data['success']:
        alerts = []
        for code, signal_data in data['results'].items():
            if signal_data['signal'] == 'sell' and signal_data['confidence'] >= 0.6:
                alerts.append({
                    'stock_code': code,
                    'signal': 'sell',
                    'confidence': signal_data['confidence'],
                    'reason': signal_data['reason']
                })
        return alerts
    return []
```

### 3. 매수 후보 스크리닝

```python
def screen_buy_candidates(min_confidence=0.6):
    """매수 후보 스크리닝"""
    BASE_URL = "http://127.0.0.1:8000"
    
    url = f"{BASE_URL}/api/trading/buy-candidates"
    response = requests.get(url, params={
        "min_confidence": min_confidence,
        "limit": 50
    })
    
    data = response.json()
    if data['success']:
        candidates = []
        for item in data['data']:
            candidates.append({
                'stock_code': item['stock_code'],
                'confidence': item['confidence'],
                'news_count': item['news_count'],
                'avg_sentiment': item['avg_sentiment']
            })
        return sorted(candidates, key=lambda x: x['confidence'], reverse=True)
    return []
```

## 주의사항

1. **신뢰도 기준**: 신뢰도가 0.6 이상인 신호만 매매 결정에 활용하는 것을 권장합니다.
2. **추가 분석 필요**: 뉴스 기반 분석만으로는 부족하므로, 기술적 분석과 기본적 분석을 병행하세요.
3. **리스크 관리**: 항상 손절매와 분산 투자를 고려하세요.
4. **API 서버 상태**: API 서버가 정상 작동 중인지 주기적으로 확인하세요 (`/api/health`).

## API 문서

더 자세한 API 문서는 다음 주소에서 확인할 수 있습니다:
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`






