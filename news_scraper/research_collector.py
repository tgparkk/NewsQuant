"""증권사 리서치 리포트 수집기 (네이버 증권 종목분석 · 가져오기 · 파싱 · 저장).

출처: stock.naver.com 종목분석 리포트 JSON API(최신순, 값은 모두 문자열).
DDL: docs/research_reports_ddl_2026-10-17.sql

- news 표·종목 연결·테마 표와 무관한 독립 경로(🔒 TN1 측정이 읽는 표는 손대지 않는다).
- UPSERT 는 nid 기준. 이미 있는 행은 read_count·updated_at 만 갱신한다
  — first_seen_at·backfilled·본문 필드는 처음 본 그대로(시점 무결성).
- 정방향(스케줄러 30분): 0쪽부터 최대 2쪽, 아는 nid 가 나온 쪽에서 멈춘다.
- 백필(scripts/backfill_research_reports.py): 컷오프 날짜까지 거슬러 가며 없는 nid 만 backfilled=TRUE 로.
- 요청 실패는 재시도 없이 WARNING 한 줄 뒤 반환한다(스케줄러로 예외를 내지 않는다).
"""

from __future__ import annotations

import logging
import re
import time as _time
from collections.abc import Callable, Iterable
from datetime import date
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any

from .base_crawler import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

API_URL = "https://stock.naver.com/api/stockSecurity/researches/v2/company"
HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Referer": "https://stock.naver.com/research/company",
    "Accept": "application/json",
}
REQUEST_TIMEOUT = 10

FORWARD_PAGE_SIZE = 30
FORWARD_MAX_PAGES = 2
BACKFILL_PAGE_SIZE = 50
BACKFILL_SLEEP = 1.0
BACKFILL_CUTOFF = date(2024, 10, 17)  # 2년 — 이 날짜 미만은 넣지 않고 멈춘다

_BIGINT_MAX = 2**63 - 1
_INT_MAX = 2**31 - 1

# INSERT 순서. first_seen_at·updated_at 은 DB 기본값(now()).
COLUMNS = (
    "nid", "write_date", "item_code", "item_name", "broker_code", "broker_name",
    "title", "summary", "goal_price", "opinion_text", "opinion_type", "read_count",
    "backfilled",
)

UPSERT_SQL = f"""
INSERT INTO research_reports ({", ".join(COLUMNS)})
VALUES ({", ".join(["%s"] * len(COLUMNS))})
ON CONFLICT (nid) DO UPDATE SET
    read_count = COALESCE(EXCLUDED.read_count, research_reports.read_count),
    updated_at = now()
RETURNING (xmax = 0) AS inserted
"""

KNOWN_NIDS_SQL = "SELECT nid FROM research_reports WHERE nid = ANY(%s)"

FetchFn = Callable[[int, int], dict[str, Any]]


class ResearchFetchError(Exception):
    """API 요청·응답 해석 실패(재시도하지 않는다)."""


# ───────────────────────── 파싱 ─────────────────────────

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_END_RE = re.compile(r"</(?:p|div|li|h[1-6]|tr)\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(html: str | None) -> str | None:
    """요약 HTML → 일반 텍스트. <br>·문단 끝은 줄바꿈, 줄 안 공백은 하나로, 빈 줄은 버린다."""
    if not html:
        return None
    s = _BR_RE.sub("\n", html)
    s = _BLOCK_END_RE.sub("\n", s)
    s = unescape(_TAG_RE.sub("", s))
    lines = (" ".join(line.split()) for line in s.splitlines())
    text = "\n".join(line for line in lines if line)
    return text or None


def parse_goal_price(value: Any) -> int | None:
    """'120000'·'120,000' → 120000 · 빈값/0/음수/해석불가 → None."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite() or d <= 0 or d > _BIGINT_MAX:
        return None
    return int(d)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _code_or_none(value: Any, max_len: int) -> str | None:
    """열 폭을 넘는 코드는 None — 한 행 때문에 쪽 전체가 롤백되지 않게."""
    s = _str_or_none(value)
    return s if s is not None and len(s) <= max_len else None


def _int_or_none(value: Any) -> int | None:
    s = _str_or_none(value)
    if s is None:
        return None
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return None


def _int_in_range(value: Any, max_value: int) -> int | None:
    """열 범위(0..max)를 벗어나면 None — 한 행 때문에 쪽 전체가 롤백되지 않게."""
    n = _int_or_none(value)
    return n if n is not None and 0 <= n <= max_value else None


def parse_item(item: Any, backfilled: bool = False) -> dict[str, Any] | None:
    """API 항목 1건 → research_reports 행. 필수(nid·제목·작성일)가 없거나 깨지면 None."""
    if not isinstance(item, dict):
        return None
    nid = _int_or_none(item.get("nid"))
    title = _str_or_none(item.get("title"))
    try:
        write_date = date.fromisoformat(str(item.get("writeDate") or "").strip())
    except ValueError:
        return None
    if nid is None or nid <= 0 or title is None:
        return None
    return {
        "nid": nid,
        "write_date": write_date,
        "item_code": _code_or_none(item.get("itemCode"), 12),
        "item_name": _str_or_none(item.get("itemName")),
        "broker_code": _code_or_none(item.get("brokerCode"), 16),
        "broker_name": _str_or_none(item.get("brokerName")),
        "title": title,
        "summary": html_to_text(item.get("content")),
        "goal_price": parse_goal_price(item.get("goalPrice")),
        "opinion_text": _str_or_none(item.get("opinionText")),
        "opinion_type": _str_or_none(item.get("opinionType")),
        "read_count": _int_in_range(item.get("readCount"), _INT_MAX),
        "backfilled": bool(backfilled),
    }


# ───────────────────────── 가져오기 ─────────────────────────

def fetch_page(index: int, size: int, session=None, timeout: float = REQUEST_TIMEOUT) -> dict[str, Any]:
    """한 쪽 요청(재시도 없음). 실패는 모두 ResearchFetchError 로."""
    if session is None:
        import requests
        session = requests
    try:
        resp = session.get(API_URL, params={"index": index, "size": size},
                           headers=HEADERS, timeout=timeout)
    except Exception as e:  # 연결·타임아웃 등
        raise ResearchFetchError(f"요청 실패 index={index}: {type(e).__name__}: {e}") from e
    if resp.status_code != 200:
        raise ResearchFetchError(f"HTTP {resp.status_code} index={index}")
    try:
        payload = resp.json()
    except ValueError as e:
        raise ResearchFetchError(f"JSON 해석 실패 index={index}: {e}") from e
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ResearchFetchError(f"응답 형식 이상 index={index}: items 없음")
    return payload


# ───────────────────────── 저장 ─────────────────────────

def _known_nids(conn, nids: Iterable[int]) -> set[int]:
    nids = list(nids)
    if not nids:
        return set()
    with conn.cursor() as cur:
        cur.execute(KNOWN_NIDS_SQL, (nids,))
        return {int(r[0]) for r in cur.fetchall()}


def _upsert_rows(conn, rows: list[dict[str, Any]]) -> int:
    """행들을 UPSERT 하고 새로 들어간 행 수를 돌려준다(커밋은 호출부)."""
    n_new = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(UPSERT_SQL, tuple(r[c] for c in COLUMNS))
            res = cur.fetchone()
            if res and res[0]:
                n_new += 1
    return n_new


def _parse_page(payload: dict[str, Any], backfilled: bool):
    rows, invalid = [], 0
    for it in payload.get("items") or []:
        row = parse_item(it, backfilled=backfilled)
        if row is None:
            invalid += 1
        else:
            rows.append(row)
    return rows, invalid


def _safe_rollback(conn) -> None:
    try:
        conn.rollback()
    except Exception as e:  # noqa: BLE001 — rollback 실패는 원래 오류를 가리지 않게 삼킨다
        logger.debug(f"[리서치] rollback 실패: {e}")


# ───────────────────────── 정방향 수집 ─────────────────────────

def collect_forward(conn, fetch: FetchFn | None = None,
                    size: int = FORWARD_PAGE_SIZE, max_pages: int = FORWARD_MAX_PAGES) -> dict[str, Any]:
    """0쪽부터 최신 리포트를 넣는다. 예외를 밖으로 내지 않고 항상 요약 dict 를 돌려준다.

    멈춤: 아는 nid 가 있는 쪽을 넣은 뒤 · hasNext=false · max_pages 쪽.
    """
    fetch = fetch or fetch_page
    t0 = _time.monotonic()
    summary: dict[str, Any] = {"ok": False, "requests": 0, "new": 0, "skipped": 0,
                               "invalid": 0, "stop_reason": None}
    try:
        for index in range(max_pages):
            summary["requests"] += 1
            payload = fetch(index, size)
            rows, invalid = _parse_page(payload, backfilled=False)
            summary["invalid"] += invalid
            try:
                known = _known_nids(conn, [r["nid"] for r in rows])
                summary["new"] += _upsert_rows(conn, rows)
                conn.commit()
            except Exception:
                _safe_rollback(conn)
                raise
            summary["skipped"] += len(known)
            if known:
                summary["stop_reason"] = "known_nid"
                break
            if not payload.get("hasNext"):
                summary["stop_reason"] = "no_next"
                break
        else:
            summary["stop_reason"] = "page_cap"
            logger.warning(f"[리서치] {max_pages}쪽 상한까지 아는 리포트가 없음 — 그 뒤 리포트 누락 가능(백필로 메울 것)")
        summary["ok"] = True
    except ResearchFetchError as e:
        summary["error"] = str(e)
        logger.warning(f"[리서치] 요청 실패 — 이번 회차 중단(재시도 없음): {e}")
    except Exception as e:  # noqa: BLE001 — 스케줄러로 예외를 내지 않는다
        summary["error"] = f"{type(e).__name__}: {e}"
        logger.warning(f"[리서치] 수집 실패 — 이번 회차 중단: {summary['error']}")
    summary["ms"] = int((_time.monotonic() - t0) * 1000)
    logger.info(
        f"[리서치] 요청 {summary['requests']} · 신규 {summary['new']} · 생략 {summary['skipped']} · "
        f"무효 {summary['invalid']} · 멈춤 {summary['stop_reason'] or '오류'} · {summary['ms']}ms"
    )
    return summary


# ───────────────────────── 백필 ─────────────────────────

def run_backfill(conn, fetch: FetchFn | None = None, sleep: Callable[[float], None] = _time.sleep,
                 cutoff: date = BACKFILL_CUTOFF, size: int = BACKFILL_PAGE_SIZE,
                 max_pages: int | None = None, dry_run: bool = False,
                 delay: float = BACKFILL_SLEEP) -> dict[str, Any]:
    """0쪽부터 거슬러 가며 없는 nid 만 backfilled=TRUE 로 넣는다(다시 돌려도 안전).

    멈춤: write_date < cutoff 인 항목이 나온 쪽 뒤 · hasNext=false · max_pages · 요청/DB 오류.
    dry_run 이면 쓰지 않는다(conn 이 있으면 아는 nid 조회만).
    """
    fetch = fetch or fetch_page
    summary: dict[str, Any] = {
        "ok": False, "requests": 0, "inserted": 0, "would_insert": 0, "skipped": 0,
        "below_cutoff": 0, "invalid": 0, "last_index": None, "oldest_date": None,
        "stop_reason": None,
    }
    index = 0
    try:
        while True:
            if max_pages is not None and summary["requests"] >= max_pages:
                summary["stop_reason"] = "max_pages"
                break
            if summary["requests"]:
                sleep(delay)
            summary["last_index"] = index
            summary["requests"] += 1
            payload = fetch(index, size)
            rows, invalid = _parse_page(payload, backfilled=True)
            summary["invalid"] += invalid

            in_range = [r for r in rows if r["write_date"] >= cutoff]
            summary["below_cutoff"] += len(rows) - len(in_range)
            if in_range:
                oldest = min(r["write_date"] for r in in_range)
                if summary["oldest_date"] is None or oldest < summary["oldest_date"]:
                    summary["oldest_date"] = oldest

            known = _known_nids(conn, [r["nid"] for r in in_range]) if conn is not None else set()
            fresh = [r for r in in_range if r["nid"] not in known]
            summary["skipped"] += len(in_range) - len(fresh)
            if dry_run:
                summary["would_insert"] += len(fresh)
            elif fresh:
                try:
                    summary["inserted"] += _upsert_rows(conn, fresh)
                    conn.commit()
                except Exception:
                    _safe_rollback(conn)
                    raise

            if len(in_range) < len(rows):
                summary["stop_reason"] = "cutoff"
                break
            if not payload.get("hasNext"):
                summary["stop_reason"] = "no_next"
                break
            index += 1
        summary["ok"] = True
    except ResearchFetchError as e:
        summary["error"] = str(e)
        logger.warning(f"[리서치 백필] 요청 실패 — 중단(재시도 없음): {e}")
    except Exception as e:  # noqa: BLE001 — 요약을 돌려주고 종료 코드로 알린다
        summary["error"] = f"{type(e).__name__}: {e}"
        logger.error(f"[리서치 백필] 실패 — 중단: {summary['error']}")
    return summary
