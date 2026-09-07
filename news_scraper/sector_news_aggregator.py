"""섹터 뉴스 집계 — 창 계산 · 뉴스→섹터 귀속(경로 A+B) · 기여도 · 집계 (스펙 B §4). DB·로거를 모른다."""
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple

from .sector_keywords import SectorKeywordDict, match_sectors, ROUTE_KW_TITLE, ROUTE_KW_BODY
from .sentiment_analyzer import SentimentAnalyzer
from .english_sentiment_analyzer import EnglishSentimentAnalyzer

# ── 스펙 §4.4 상수 (config.yaml 로 빼지 않는다 — 관례) ──────────────────────
MIN_N = 3                 # 방향 있는 뉴스가 이보다 적으면 score_signed = 0
K_SCALE = 2.0             # score_signed = clip(score_norm / K_SCALE)
W_KW_TITLE = 1.0
W_KW_BODY = 0.5
W_STOCK = 0.7             # related_stocks 노이즈 → 낮춤
MAX_CODES_PER_NEWS = 5    # 초과 = 인사·시황 나열 기사 → 경로 B 건너뜀(건수 보고)
BODY_CHARS = 2000
DIR_EPS = 0.1             # |sentiment| >= 0.1 이면 「방향 있는」 뉴스
TOP_NEWS = 5
DEFAULT_W_SRC = 0.9
MARKET_CLOSE = time(15, 30)
FREEZE_FROM = time(9, 5)  # 평일 09:05~15:30 은 오늘 거래일 점수 동결(봇이 09:00 에 읽은 값 보존)
ROUTE_STOCK = "stock"
_ROUTE_WEIGHT = {ROUTE_KW_TITLE: W_KW_TITLE, ROUTE_KW_BODY: W_KW_BODY, ROUTE_STOCK: W_STOCK}

# 한/영 분석기의 출처 신뢰도를 합친다(한글 쪽이 우선). 없는 출처는 DEFAULT_W_SRC.
SOURCE_CREDIBILITY: Dict[str, float] = {
    **EnglishSentimentAnalyzer.SOURCE_CREDIBILITY,
    **SentimentAnalyzer.SOURCE_CREDIBILITY,
}


# ── 시간 ───────────────────────────────────────────────────────────────────
def next_weekday(d: date) -> date:
    d = d + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def prev_weekday(d: date) -> date:
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def compute_trade_date(now: datetime) -> date:
    """평일 ∧ now < 15:30 → 오늘, 아니면 다음 평일. 공휴일 달력 없음(무시)."""
    if now.weekday() < 5 and now.time() < MARKET_CLOSE:
        return now.date()
    return next_weekday(now.date())


def compute_window(now: datetime) -> Tuple[date, datetime, datetime]:
    """(trade_date, window_start=직전 평일 15:30, window_end=now). D-1 장중 뉴스는 D-1 종가에 반영됐다고 보고 뺀다."""
    trade_date = compute_trade_date(now)
    start = datetime.combine(prev_weekday(trade_date), MARKET_CLOSE)
    return trade_date, start, now


def is_frozen(now: datetime) -> bool:
    """평일 09:05 ≤ t < 15:30 — 쓰지 않는다. UPSERT 가 덮어쓰므로 봇이 09:00 에 읽은 행을 보존해야 §8-① 평가가 된다."""
    return now.weekday() < 5 and FREEZE_FROM <= now.time() < MARKET_CLOSE


def split_related_stocks(raw) -> List[str]:
    """'005930,000660' → ['005930','000660']. 6자리만, 순서 유지, 중복 제거."""
    if not raw:
        return []
    out: List[str] = []
    for part in str(raw).split(","):
        c = part.strip()
        if len(c) == 6 and c not in out:
            out.append(c)
    return out
