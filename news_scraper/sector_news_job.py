"""섹터 뉴스 집계 잡 — 오케스트레이션(DB 읽기 → 순수 집계 → DB 쓰기). 스펙 B §4.5.

🔑 예외를 밖으로 내지 않는다(스케줄러를 죽이지 않는다 — _handle_crawler_result 관례).
   항상 summary dict 를 돌려준다.
"""
import logging
import time as _time
from datetime import datetime
from typing import Dict, Optional

import pytz

from .sector_keywords import load_sector_keywords, SectorKeywordError
from .sector_news_aggregator import (
    aggregate, compute_window, is_frozen, prev_weekday, split_related_stocks, MAX_CODES_PER_NEWS,
)

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")


def now_kst_naive() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def run_sector_news_job(db, now: Optional[datetime] = None, kw_path=None) -> Dict:
    """1회 실행. db 는 NewsDatabase(또는 같은 메서드를 가진 대역)."""
    t0 = _time.monotonic()
    now = now or now_kst_naive()
    summary: Dict = {"ok": False, "now": now.isoformat()}
    try:
        trade_date, ws, we = compute_window(now)
        if is_frozen(now):
            summary.update({"ok": True, "frozen": True, "trade_date": trade_date.isoformat()})
            logger.info(f"[섹터뉴스] 동결 구간(09:05~15:30) — trade_date={trade_date} 갱신 생략")
            return summary

        try:
            kwdict = load_sector_keywords(kw_path)
        except (SectorKeywordError, OSError) as e:
            logger.error(f"[섹터뉴스] 사전 로드 실패 — 집계 중단: {e}")
            summary["error"] = f"dict:{e}"
            return summary

        news_rows = db.get_news_in_window(ws, we)

        codes = set()
        for n in news_rows:
            codes.update(split_related_stocks(n.get("related_stocks")))
        code_to_sector: Dict[str, str] = {}
        sector_names: Dict[str, str] = {}
        stock_route_enabled = True
        try:
            code_to_sector, sector_names = db.get_sector_map_as_of(prev_weekday(trade_date), sorted(codes))
        except Exception as e:
            stock_route_enabled = False
            logger.warning(f"[섹터뉴스] 경로 B 비활성 — fn_sector_map_as_of 조회 실패: {type(e).__name__}: {e}")

        result = aggregate(news_rows, kwdict, code_to_sector, sector_names, now,
                           stock_route_enabled=stock_route_enabled)
        for s in result.scores:
            s["dict_version"] = kwdict.version
        n_scores, n_hits = db.write_sector_news_result(trade_date, result.scores, result.hits)

        skipped = result.summary.get("stock_route_skipped", 0)
        ms = int((_time.monotonic() - t0) * 1000)
        summary.update({
            "ok": True, "frozen": False, "trade_date": trade_date.isoformat(),
            "window": [ws.isoformat(), we.isoformat()],
            "n_news": len(news_rows), "n_hits": n_hits, "n_sectors": n_scores,
            "stock_route": stock_route_enabled, "stock_route_skipped": skipped,
            "mapped_codes": len(code_to_sector), "ms": ms,
        })
        logger.info(
            f"[섹터뉴스] trade_date={trade_date} 창={ws:%m-%d %H:%M}~{we:%m-%d %H:%M} "
            f"뉴스 {len(news_rows)} · 귀속 {n_hits} · 섹터 {n_scores} · "
            f"경로B {'on' if stock_route_enabled else 'off'}(매핑 {len(code_to_sector)}/{len(codes)}) · "
            f"절단 {skipped} · {ms}ms"
        )
        if skipped:
            logger.warning(f"[섹터뉴스] related_stocks > {MAX_CODES_PER_NEWS} 로 경로 B 건너뛴 뉴스 {skipped}건")
        return summary
    except Exception as e:
        logger.error(f"[섹터뉴스] 집계 실패: {e}", exc_info=True)
        summary["error"] = f"{type(e).__name__}: {e}"
        return summary
