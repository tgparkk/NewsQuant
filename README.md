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

## 설치 방법

1. 필요한 패키지 설치:
```bash
pip install -r requirements.txt
```

2. 프로그램 실행:
```bash
python main.py
```

## 프로젝트 구조

```
NewsQuant/
├── news_scraper/
│   ├── __init__.py
│   ├── base_crawler.py          # 기본 크롤러 클래스
│   ├── database.py               # 데이터베이스 관리
│   ├── scheduler.py              # 스케줄러
│   └── crawlers/
│       ├── __init__.py
│       ├── naver_finance_crawler.py
│       ├── krx_crawler.py
│       ├── yonhap_crawler.py
│       ├── hankyung_crawler.py
│       └── mk_crawler.py
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
- `sentiment_score`: 감성 점수 (향후 사용)
- `created_at`: 생성일시
- `updated_at`: 수정일시

### collection_log 테이블
- 수집 이력 및 오류 로그 관리

## 사용 방법

### 기본 실행
```bash
python main.py
```

프로그램이 실행되면 자동으로 스케줄에 따라 뉴스를 수집합니다.

### 데이터 조회

Python 스크립트에서:
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

## 주의사항

1. **법적 고지**: 웹 크롤링은 각 사이트의 이용약관과 robots.txt를 준수해야 합니다. 과도한 요청은 차단될 수 있으니 적절한 딜레이를 설정했습니다.

2. **데이터베이스**: SQLite를 사용하며, 대용량 데이터 처리 시 MySQL이나 PostgreSQL로 마이그레이션을 고려하세요.

3. **크롤러 조정**: 각 뉴스 사이트의 HTML 구조가 변경될 수 있으므로, 크롤러를 주기적으로 점검하고 조정해야 합니다.

## 향후 개선 사항

- [ ] 감성 분석 기능 추가
- [ ] MySQL/PostgreSQL 지원
- [ ] 웹 대시보드 추가
- [ ] 알림 기능 (중요 뉴스 발견 시)
- [ ] API 서버 제공
- [ ] 더 많은 뉴스 소스 추가

## 라이선스

이 프로젝트는 개인 사용 목적으로 개발되었습니다.

