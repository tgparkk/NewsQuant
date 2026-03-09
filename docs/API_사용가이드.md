# NewsQuant API 사용 가이드

## API 기본 정보

- **API 서버 주소**: http://127.0.0.1:8000
- **API 문서**: http://127.0.0.1:8000/docs (Swagger UI)
- **ReDoc 문서**: http://127.0.0.1:8000/redoc
- **기본 포맷**: JSON

---

## API 호출 방법

### 1. 브라우저에서 직접 호출

가장 간단한 방법입니다. 브라우저 주소창에 URL을 입력하거나 링크를 클릭하면 됩니다.

```
http://127.0.0.1:8000/api/news/latest?limit=10
```

### 2. Python에서 호출 (requests 라이브러리)

```python
import requests

# API 기본 URL
API_BASE = "http://127.0.0.1:8000"

# GET 요청
response = requests.get(f"{API_BASE}/api/news/latest", params={
    "limit": 50,
    "min_score": 0.7
})

# 응답 확인
if response.status_code == 200:
    data = response.json()
    news_list = data["data"]
    print(f"조회된 뉴스: {len(news_list)}개")
else:
    print(f"오류: {response.status_code}")
```

### 3. C#에서 호출

```csharp
using System.Net.Http;
using System.Text.Json;

var httpClient = new HttpClient();
var baseUrl = "http://127.0.0.1:8000";

// GET 요청
var response = await httpClient.GetAsync($"{baseUrl}/api/news/latest?limit=50&min_score=0.7");
var content = await response.Content.ReadAsStringAsync();

// JSON 파싱
var jsonDoc = JsonDocument.Parse(content);
var data = jsonDoc.RootElement.GetProperty("data");
```

### 4. JavaScript/TypeScript에서 호출

```javascript
// Fetch API 사용
const API_BASE = "http://127.0.0.1:8000";

// GET 요청
const response = await fetch(`${API_BASE}/api/news/latest?limit=50&min_score=0.7`);
const data = await response.json();

console.log(`조회된 뉴스: ${data.count}개`);
data.data.forEach(news => {
    console.log(news.title);
});
```

### 5. curl 명령어로 호출

```bash
# 기본 호출
curl "http://127.0.0.1:8000/api/news/latest?limit=10"

# JSON 형식으로 보기 좋게 출력
curl "http://127.0.0.1:8000/api/news/latest?limit=10" | python -m json.tool
```

---

## API 엔드포인트별 사용법

### 1. 최신 뉴스 조회

**엔드포인트**: `GET /api/news/latest`

**파라미터:**
- `limit` (선택): 조회 개수 (1-1000, 기본값: 100)
- `source` (선택): 출처 필터 (예: "naver_finance", "hankyung")
- `min_score` (선택): 최소 종합 점수 (-1.0 ~ 1.0)

**호출 예시:**

```python
import requests

# 기본 호출 (최신 100개)
response = requests.get("http://127.0.0.1:8000/api/news/latest")
data = response.json()

# 파라미터 사용
response = requests.get("http://127.0.0.1:8000/api/news/latest", params={
    "limit": 50,
    "source": "naver_finance",
    "min_score": 0.7
})
data = response.json()
```

**응답 예시:**

```json
{
  "success": true,
  "count": 50,
  "data": [
    {
      "id": 123,
      "news_id": "naver_20240115_001",
      "title": "삼성전자 주가 상승, 반도체 호조 영향",
      "content": "삼성전자가 반도체 업황 개선으로 주가가 상승세를 보이고 있다...",
      "published_at": "2024-01-15T09:30:00",
      "source": "naver_finance",
      "category": "증시",
      "url": "https://finance.naver.com/news/...",
      "related_stocks": "005930,000660",
      "sentiment_score": 0.75,
      "importance_score": 0.8,
      "impact_score": 0.7,
      "timeliness_score": 1.0,
      "overall_score": 0.82,
      "created_at": "2024-01-15T09:31:00",
      "updated_at": "2024-01-15T09:31:00"
    },
    ...
  ]
}
```

---

### 2. 날짜 범위로 뉴스 조회

**엔드포인트**: `GET /api/news/date`

**파라미터:**
- `start_date` (필수): 시작일시 (ISO 형식, 예: "2024-01-15T00:00:00")
- `end_date` (필수): 종료일시 (ISO 형식)
- `source` (선택): 출처 필터

**호출 예시:**

```python
import requests
from datetime import datetime, timedelta

# 오늘 뉴스 조회
today = datetime.now()
yesterday = today - timedelta(days=1)

response = requests.get("http://127.0.0.1:8000/api/news/date", params={
    "start_date": yesterday.isoformat(),
    "end_date": today.isoformat()
})
data = response.json()
```

**응답 형식:**
- `GET /api/news/latest`와 동일한 형식

---

### 3. 종목별 뉴스 조회 (단일 종목)

**엔드포인트**: `GET /api/news/stock/{stock_code}`

**파라미터:**
- `stock_code` (필수): 종목 코드 (6자리, 예: "005930")
- `limit` (선택): 조회 개수 (1-500, 기본값: 50)

**호출 예시:**

```python
import requests

# 삼성전자(005930) 뉴스 조회
response = requests.get("http://127.0.0.1:8000/api/news/stock/005930", params={
    "limit": 20
})
data = response.json()

# 응답에서 종목 코드 확인
print(f"종목 코드: {data['stock_code']}")
print(f"조회된 뉴스: {data['count']}개")
```

**응답 예시:**

```json
{
  "success": true,
  "stock_code": "005930",
  "count": 20,
  "data": [
    {
      "id": 123,
      "title": "삼성전자 주가 상승...",
      "related_stocks": "005930,000660",
      ...
    },
    ...
  ]
}
```

---

### 3-1. 여러 종목 배치 조회 ⭐ (실전 추천)

**엔드포인트**: `POST /api/news/stocks/batch`

**파라미터:**
- `stock_codes` (필수): 종목 코드 리스트 (최대 100개)
- `limit_per_stock` (선택): 종목당 조회 개수 (기본값: 10)
- `min_score` (선택): 최소 종합 점수 (-1.0 ~ 1.0)

**호출 예시:**

```python
import requests

# 여러 종목 한 번에 조회 (배치)
response = requests.post(
    "http://127.0.0.1:8000/api/news/stocks/batch",
    json={
        "stock_codes": ["005930", "000660", "035420"],
        "limit_per_stock": 10,
        "min_score": 0.6
    }
)
data = response.json()

# 각 종목별 결과
for stock_code, result in data["results"].items():
    print(f"{stock_code}: {result['count']}개 뉴스")
    for news in result["news"]:
        print(f"  - {news['title']}")
```

**응답 예시:**

```json
{
  "success": true,
  "stock_codes": ["005930", "000660", "035420"],
  "limit_per_stock": 10,
  "min_score": 0.6,
  "total_news_count": 25,
  "results": {
    "005930": {
      "count": 10,
      "news": [...]
    },
    "000660": {
      "count": 8,
      "news": [...]
    },
    "035420": {
      "count": 7,
      "news": [...]
    }
  }
}
```

**실전 사용 시나리오:**

```python
# 1차: 주식 데이터로 종목 필터링
filtered_stocks = ["005930", "000660", "035420"]

# 2차: 뉴스 데이터로 추가 분석
response = requests.post(
    "http://127.0.0.1:8000/api/news/stocks/batch",
    json={
        "stock_codes": filtered_stocks,
        "limit_per_stock": 10,
        "min_score": 0.6
    }
)

# 뉴스 분석 후 매매 결정
data = response.json()
for stock_code, result in data["results"].items():
    if result["news"]:
        latest = result["news"][0]
        if latest.get("sentiment_score", 0) > 0.5:
            print(f"{stock_code}: 긍정적 뉴스 발견!")
```

---

### 4. 뉴스 검색 (고급 필터링)

**파라미터:**
- `stock_code` (필수): 종목 코드 (6자리, 예: "005930")
- `limit` (선택): 조회 개수 (1-500, 기본값: 50)

**호출 예시:**

```python
import requests

# 삼성전자(005930) 뉴스 조회
response = requests.get("http://127.0.0.1:8000/api/news/stock/005930", params={
    "limit": 20
})
data = response.json()

# 응답에서 종목 코드 확인
print(f"종목 코드: {data['stock_code']}")
print(f"조회된 뉴스: {data['count']}개")
```

**응답 예시:**

```json
{
  "success": true,
  "stock_code": "005930",
  "count": 20,
  "data": [
    {
      "id": 123,
      "title": "삼성전자 주가 상승...",
      "related_stocks": "005930,000660",
      ...
    },
    ...
  ]
}
```

---

### 4. 뉴스 검색 (고급 필터링)

**엔드포인트**: `GET /api/news/search`

**파라미터:**
- `keyword` (선택): 키워드 검색 (제목, 본문)
- `min_sentiment` (선택): 최소 감성 점수 (-1.0 ~ 1.0)
- `max_sentiment` (선택): 최대 감성 점수 (-1.0 ~ 1.0)
- `min_overall_score` (선택): 최소 종합 점수 (-1.0 ~ 1.0)
- `source` (선택): 출처 필터
- `limit` (선택): 조회 개수 (1-1000, 기본값: 100)

**호출 예시:**

```python
import requests

# 긍정적인 뉴스만 검색 (감성 점수 0.5 이상)
response = requests.get("http://127.0.0.1:8000/api/news/search", params={
    "min_sentiment": 0.5,
    "limit": 50
})
data = response.json()

# 키워드 + 감성 점수 필터
response = requests.get("http://127.0.0.1:8000/api/news/search", params={
    "keyword": "삼성전자",
    "min_sentiment": 0.5,
    "min_overall_score": 0.7,
    "limit": 20
})
data = response.json()
```

**응답 예시:**

```json
{
  "success": true,
  "count": 50,
  "filters": {
    "keyword": null,
    "min_sentiment": 0.5,
    "max_sentiment": null,
    "min_overall_score": null,
    "source": null
  },
  "data": [
    ...
  ]
}
```

---

### 5. 통계 조회

**엔드포인트**: `GET /api/stats`

**파라미터:**
- `days` (선택): 최근 N일간 통계 (1-365, 기본값: 7)

**호출 예시:**

```python
import requests

# 최근 7일 통계
response = requests.get("http://127.0.0.1:8000/api/stats", params={
    "days": 7
})
data = response.json()

stats = data["data"]
print(f"전체 뉴스: {stats['total_news']:,}개")
print("출처별 뉴스:")
for source, count in stats['by_source'].items():
    print(f"  {source}: {count:,}개")
```

**응답 예시:**

```json
{
  "success": true,
  "days": 7,
  "data": {
    "total_news": 1250,
    "by_source": {
      "naver_finance": 450,
      "hankyung": 300,
      "mk_news": 250,
      "yonhap_infomax": 150,
      "krx_disclosure": 100
    },
    "recent_collection": {
      "naver_finance": {
        "total": 450,
        "attempts": 210
      },
      ...
    }
  }
}
```

---

### 6. 건강 상태 체크

**엔드포인트**: `GET /api/health`

**호출 예시:**

```python
import requests

response = requests.get("http://127.0.0.1:8000/api/health")
data = response.json()

if data["status"] == "healthy":
    print("API 서버 정상 작동 중")
else:
    print(f"문제 발생: {data.get('error')}")
```

**응답 예시 (정상):**

```json
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2024-01-15T10:30:00"
}
```

**응답 예시 (오류):**

```json
{
  "status": "unhealthy",
  "database": "disconnected",
  "error": "Database connection failed",
  "timestamp": "2024-01-15T10:30:00"
}
```

---

## 응답 형식 상세 설명

### 성공 응답 (200 OK)

모든 API는 성공 시 다음과 같은 공통 구조를 가집니다:

```json
{
  "success": true,
  "count": 50,  // 데이터 개수 (일부 API에만)
  "data": [...] // 실제 데이터
}
```

### 에러 응답

#### 400 Bad Request (잘못된 요청)

```json
{
  "detail": "종목 코드는 6자리 숫자여야 합니다. 예: 005930"
}
```

#### 500 Internal Server Error (서버 오류)

```json
{
  "detail": "Database connection error"
}
```

#### 503 Service Unavailable (서비스 불가)

```json
{
  "status": "unhealthy",
  "database": "disconnected",
  "error": "...",
  "timestamp": "..."
}
```

---

## 뉴스 데이터 구조

각 뉴스 데이터는 다음과 같은 필드를 가집니다:

```json
{
  "id": 123,                              // 데이터베이스 ID
  "news_id": "naver_20240115_001",       // 뉴스 고유 ID
  "title": "뉴스 제목",                   // 제목
  "content": "뉴스 본문...",              // 본문
  "published_at": "2024-01-15T09:30:00", // 발행일시 (ISO 형식)
  "source": "naver_finance",             // 출처
  "category": "증시",                     // 카테고리
  "url": "https://...",                  // 원본 URL
  "related_stocks": "005930,000660",     // 관련 종목 코드 (콤마 구분)
  "sentiment_score": 0.75,               // 감성 점수 (-1.0 ~ +1.0)
  "importance_score": 0.8,               // 중요도 점수 (0.0 ~ 1.0)
  "impact_score": 0.7,                   // 영향도 점수 (0.0 ~ 1.0)
  "timeliness_score": 1.0,               // 실시간성 점수 (0.0 ~ 1.0)
  "overall_score": 0.82,                 // 종합 점수
  "created_at": "2024-01-15T09:31:00",  // 생성일시
  "updated_at": "2024-01-15T09:31:00"   // 수정일시
}
```

### 점수 설명

- **sentiment_score** (-1.0 ~ +1.0)
  - -1.0: 매우 부정적 (주가 하락 신호)
  - 0.0: 중립
  - +1.0: 매우 긍정적 (주가 상승 신호)

- **overall_score** (종합 점수)
  - 감성, 중요도, 영향도, 실시간성을 종합한 점수
  - 높을수록 중요한 뉴스

---

## 실전 사용 예제

### 예제 1: 주식 거래 프로그램에서 사용

```python
import requests
from datetime import datetime, timedelta

class NewsMonitor:
    def __init__(self):
        self.api_base = "http://127.0.0.1:8000"
    
    def get_important_news(self, min_score=0.7):
        """중요한 뉴스만 조회"""
        response = requests.get(
            f"{self.api_base}/api/news/latest",
            params={"limit": 50, "min_score": min_score},
            timeout=5
        )
        response.raise_for_status()
        return response.json()["data"]
    
    def monitor_stock(self, stock_code):
        """특정 종목 뉴스 모니터링"""
        response = requests.get(
            f"{self.api_base}/api/news/stock/{stock_code}",
            params={"limit": 10},
            timeout=5
        )
        response.raise_for_status()
        return response.json()["data"]
    
    def get_positive_news(self):
        """긍정적인 뉴스만 조회"""
        response = requests.get(
            f"{self.api_base}/api/news/search",
            params={"min_sentiment": 0.5, "limit": 20},
            timeout=5
        )
        response.raise_for_status()
        return response.json()["data"]

# 사용
monitor = NewsMonitor()

# 중요한 뉴스 확인
important_news = monitor.get_important_news(min_score=0.8)
for news in important_news[:5]:
    print(f"{news['title']} - 점수: {news['overall_score']}")

# 삼성전자 뉴스 모니터링
samsung_news = monitor.monitor_stock("005930")
for news in samsung_news:
    print(f"{news['title']} - 감성: {news['sentiment_score']}")
```

### 예제 2: 실시간 모니터링

```python
import requests
import time

def monitor_latest_news(check_interval=60):
    """최신 뉴스를 주기적으로 확인"""
    api_base = "http://127.0.0.1:8000"
    last_news_id = None
    
    while True:
        try:
            response = requests.get(
                f"{api_base}/api/news/latest",
                params={"limit": 10},
                timeout=5
            )
            response.raise_for_status()
            news_list = response.json()["data"]
            
            # 새로운 뉴스 확인
            if news_list:
                latest_news = news_list[0]
                current_id = latest_news.get("news_id")
                
                if last_news_id != current_id:
                    print(f"\n새로운 뉴스 발견!")
                    print(f"제목: {latest_news['title']}")
                    print(f"점수: {latest_news.get('overall_score', 'N/A')}")
                    print(f"시간: {latest_news['published_at']}")
                    last_news_id = current_id
                else:
                    print(".", end="", flush=True)  # 진행 표시
            
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"\n오류 발생: {e}")
            time.sleep(check_interval)

# 실행
monitor_latest_news(check_interval=30)  # 30초마다 확인
```

### 예제 3: 특정 키워드 알림

```python
import requests

def check_keyword_news(keyword, min_sentiment=0.5):
    """특정 키워드가 포함된 긍정적인 뉴스 검색"""
    response = requests.get(
        "http://127.0.0.1:8000/api/news/search",
        params={
            "keyword": keyword,
            "min_sentiment": min_sentiment,
            "limit": 10
        },
        timeout=5
    )
    response.raise_for_status()
    return response.json()["data"]

# 사용
news = check_keyword_news("반도체", min_sentiment=0.6)
if news:
    print(f"'{keyword}' 관련 긍정적 뉴스 {len(news)}개 발견:")
    for item in news:
        print(f"  - {item['title']}")
        print(f"    감성 점수: {item['sentiment_score']}")
```

---

## 주의사항

1. **타임아웃 설정**: 네트워크 문제를 대비해 타임아웃을 설정하세요.
   ```python
   response = requests.get(url, timeout=5)
   ```

2. **에러 처리**: 항상 에러 처리를 포함하세요.
   ```python
   try:
       response = requests.get(url)
       response.raise_for_status()
       data = response.json()
   except requests.exceptions.RequestException as e:
       print(f"요청 실패: {e}")
   ```

3. **연결 확인**: API 서버가 실행 중인지 먼저 확인하세요.
   ```python
   health_response = requests.get("http://127.0.0.1:8000/api/health")
   if health_response.json()["status"] != "healthy":
       print("API 서버가 정상 작동하지 않습니다.")
   ```

4. **요청 빈도**: 과도한 요청은 피하세요. 적절한 간격을 두고 요청하세요.

---

## 브라우저에서 테스트하기

1. **API 문서 페이지**: http://127.0.0.1:8000/docs
   - 모든 API를 직접 테스트할 수 있습니다.
   - 파라미터를 입력하고 "Try it out" 버튼을 클릭하세요.

2. **직접 URL 입력**:
   ```
   http://127.0.0.1:8000/api/news/latest?limit=10
   ```

3. **ReDoc 문서**: http://127.0.0.1:8000/redoc
   - 읽기 좋은 형식의 API 문서입니다.

---

## 추가 리소스

- **예제 코드**: `examples/api_client_example.py`
- **API 서버 코드**: `news_scraper/api/server.py`
- **비교 분석 문서**: `DB직접접근_vs_API_비교분석.md`
