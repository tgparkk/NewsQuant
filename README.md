# NewsQuant - 주식 뉴스 수집 및 시장 예측 시스템

국내외 뉴스를 자동 수집하고, 감성 분석을 통해 KOSPI/KOSDAQ 지수 예측 및 개별 종목 매매 시그널을 생성하는 시스템입니다.

## 주요 기능

- **국내 뉴스 수집**: 네이버 금융, DART 공시, 연합인포맥스, 한국경제, 매일경제
- **글로벌 뉴스 수집**: Google News, CNBC, MarketWatch, Investing.com (RSS 기반)
- **감성 분석**: 한국어/영어 뉴스 감성 점수 산출
- **시장 예측**: 글로벌+국내 뉴스 기반 KOSPI/KOSDAQ 방향 예측
- **매매 시그널**: 종목별 뉴스 분석 → 매수/매도 후보 추출
- **확산도 가중치**: 중복 보도량 기반 시장 관심도 반영
- **REST API**: FastAPI 기반, 다른 프로그램에서 HTTP로 데이터 접근

## 설치 및 실행

### 사전 요구사항
- Python 3.10+
- PostgreSQL (포트 5433, DB명: newsquant)

### 설치
```bash
pip install -r requirements.txt
```

### 실행
```bash
# 전체 실행 (스케줄러 + API 서버)
python main.py

# API 서버만 실행
python run_api.py

# 스케줄러만 실행
python run_scheduler.py
```

실행 후:
- API 서버: http://127.0.0.1:8000
- Swagger 문서: http://127.0.0.1:8000/docs

## 수집 스케줄

| 시간대 | 주기 |
|--------|------|
| 장중 (월~금 09:00~15:30) | 1분 |
| 장후 (월~금 15:30~24:00) | 5분 |
| 주말/새벽 | 30분 |

## 프로젝트 구조

```
NewsQuant/
├── main.py                          # 메인 실행 (스케줄러 + API)
├── run_api.py                       # API 서버 단독 실행
├── run_scheduler.py                 # 스케줄러 단독 실행
├── news_scraper/
│   ├── database.py                  # PostgreSQL (psycopg2 커넥션 풀)
│   ├── scheduler.py                 # APScheduler 오케스트레이터
│   ├── sentiment_analyzer.py        # 한국어 감성 분석
│   ├── english_sentiment_analyzer.py # 영어 감성 분석
│   ├── market_predictor.py          # KOSPI/KOSDAQ 지수 예측
│   ├── trading_analyzer.py          # 개별 종목 매매 시그널
│   ├── price_fetcher.py             # 주가 데이터 조회
│   ├── config.py                    # 설정
│   ├── base_crawler.py              # 크롤러 베이스 클래스
│   ├── api/
│   │   └── server.py                # FastAPI 엔드포인트
│   ├── crawlers/
│   │   ├── naver_finance_crawler.py # 네이버 금융
│   │   ├── dart_crawler.py          # DART 공시
│   │   ├── yonhap_crawler.py        # 연합인포맥스
│   │   ├── hankyung_crawler.py      # 한국경제
│   │   ├── mk_crawler.py            # 매일경제
│   │   ├── krx_crawler.py           # 한국거래소
│   │   └── global_news_crawler.py   # 글로벌 뉴스 (RSS)
│   └── data_quality/                # 데이터 품질 검증
├── scripts/                         # 유틸리티 스크립트
├── examples/                        # API 클라이언트 예제
└── docs/                            # 문서
    ├── API_사용가이드.md             # 뉴스 API 가이드
    ├── TRADING_API_GUIDE.md         # 매매 시그널 API 가이드
    ├── MARKET_PREDICT_API_GUIDE.md  # 시장 예측 API 가이드
    ├── 빠른시작가이드.md              # 빠른 시작 가이드
    └── ...                          # 기타 개발 기록
```

## API 엔드포인트

### 뉴스 조회
- `GET /api/news/latest` - 최신 뉴스
- `GET /api/news/date` - 날짜 범위 조회
- `GET /api/news/stock/{code}` - 종목별 뉴스
- `GET /api/news/search` - 검색/필터링

### 시장 예측
- `GET /api/market/predict` - KOSPI/KOSDAQ 예측 (전체 분석)
- `GET /api/market/predict/summary` - 예측 요약
- `GET /api/market/global-sentiment` - 글로벌 뉴스 감성

### 매매 시그널
- `GET /api/trading/analysis/today` - 오늘의 종목 분석
- `GET /api/trading/signal/{code}` - 개별 종목 시그널
- `POST /api/trading/signals/batch` - 다중 종목 시그널
- `GET /api/trading/buy-candidates` - 매수 후보
- `GET /api/trading/sell-candidates` - 매도 후보

### 상태
- `GET /api/stats` - 수집 통계
- `GET /api/health` - 서버 상태

자세한 사용법은 [docs/](docs/) 폴더의 가이드를 참조하세요.

## 데이터베이스

PostgreSQL을 사용합니다.

```
Host: localhost
Port: 5433
Database: newsquant
User: postgres
```

### 주요 테이블
- `news` - 수집된 뉴스 (감성 점수, 종목 코드, 확산도 등 포함)
- `collection_log` - 수집 이력 및 오류 로그

## 라이선스

이 프로젝트는 개인 사용 목적으로 개발되었습니다.
