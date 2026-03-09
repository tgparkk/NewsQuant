# 시장 지수 예측 API 사용 가이드

다른 프로그램(RoboTrader 등)에서 KOSPI/KOSDAQ 방향 예측을 활용하는 방법입니다.

## 1. 서버 실행

```bash
# 전체 시스템 (수집 + API)
python main.py

# API만 실행
python run_api.py
```

서버 주소: `http://127.0.0.1:8000`

---

## 2. 핵심 API 엔드포인트

### 2-1. 시장 예측 (전체)

```
GET /api/market/predict?hours=24
```

**파라미터:**
| 이름 | 기본값 | 설명 |
|------|--------|------|
| hours | 24 | 분석할 뉴스 시간 범위 (1~168) |

**응답 예시:**
```json
{
  "success": true,
  "data": {
    "prediction": {
      "direction": "down",
      "strength": "moderate",
      "description": "소폭 하락 예상",
      "mixed_signals": true,
      "global_direction": "down",
      "domestic_direction": "neutral"
    },
    "confidence": 0.44,
    "combined_sentiment": -0.072,
    "market_phase": "pre_market",
    "global_analysis": {
      "weighted_sentiment": -0.107,
      "total_count": 56,
      "positive_ratio": 0.16,
      "category_breakdown": {
        "trade_policy": {"avg_sentiment": -0.425, "count": 8},
        "technology": {"avg_sentiment": -0.100, "count": 21}
      }
    },
    "domestic_analysis": {
      "weighted_sentiment": -0.029,
      "total_count": 1185,
      "positive_ratio": 0.01
    },
    "key_factors": [
      {"factor": "무역/관세", "impact": "부정", "news_count": 8, "avg_sentiment": -0.425},
      {"factor": "반도체/AI", "impact": "부정", "news_count": 21, "avg_sentiment": -0.100}
    ],
    "summary": "[장전] KOSPI/KOSDAQ 예측: ▼ 소폭 하락 예상\n신뢰도: 44% | 종합 감성: -0.072"
  }
}
```

### 2-2. 시장 예측 (요약만)

```
GET /api/market/predict/summary?hours=24
```

**응답 예시:**
```json
{
  "success": true,
  "direction": "down",
  "strength": "moderate",
  "confidence": 0.44,
  "summary": "[장전] KOSPI/KOSDAQ 예측: ▼ 소폭 하락 예상\n신뢰도: 44% | 종합 감성: -0.072\n글로벌 뉴스: 56건 (감성: -0.107, 긍정률: 16%)\n국내 뉴스: 1185건 (감성: -0.029, 긍정률: 1%)\n핵심 요인:\n  - 무역/관세: 부정 (8건, 감성 -0.425)"
}
```

### 2-3. 글로벌 뉴스 감성만 조회

```
GET /api/market/global-sentiment?hours=24
```

---

## 3. Python에서 사용하기

### 3-1. requests 라이브러리

```python
import requests

# 시장 예측 조회
resp = requests.get("http://127.0.0.1:8000/api/market/predict", params={"hours": 24})
data = resp.json()["data"]

direction = data["prediction"]["direction"]   # "up" | "down" | "neutral"
strength  = data["prediction"]["strength"]    # "strong" | "moderate" | "weak"
confidence = data["confidence"]               # 0.0 ~ 1.0
sentiment  = data["combined_sentiment"]       # -1.0 ~ +1.0

print(f"방향: {direction}, 강도: {strength}, 신뢰도: {confidence:.0%}")

# 핵심 요인 출력
for factor in data["key_factors"]:
    print(f"  {factor['factor']}: {factor['impact']} (감성 {factor['avg_sentiment']:+.3f})")
```

### 3-2. 매매 로직에 통합하기

```python
import requests

def get_market_prediction() -> dict:
    """NewsQuant 시장 예측 조회"""
    try:
        resp = requests.get(
            "http://127.0.0.1:8000/api/market/predict",
            params={"hours": 24},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["data"]
    except Exception as e:
        print(f"시장 예측 조회 실패: {e}")
        return None


def should_trade_today() -> dict:
    """오늘 매매 여부 판단"""
    pred = get_market_prediction()
    if pred is None:
        return {"trade": True, "reason": "예측 데이터 없음, 기본 매매"}

    direction = pred["prediction"]["direction"]
    confidence = pred["confidence"]
    strength = pred["prediction"]["strength"]

    # 강한 하락 예측 + 높은 신뢰도 → 매매 보류
    if direction == "down" and strength == "strong" and confidence >= 0.6:
        return {
            "trade": False,
            "reason": f"강한 하락 예측 (신뢰도 {confidence:.0%})",
            "action": "매수 보류, 기존 포지션 축소 검토",
        }

    # 강한 상승 예측 → 적극 매매
    if direction == "up" and strength == "strong" and confidence >= 0.6:
        return {
            "trade": True,
            "reason": f"강한 상승 예측 (신뢰도 {confidence:.0%})",
            "action": "적극 매수, 포지션 확대 검토",
        }

    # 혼조 또는 약한 신호 → 일반 매매
    return {
        "trade": True,
        "reason": f"{direction} ({strength}, 신뢰도 {confidence:.0%})",
        "action": "일반 매매, 뉴스 모니터링",
    }


# 사용 예시
result = should_trade_today()
print(f"매매: {'O' if result['trade'] else 'X'}")
print(f"판단: {result['reason']}")
print(f"행동: {result['action']}")
```

### 3-3. 장전 자동 리포트

```python
import requests
from datetime import datetime

def morning_report():
    """장전 시장 리포트 (08:30에 실행)"""
    # 1. 시장 예측
    pred = requests.get(
        "http://127.0.0.1:8000/api/market/predict",
        params={"hours": 24}
    ).json()["data"]

    # 2. 매수/매도 후보
    candidates = requests.get(
        "http://127.0.0.1:8000/api/trading/analysis/today"
    ).json()["data"]

    print(f"=== {datetime.now().strftime('%Y-%m-%d')} 장전 리포트 ===")
    print()
    print(pred["summary"])
    print()
    print(f"매수 후보: {len(candidates.get('buy_candidates', []))}종목")
    for c in candidates.get("buy_candidates", [])[:5]:
        print(f"  {c['stock_code']} (감성 {c['avg_sentiment']:+.3f}, 뉴스 {c['news_count']}건)")
    print(f"매도 후보: {len(candidates.get('sell_candidates', []))}종목")
    for c in candidates.get("sell_candidates", [])[:5]:
        print(f"  {c['stock_code']} (감성 {c['avg_sentiment']:+.3f}, 뉴스 {c['news_count']}건)")

morning_report()
```

---

## 4. PostgreSQL에서 직접 쿼리

DB에 직접 접속하여 분석할 수도 있습니다.

```
호스트: localhost
포트: 5433
DB명: newsquant
계정: postgres / postgres
```

### 유용한 쿼리

```sql
-- 최근 24시간 글로벌 뉴스 감성 평균
SELECT source,
       COUNT(*) as cnt,
       ROUND(AVG(sentiment_score)::numeric, 3) as avg_sentiment,
       ROUND(AVG(overall_score)::numeric, 3) as avg_overall
FROM news
WHERE published_at >= NOW() - INTERVAL '24 hours'
  AND source IN ('google_news_finance','google_news_asia','google_news_trade',
                  'google_news_tech','cnbc','marketwatch','investing_com')
GROUP BY source
ORDER BY cnt DESC;

-- 카테고리별 글로벌 감성
SELECT category,
       COUNT(*) as cnt,
       ROUND(AVG(sentiment_score)::numeric, 3) as avg_sentiment
FROM news
WHERE published_at >= NOW() - INTERVAL '24 hours'
  AND source LIKE 'google_news_%'
GROUP BY category
ORDER BY cnt DESC;

-- 특정 종목 최근 뉴스 + 감성
SELECT title, source, sentiment_score, overall_score, published_at
FROM news
WHERE related_stocks LIKE '%005930%'
ORDER BY published_at DESC
LIMIT 20;

-- 일별 감성 추이 (최근 7일)
SELECT DATE(published_at) as dt,
       COUNT(*) as cnt,
       ROUND(AVG(sentiment_score)::numeric, 3) as avg_sent
FROM news
WHERE published_at >= NOW() - INTERVAL '7 days'
GROUP BY dt
ORDER BY dt DESC;
```

---

## 5. 예측 해석 가이드

| direction | strength | confidence | 해석 |
|-----------|----------|-----------|------|
| up | strong | >= 0.6 | 강한 상승 기대. 적극 매수 고려 |
| up | moderate | 0.4~0.6 | 소폭 상승 가능. 일반 매매 |
| neutral | weak | < 0.4 | 방향 불분명. 보수적 접근 |
| down | moderate | 0.4~0.6 | 소폭 하락 가능. 신규 매수 자제 |
| down | strong | >= 0.6 | 강한 하락 우려. 매수 보류, 리스크 관리 |

**mixed_signals = true**: 글로벌과 국내 방향이 엇갈림. 변동성 확대 가능.

### 시간대별 가중치

| 시간대 | 글로벌 비중 | 국내 비중 | 설명 |
|--------|-----------|----------|------|
| 장전 (09:00 전) | 65% | 35% | 미국 장 마감 영향 반영 |
| 장중 (09:00~15:30) | 40% | 60% | 국내 실시간 뉴스 반영 |
| 장후 (15:30 이후) | 55% | 45% | 다음 날 전망 |

### 핵심 요인 (key_factors)

| factor | 설명 |
|--------|------|
| US 금리/연준 | Fed 금리 결정, FOMC, 파월 발언 |
| 무역/관세 | 관세, 무역전쟁, 제재, 수출입 |
| 반도체/AI | 반도체, NVIDIA, DRAM, AI |
| 미국 증시 | 다우, 나스닥, S&P 500 동향 |
| 중국 경제 | 중국 경제지표, 위안화, PBOC |
| 지정학 | 전쟁, 분쟁, 군사, 미사일 |
| 환율 | 달러, 원화, 엔화, 환율 |

---

## 6. RoboTrader 통합 예시

```python
# RoboTrader council 모듈에서 사용
class NewsQuantCouncil:
    """NewsQuant 시장 예측 기반 의견"""

    API_URL = "http://127.0.0.1:8000"

    def get_opinion(self) -> dict:
        import requests

        try:
            resp = requests.get(
                f"{self.API_URL}/api/market/predict",
                params={"hours": 24},
                timeout=10,
            )
            data = resp.json()["data"]
        except Exception:
            return {"signal": "neutral", "weight": 0.0, "reason": "NewsQuant 연결 실패"}

        direction = data["prediction"]["direction"]
        confidence = data["confidence"]

        # 신호 변환
        if direction == "up":
            signal = "bullish"
            weight = confidence
        elif direction == "down":
            signal = "bearish"
            weight = confidence
        else:
            signal = "neutral"
            weight = 0.0

        return {
            "signal": signal,
            "weight": round(weight, 3),
            "reason": data["prediction"]["description"],
            "key_factors": data["key_factors"][:3],
            "global_sentiment": data["global_analysis"].get("weighted_sentiment", 0),
            "domestic_sentiment": data["domestic_analysis"].get("weighted_sentiment", 0),
        }
```
