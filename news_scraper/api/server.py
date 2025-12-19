"""
FastAPI 서버
다른 프로그램에서 뉴스 데이터를 조회할 수 있는 REST API 제공
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict
from fastapi import FastAPI, Query, HTTPException, Body
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from threading import Thread

from ..database import NewsDatabase
from ..trading_analyzer import TradingAnalyzer

logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title="NewsQuant API",
    description="주식 뉴스 수집 시스템 REST API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS 설정 (다른 도메인에서 접근 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인만 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 데이터베이스 인스턴스
db = NewsDatabase()

# 매매 분석기 인스턴스
trading_analyzer = TradingAnalyzer()


# 요청 모델
class BatchStockRequest(BaseModel):
    stock_codes: List[str]
    limit_per_stock: int = 10
    min_score: Optional[float] = None


@app.get("/")
async def root():
    """API 루트 경로"""
    return {
        "service": "NewsQuant API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "running"
    }


@app.get("/api/health")
async def health_check():
    """API 서버 건강 상태 체크"""
    try:
        # DB 연결 테스트
        conn = db.get_connection()
        conn.execute("SELECT 1")
        conn.close()
        
        return JSONResponse({
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        )


@app.get("/api/news/latest")
async def get_latest_news(
    limit: int = Query(100, ge=1, le=1000, description="조회 개수"),
    source: Optional[str] = Query(None, description="출처 필터"),
    min_score: Optional[float] = Query(None, ge=-1.0, le=1.0, description="최소 종합 점수")
):
    """
    최신 뉴스 조회
    
    - **limit**: 조회할 뉴스 개수 (1-1000, 기본값: 100)
    - **source**: 출처 필터 (선택)
    - **min_score**: 최소 종합 점수 (선택, -1.0 ~ 1.0)
    """
    try:
        news_list = db.get_latest_news(limit=limit, source=source)
        
        # 종합 점수 필터링
        if min_score is not None:
            news_list = [
                news for news in news_list
                if news.get('overall_score') is not None
                and news['overall_score'] >= min_score
            ]
        
        return JSONResponse({
            "success": True,
            "count": len(news_list),
            "data": news_list
        })
    except Exception as e:
        logger.error(f"Error fetching latest news: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/news/date")
async def get_news_by_date(
    start_date: str = Query(..., description="시작일시 (ISO 형식, 예: 2024-01-15T00:00:00)"),
    end_date: str = Query(..., description="종료일시 (ISO 형식)"),
    source: Optional[str] = Query(None, description="출처 필터")
):
    """
    날짜 범위로 뉴스 조회
    
    - **start_date**: 시작일시 (ISO 형식, 필수)
    - **end_date**: 종료일시 (ISO 형식, 필수)
    - **source**: 출처 필터 (선택)
    """
    try:
        news_list = db.get_news_by_date_range(
            start_date=start_date,
            end_date=end_date,
            source=source
        )
        
        return JSONResponse({
            "success": True,
            "count": len(news_list),
            "data": news_list
        })
    except Exception as e:
        logger.error(f"Error fetching news by date: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/news/stock/{stock_code}")
async def get_news_by_stock(
    stock_code: str,
    limit: int = Query(50, ge=1, le=500, description="조회 개수")
):
    """
    특정 종목 관련 뉴스 조회
    
    - **stock_code**: 종목 코드 (6자리, 예: 005930)
    - **limit**: 조회 개수 (1-500, 기본값: 50)
    """
    try:
        # 종목 코드 검증 (6자리 숫자)
        if not stock_code.isdigit() or len(stock_code) != 6:
            raise HTTPException(
                status_code=400,
                detail="종목 코드는 6자리 숫자여야 합니다. 예: 005930"
            )
        
        news_list = db.get_news_by_stock(stock_code=stock_code, limit=limit)
        
        return JSONResponse({
            "success": True,
            "stock_code": stock_code,
            "count": len(news_list),
            "data": news_list
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching news by stock: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/news/stocks/batch")
async def get_news_by_stocks_batch(request: BatchStockRequest):
    """
    여러 종목의 뉴스를 한 번에 조회 (배치 조회)
    
    실전 주식 거래 환경에서 1차 필터링된 종목들의 뉴스를 빠르게 조회할 때 사용
    
    - **stock_codes**: 종목 코드 리스트 (6자리, 예: ["005930", "000660"])
    - **limit_per_stock**: 종목당 조회 개수 (기본값: 10)
    - **min_score**: 최소 종합 점수 (선택)
    """
    try:
        # 종목 코드 검증
        invalid_codes = [
            code for code in request.stock_codes
            if not code.isdigit() or len(code) != 6
        ]
        
        if invalid_codes:
            raise HTTPException(
                status_code=400,
                detail=f"잘못된 종목 코드: {invalid_codes}. 종목 코드는 6자리 숫자여야 합니다."
            )
        
        # 종목 수 제한 (실전 환경 보호)
        if len(request.stock_codes) > 100:
            raise HTTPException(
                status_code=400,
                detail="한 번에 조회할 수 있는 종목 수는 최대 100개입니다."
            )
        
        # 여러 종목의 뉴스 조회
        results = db.get_news_by_stocks(
            stock_codes=request.stock_codes,
            limit_per_stock=request.limit_per_stock
        )
        
        # 종합 점수 필터링
        if request.min_score is not None:
            filtered_results = {}
            for stock_code, news_list in results.items():
                filtered_news = [
                    news for news in news_list
                    if news.get('overall_score') is not None
                    and news['overall_score'] >= request.min_score
                ]
                filtered_results[stock_code] = filtered_news
            results = filtered_results
        
        # 결과 통계
        total_news = sum(len(news_list) for news_list in results.values())
        
        return JSONResponse({
            "success": True,
            "stock_codes": request.stock_codes,
            "limit_per_stock": request.limit_per_stock,
            "min_score": request.min_score,
            "total_news_count": total_news,
            "results": {
                stock_code: {
                    "count": len(news_list),
                    "news": news_list
                }
                for stock_code, news_list in results.items()
            }
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching news by stocks batch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/news/search")
async def search_news(
    keyword: Optional[str] = Query(None, description="키워드 검색 (제목, 본문)"),
    min_sentiment: Optional[float] = Query(None, ge=-1.0, le=1.0, description="최소 감성 점수"),
    max_sentiment: Optional[float] = Query(None, ge=-1.0, le=1.0, description="최대 감성 점수"),
    min_overall_score: Optional[float] = Query(None, ge=-1.0, le=1.0, description="최소 종합 점수"),
    source: Optional[str] = Query(None, description="출처 필터"),
    limit: int = Query(100, ge=1, le=1000, description="조회 개수")
):
    """
    뉴스 검색 (고급 필터링)
    
    - **keyword**: 키워드 검색 (제목, 본문)
    - **min_sentiment**: 최소 감성 점수 (-1.0 ~ 1.0)
    - **max_sentiment**: 최대 감성 점수 (-1.0 ~ 1.0)
    - **min_overall_score**: 최소 종합 점수 (-1.0 ~ 1.0)
    - **source**: 출처 필터
    - **limit**: 조회 개수 (1-1000, 기본값: 100)
    """
    try:
        news_list = db.search_news(
            keyword=keyword,
            min_sentiment=min_sentiment,
            max_sentiment=max_sentiment,
            min_overall_score=min_overall_score,
            source=source,
            limit=limit
        )
        
        return JSONResponse({
            "success": True,
            "count": len(news_list),
            "filters": {
                "keyword": keyword,
                "min_sentiment": min_sentiment,
                "max_sentiment": max_sentiment,
                "min_overall_score": min_overall_score,
                "source": source
            },
            "data": news_list
        })
    except Exception as e:
        logger.error(f"Error searching news: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_statistics(
    days: int = Query(7, ge=1, le=365, description="조회할 일수")
):
    """
    수집 통계 조회
    
    - **days**: 최근 N일간 통계 (1-365, 기본값: 7)
    """
    try:
        stats = db.get_collection_stats(days=days)
        
        return JSONResponse({
            "success": True,
            "days": days,
            "data": stats
        })
    except Exception as e:
        logger.error(f"Error fetching statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 매매 판단 API ====================

@app.get("/api/trading/analysis/today")
async def get_today_trading_analysis():
    """
    오늘자 뉴스 기반 종목 분석 결과 조회
    
    매수/매도 후보 종목 및 전체 종목 통계를 반환합니다.
    """
    try:
        analysis = trading_analyzer.analyze_today_stocks()
        
        return JSONResponse({
            "success": True,
            "data": analysis
        })
    except Exception as e:
        logger.error(f"Error analyzing today stocks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trading/signal/{stock_code}")
async def get_stock_trading_signal(
    stock_code: str,
    days: int = Query(1, ge=1, le=30, description="분석할 일수 (기본값: 1, 오늘만)")
):
    """
    특정 종목의 매매 신호 조회
    
    - **stock_code**: 종목 코드 (6자리, 예: 005930)
    - **days**: 분석할 일수 (1-30, 기본값: 1)
    
    반환값:
    - signal: "buy", "sell", "hold"
    - confidence: 신호 신뢰도 (0.0 ~ 1.0)
    - reason: 신호 이유
    """
    try:
        # 종목 코드 검증
        if not stock_code.isdigit() or len(stock_code) != 6:
            raise HTTPException(
                status_code=400,
                detail="종목 코드는 6자리 숫자여야 합니다. 예: 005930"
            )
        
        signal = trading_analyzer.get_stock_signal(stock_code, days=days)
        
        return JSONResponse({
            "success": True,
            "data": signal
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trading signal: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/trading/signals/batch")
async def get_trading_signals_batch(
    stock_codes: List[str] = Body(..., description="종목 코드 리스트"),
    days: int = Body(1, ge=1, le=30, description="분석할 일수")
):
    """
    여러 종목의 매매 신호를 한 번에 조회 (배치 조회)
    
    - **stock_codes**: 종목 코드 리스트 (예: ["005930", "000660"])
    - **days**: 분석할 일수 (1-30, 기본값: 1)
    """
    try:
        # 종목 코드 검증
        invalid_codes = [
            code for code in stock_codes
            if not code.isdigit() or len(code) != 6
        ]
        
        if invalid_codes:
            raise HTTPException(
                status_code=400,
                detail=f"잘못된 종목 코드: {invalid_codes}. 종목 코드는 6자리 숫자여야 합니다."
            )
        
        # 종목 수 제한
        if len(stock_codes) > 100:
            raise HTTPException(
                status_code=400,
                detail="한 번에 조회할 수 있는 종목 수는 최대 100개입니다."
            )
        
        # 각 종목의 신호 조회
        results = {}
        for stock_code in stock_codes:
            try:
                signal = trading_analyzer.get_stock_signal(stock_code, days=days)
                results[stock_code] = signal
            except Exception as e:
                logger.warning(f"Error getting signal for {stock_code}: {e}")
                results[stock_code] = {
                    'stock_code': stock_code,
                    'signal': 'hold',
                    'confidence': 0.0,
                    'error': str(e)
                }
        
        return JSONResponse({
            "success": True,
            "days": days,
            "count": len(results),
            "results": results
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trading signals batch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trading/stock/{stock_code}/analysis")
async def get_stock_detailed_analysis(
    stock_code: str,
    days: int = Query(7, ge=1, le=30, description="분석할 일수 (기본값: 7)")
):
    """
    종목별 상세 분석 조회
    
    - **stock_code**: 종목 코드 (6자리, 예: 005930)
    - **days**: 분석할 일수 (1-30, 기본값: 7)
    
    반환값:
    - 통계 정보 (평균 감성, 종합 점수 등)
    - 최신 뉴스 목록
    - 매매 신호
    """
    try:
        # 종목 코드 검증
        if not stock_code.isdigit() or len(stock_code) != 6:
            raise HTTPException(
                status_code=400,
                detail="종목 코드는 6자리 숫자여야 합니다. 예: 005930"
            )
        
        analysis = trading_analyzer.get_stock_analysis(stock_code, days=days)
        
        return JSONResponse({
            "success": True,
            "data": analysis
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stock analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trading/buy-candidates")
async def get_buy_candidates(
    min_confidence: float = Query(0.5, ge=0.0, le=1.0, description="최소 신뢰도"),
    limit: int = Query(20, ge=1, le=100, description="조회 개수")
):
    """
    매수 후보 종목 조회
    
    - **min_confidence**: 최소 신뢰도 (0.0 ~ 1.0, 기본값: 0.5)
    - **limit**: 조회 개수 (1-100, 기본값: 20)
    """
    try:
        analysis = trading_analyzer.analyze_today_stocks()
        buy_candidates = analysis.get('buy_candidates', [])
        
        # 신뢰도 필터링 및 제한
        filtered = [
            {
                **candidate,
                'signal': 'buy',
                'confidence': min(0.5 + (candidate['avg_sentiment'] * 0.3) + (candidate['avg_overall'] * 0.2), 1.0)
            }
            for candidate in buy_candidates
        ]
        filtered = [c for c in filtered if c['confidence'] >= min_confidence]
        filtered = sorted(filtered, key=lambda x: x['confidence'], reverse=True)[:limit]
        
        return JSONResponse({
            "success": True,
            "count": len(filtered),
            "data": filtered
        })
    except Exception as e:
        logger.error(f"Error getting buy candidates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trading/sell-candidates")
async def get_sell_candidates(
    min_confidence: float = Query(0.5, ge=0.0, le=1.0, description="최소 신뢰도"),
    limit: int = Query(20, ge=1, le=100, description="조회 개수")
):
    """
    매도 후보 종목 조회
    
    - **min_confidence**: 최소 신뢰도 (0.0 ~ 1.0, 기본값: 0.5)
    - **limit**: 조회 개수 (1-100, 기본값: 20)
    """
    try:
        analysis = trading_analyzer.analyze_today_stocks()
        sell_candidates = analysis.get('sell_candidates', [])
        
        # 신뢰도 필터링 및 제한
        filtered = [
            {
                **candidate,
                'signal': 'sell',
                'confidence': min(0.5 + (abs(candidate['avg_sentiment']) * 0.3) + ((1 - candidate['avg_overall']) * 0.2), 1.0)
            }
            for candidate in sell_candidates
        ]
        filtered = [c for c in filtered if c['confidence'] >= min_confidence]
        filtered = sorted(filtered, key=lambda x: x['confidence'], reverse=True)[:limit]
        
        return JSONResponse({
            "success": True,
            "count": len(filtered),
            "data": filtered
        })
    except Exception as e:
        logger.error(f"Error getting sell candidates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def start_api_server(host: str = "127.0.0.1", port: int = 8000):
    """
    API 서버 시작
    
    Args:
        host: 서버 호스트 (기본값: 127.0.0.1)
        port: 서버 포트 (기본값: 8000)
    """
    logger.info(f"Starting NewsQuant API server on http://{host}:{port}")
    logger.info(f"API Documentation: http://{host}:{port}/docs")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
