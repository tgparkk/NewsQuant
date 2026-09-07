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
    """'005930,000660' → ['005930','000660']. 6글자만(영숫자 코드 0220WL 등 포함), 순서 유지, 중복 제거."""
    if not raw:
        return []
    out: List[str] = []
    for part in str(raw).split(","):
        c = part.strip()
        if len(c) == 6 and c not in out:
            out.append(c)
    return out


# ── 귀속 ───────────────────────────────────────────────────────────────────
@dataclass
class SectorHit:
    route: str            # 가중치 최대 경로
    routes: List[str]     # 걸린 경로 전부
    matched: str          # 키워드 / 종목코드
    w_match: float


def attribute_news(news: Dict, kwdict: SectorKeywordDict, code_to_sector: Dict[str, str], *,
                   stock_route_enabled: bool, summary: Dict) -> Dict[str, SectorHit]:
    """뉴스 1건 → {섹터: SectorHit}. 경로 A(키워드) + 경로 B(related_stocks→KSIC3). 경로 중복 시 max 가중 하나."""
    result: Dict[str, SectorHit] = {}
    for key, kh in match_sectors(news.get("title"), news.get("content"), kwdict, BODY_CHARS).items():
        result[key] = SectorHit(kh.route, [kh.route], kh.matched, _ROUTE_WEIGHT[kh.route])

    if stock_route_enabled:
        codes = split_related_stocks(news.get("related_stocks"))
        if len(codes) > MAX_CODES_PER_NEWS:
            summary["stock_route_skipped"] = summary.get("stock_route_skipped", 0) + 1
        else:
            for code in codes:
                sec = code_to_sector.get(code)
                if sec is None:
                    continue
                if sec in result:
                    h = result[sec]
                    if ROUTE_STOCK not in h.routes:
                        h.routes.append(ROUTE_STOCK)
                        h.matched = f"{h.matched},{code}"
                    else:
                        h.matched = f"{h.matched},{code}"
                    if W_STOCK > h.w_match:
                        h.w_match = W_STOCK
                        h.route = ROUTE_STOCK
                else:
                    result[sec] = SectorHit(ROUTE_STOCK, [ROUTE_STOCK], code, W_STOCK)
    return result


# ── 집계 ───────────────────────────────────────────────────────────────────
@dataclass
class AggregationResult:
    trade_date: date
    window_start: datetime
    window_end: datetime
    scores: List[Dict] = field(default_factory=list)
    hits: List[Dict] = field(default_factory=list)
    summary: Dict = field(default_factory=dict)


def _to_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def aggregate(news_rows: List[Dict], kwdict: SectorKeywordDict, code_to_sector: Dict[str, str],
              sector_names: Dict[str, str], now: datetime, *, stock_route_enabled: bool = True) -> AggregationResult:
    """스펙 §4.4:
        c(i,s)       = sentiment × w_match × w_src
        n_dir        = |sentiment| >= DIR_EPS 인 뉴스 수 (중립 DART 정형공시는 분모에 안 넣는다)
        score_norm   = Σc / sqrt(max(n_dir,1))
        score_signed = 0 (n_dir < MIN_N) | clip(score_norm / K_SCALE, -1, +1)
    """
    trade_date, ws, we = compute_window(now)
    summary: Dict = {"n_input": len(news_rows), "stock_route_enabled": stock_route_enabled, "stock_route_skipped": 0}
    acc: Dict[str, Dict] = {}
    hits: List[Dict] = []

    for n in news_rows:
        sent = _to_float(n.get("sentiment_score"))
        w_src = SOURCE_CREDIBILITY.get(n.get("source"), DEFAULT_W_SRC)
        per_sector = attribute_news(n, kwdict, code_to_sector, stock_route_enabled=stock_route_enabled, summary=summary)
        for key, h in per_sector.items():
            c = sent * h.w_match * w_src
            a = acc.setdefault(key, {"n_news": 0, "n_dir": 0, "n_kw": 0, "n_stock": 0,
                                     "n_pos": 0, "n_neg": 0, "score_raw": 0.0, "top": []})
            a["n_news"] += 1
            if abs(sent) >= DIR_EPS:
                a["n_dir"] += 1
            if ROUTE_KW_TITLE in h.routes or ROUTE_KW_BODY in h.routes:
                a["n_kw"] += 1
            if ROUTE_STOCK in h.routes:
                a["n_stock"] += 1
            if sent >= DIR_EPS:
                a["n_pos"] += 1
            elif sent <= -DIR_EPS:
                a["n_neg"] += 1
            a["score_raw"] += c
            a["top"].append({"news_id": n.get("news_id"), "title": (n.get("title") or "")[:120],
                             "c": round(c, 4), "route": h.route})
            hits.append({"trade_date": trade_date, "news_id": n.get("news_id"), "sector_key": key,
                         "route": h.route, "routes": ",".join(h.routes), "matched": h.matched[:200],
                         "w_match": h.w_match, "contribution": c})

    scores: List[Dict] = []
    for key, a in acc.items():
        score_norm = a["score_raw"] / math.sqrt(max(a["n_dir"], 1))
        score_signed = 0.0 if a["n_dir"] < MIN_N else _clip(score_norm / K_SCALE)
        top = sorted(a["top"], key=lambda x: abs(x["c"]), reverse=True)[:TOP_NEWS]
        name = kwdict.sectors[key].name if key in kwdict.sectors else sector_names.get(key)
        scores.append({
            "trade_date": trade_date, "sector_key": key, "sector_name": name,
            "window_start": ws, "window_end": we,
            "n_news": a["n_news"], "n_dir": a["n_dir"], "n_kw": a["n_kw"], "n_stock": a["n_stock"],
            "n_pos": a["n_pos"], "n_neg": a["n_neg"],
            "score_raw": a["score_raw"], "score_norm": score_norm, "score_signed": score_signed,
            "top_news": top,
        })
    summary.update({"n_hits": len(hits), "n_sectors": len(scores)})
    return AggregationResult(trade_date, ws, we, scores, hits, summary)
