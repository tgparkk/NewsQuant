# 주식 뉴스 수집 시스템

주식 거래를 위한 뉴스 데이터를 자동으로 수집하는 시스템입니다.

## 주요 기능

- **다양한 뉴스 소스 지원**
  - 네이버 금융
  - 한국거래소 공시
  - 연합인포맥스
  - 한국경제
  - 매일경제

- **시장 시간 고려 자동 수집**
  - 시장 운영 시간 (월~금 09:00~15:30): 1분마다
  - 시장 마감 후 (월~금 15:30~24:00): 5분마다
  - 주말/새벽: 30분마다

- **SQLite 데이터베이스 저장**
  - 뉴스 데이터 영구 저장
  - 중복 방지
  - 수집 로그 관리
  - WAL 모드 지원 (동시 읽기/쓰기)

- **REST API 서버 제공**
  - 다른 프로그램에서 뉴스 데이터 접근 가능
  - FastAPI 기반 고성능 API
  - 자동 API 문서화 (Swagger/ReDoc)
  - 언어 제약 없음 (Python, C#, Java, JavaScript 등)

## 설치 방법

1. 필요한 패키지 설치:
```bash
pip install -r requirements.txt
```

2. 프로그램 실행:
```bash
python main.py
```

프로그램 실행 시 다음이 함께 시작됩니다:
- 뉴스 수집 스케줄러 (백그라운드)
- REST API 서버 (포트 8000)
  - API 문서: http://127.0.0.1:8000/docs
  - ReDoc 문서: http://127.0.0.1:8000/redoc

## 프로젝트 구조

```
NewsQuant/
├── news_scraper/
│   ├── __init__.py
│   ├── base_crawler.py          # 기본 크롤러 클래스
│   ├── database.py               # 데이터베이스 관리
│   ├── scheduler.py              # 스케줄러
│   ├── sentiment_analyzer.py    # 감성 분석
│   ├── api/                      # API 서버 모듈
│   │   ├── __init__.py
│   │   └── server.py            # FastAPI 서버
│   └── crawlers/
│       ├── __init__.py
│       ├── naver_finance_crawler.py
│       ├── krx_crawler.py
│       ├── yonhap_crawler.py
│       ├── hankyung_crawler.py
│       └── mk_crawler.py
├── examples/
│   └── api_client_example.py    # API 클라이언트 예제
├── main.py                       # 메인 실행 파일
├── requirements.txt              # 필수 패키지
├── news_data.db                  # SQLite 데이터베이스 (자동 생성)
└── news_scraper.log             # 로그 파일 (자동 생성)
```

## 데이터베이스 스키마

### news 테이블
- `id`: 자동 증가 ID
- `news_id`: 뉴스 고유 ID (중복 방지)
- `title`: 뉴스 제목
- `content`: 뉴스 본문
- `published_at`: 발행일시
- `source`: 출처
- `category`: 카테고리
- `url`: 뉴스 URL
- `related_stocks`: 관련 종목 코드 (콤마 구분)
- `sentiment_score`: 감성 점수 (-1.0 ~ +1.0)
- `importance_score`: 중요도 점수 (0.0 ~ 1.0)
- `impact_score`: 영향도 점수 (0.0 ~ 1.0)
- `timeliness_score`: 실시간성 점수 (0.0 ~ 1.0)
- `overall_score`: 종합 점수
- `created_at`: 생성일시
- `updated_at`: 수정일시

### collection_log 테이블
- 수집 이력 및 오류 로그 관리

## 사용 방법

### 기본 실행
```bash
python main.py
```

프로그램이 실행되면 자동으로 스케줄에 따라 뉴스를 수집하고, API 서버가 시작됩니다.

### REST API를 통한 데이터 조회 (추천)

다른 프로그램에서 HTTP API를 통해 뉴스 데이터에 접근할 수 있습니다.

**Python 예제:**
```python
import requests

API_BASE = "http://127.0.0.1:8000"

# 최신 뉴스 조회
response = requests.get(f"{API_BASE}/api/news/latest", params={
    "limit": 50,
    "min_score": 0.7
})
news_list = response.json()["data"]

# 종목별 뉴스 조회 (삼성전자)
response = requests.get(f"{API_BASE}/api/news/stock/005930")
samsung_news = response.json()["data"]

# 날짜 범위 조회
from datetime import datetime, timedelta
today = datetime.now()
yesterday = today - timedelta(days=1)
response = requests.get(f"{API_BASE}/api/news/date", params={
    "start_date": yesterday.isoformat(),
    "end_date": today.isoformat()
})

# 검색 (긍정적인 뉴스만)
response = requests.get(f"{API_BASE}/api/news/search", params={
    "min_sentiment": 0.5,
    "limit": 100
})
```

**더 많은 예제:**
- `examples/api_client_example.py` 파일 참조

**API 문서:**
- 브라우저에서 http://127.0.0.1:8000/docs 접속하면 모든 API를 테스트할 수 있습니다.

### 직접 데이터베이스 접근 (개발/테스트용)

Python 스크립트에서 직접 접근:
```python
from news_scraper.database import NewsDatabase
from datetime import datetime, timedelta

db = NewsDatabase()

# 최신 뉴스 조회
latest_news = db.get_latest_news(limit=100)

# 날짜 범위로 조회
start = (datetime.now() - timedelta(days=7)).isoformat()
end = datetime.now().isoformat()
news = db.get_news_by_date_range(start, end)

# 통계 조회
stats = db.get_collection_stats(days=7)
```

> **주의**: 실전 환경에서는 REST API를 사용하는 것을 권장합니다. 직접 데이터베이스 접근은 SQLite 동시 접근 문제가 발생할 수 있습니다.

## 주의사항

1. **법적 고지**: 웹 크롤링은 각 사이트의 이용약관과 robots.txt를 준수해야 합니다. 과도한 요청은 차단될 수 있으니 적절한 딜레이를 설정했습니다.

2. **데이터베이스**: SQLite를 사용하며, 대용량 데이터 처리 시 MySQL이나 PostgreSQL로 마이그레이션을 고려하세요.

3. **크롤러 조정**: 각 뉴스 사이트의 HTML 구조가 변경될 수 있으므로, 크롤러를 주기적으로 점검하고 조정해야 합니다.

## API 엔드포인트

### 뉴스 조회
- `GET /api/news/latest` - 최신 뉴스 조회
- `GET /api/news/date` - 날짜 범위로 뉴스 조회
- `GET /api/news/stock/{code}` - 종목별 뉴스 조회
- `GET /api/news/search` - 고급 검색 및 필터링

### 통계 및 상태
- `GET /api/stats` - 수집 통계 조회
- `GET /api/health` - API 서버 건강 상태

자세한 API 문서는 http://127.0.0.1:8000/docs 에서 확인할 수 있습니다.

## 향후 개선 사항

- [x] 감성 분석 기능 추가
- [x] API 서버 제공
- [ ] MySQL/PostgreSQL 지원
- [ ] 웹 대시보드 추가
- [ ] 알림 기능 (중요 뉴스 발견 시)
- [ ] 더 많은 뉴스 소스 추가
- [ ] API 인증 기능 (선택)
- [ ] 캐싱 레이어 추가 (성능 최적화)

## 라이선스

이 프로젝트는 개인 사용 목적으로 개발되었습니다.

