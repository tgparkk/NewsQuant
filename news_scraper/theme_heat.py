"""네이버 테마 «열기»(등락률·상승/하락/보합 수) 장 마감 뒤 수집.

08:00 소속 스냅샷(theme_snapshot.py)은 장 전이라 등락률이 0 으로 초기화돼 열기를 못 담는다.
이 모듈은 마감 뒤(NXT 20:00 종료 · 종가 갱신 20:20) 값이 확정된 시점에 별도 표 theme_heat_daily 에 찍는다.
DDL: docs/theme_heat_ddl_2026-10-07.sql

- 08:00 경로(theme_snapshot.py)와 기존 3표는 건드리지 않는다. 가져오기 클라이언트·파서만 재사용(단방향 의존).
- 값은 «마감 확정 응답»일 때만 저장한다: marketStatus=CLOSE · 장 전 초기화 아님 · 기준일(종목 localTradedAt 최빈 날짜)=snap_date.
- INSERT 는 ON CONFLICT DO NOTHING — 하루의 첫 확정 관측만 남는다(덮어쓰기 0).
"""

import gzip
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from .http_guard import CircuitOpen
from .theme_snapshot import (
    DEFAULT_ARCHIVE_DIR,
    FetchError,
    NaverThemeClient,
    ThemeData,
    fetch_theme_detail,
    fetch_theme_list,
    kst_snap_date,
    parse_change_rate,
    parse_theme_detail,
)

logger = logging.getLogger(__name__)

CLOSED = "CLOSE"
STALE_ABORT_AFTER = 3  # 확정 값이 하나도 없는 채로 이 수만큼 테마가 연속 부적격이면 나머지를 돌지 않는다


# ───────────────────────── 파싱 ─────────────────────────

def _basis_date(stocks: List[Dict[str, Any]]) -> Optional[date]:
    """응답의 기준일 = 구성종목 localTradedAt 날짜의 최빈값(거래정지 종목 한두 개에 흔들리지 않게)."""
    days = Counter((s.get("localTradedAt") or "")[:10] for s in stocks)
    days.pop("", None)
    if not days:
        return None
    try:
        return date.fromisoformat(days.most_common(1)[0][0])
    except ValueError:
        return None


def _calc_change_rate(stocks: List[Dict[str, Any]], member_count: Optional[int]) -> Optional[Decimal]:
    """구성종목 fluctuationsRatio 의 동일가중 평균(네이버 changeRate 와 2026-10-05 보관본 264테마 전부 ±0.01 일치).

    종목이 일부만 왔거나(member_count 불일치) 값이 비면 평균을 내지 않는다.
    """
    rates = [parse_change_rate(s.get("fluctuationsRatio")) for s in stocks]
    if not rates or any(r is None for r in rates) or member_count != len(rates):
        return None
    return (sum(rates) / len(rates)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_heat(pages: List[Dict[str, Any]], list_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """상세 페이지(들) → 열기 행. valid = 마감 확정 응답(CLOSE · 장 전 초기화 아님)."""
    row, _members, _mismatch = parse_theme_detail(pages, list_row)
    stocks = [s for p in pages for s in p.get("stocks") or []]
    market_status = pages[0].get("marketStatus")
    return {
        "theme_no": row["theme_no"],
        "theme_name": row.get("theme_name") or "",
        "member_count": row.get("member_count"),
        "change_rate": row.get("change_rate"),
        "rise_count": row.get("rise_count"),
        "fall_count": row.get("fall_count"),
        "steady_count": row.get("steady_count"),
        "list_change_rate": (list_row or {}).get("change_rate"),
        "calc_change_rate": _calc_change_rate(stocks, row.get("member_count")),
        "market_status": market_status,
        "basis_date": _basis_date(stocks),
        "metrics_reset": row["metrics_reset"],
        "valid": market_status == CLOSED and not row["metrics_reset"] and row.get("change_rate") is not None,
    }


# ───────────────────────── 저장 ─────────────────────────

@dataclass
class HeatResult:
    status: str  # ok | partial | failed | skipped
    snap_date: date
    run_id: Optional[int] = None
    n_themes: int = 0
    n_inserted: int = 0
    n_errors: int = 0
    market_status: Optional[str] = None
    basis_date: Optional[date] = None
    note: str = ""
    archive_path: Optional[str] = None
    total_count_expected: Optional[int] = None
    errors: List[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return {"ok": 0, "skipped": 0, "partial": 2}.get(self.status, 1)


class HeatStore:
    """psycopg2 연결을 받아 theme_heat_run · theme_heat_daily 에만 쓴다(테스트에서는 모의 연결)."""

    def __init__(self, conn):
        self.conn = conn

    def has_ok_run(self, snap_date: date) -> bool:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM theme_heat_run WHERE snap_date = %s AND status = 'ok' LIMIT 1",
                (snap_date,),
            )
            found = cur.fetchone() is not None
        self.conn.commit()
        return found

    def start_run(self, snap_date: date) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO theme_heat_run (snap_date, status) VALUES (%s, 'running') RETURNING run_id",
                (snap_date,),
            )
            run_id = cur.fetchone()[0]
        self.conn.commit()
        return run_id

    def insert_heat(self, snap_date: date, run_id: int, h: Dict[str, Any], fetched_at: datetime) -> int:
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO theme_heat_daily
                       (snap_date, theme_no, theme_name, member_count, change_rate,
                        rise_count, fall_count, steady_count, list_change_rate, calc_change_rate,
                        basis_date, market_status, fetched_at, run_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    (snap_date, h["theme_no"], h["theme_name"], h["member_count"], h["change_rate"],
                     h["rise_count"], h["fall_count"], h["steady_count"], h["list_change_rate"],
                     h["calc_change_rate"], h["basis_date"], h["market_status"], fetched_at, run_id),
                )
                n = max(cur.rowcount, 0)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return n

    def finish_run(self, run_id: int, res: HeatResult) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE theme_heat_run
                   SET status=%s, n_themes=%s, n_inserted=%s, n_errors=%s,
                       finished_at=now(), market_status=%s, basis_date=%s, note=%s
                   WHERE run_id=%s""",
                (res.status, res.n_themes, res.n_inserted, res.n_errors,
                 res.market_status, res.basis_date, res.note, run_id),
            )
        self.conn.commit()


def write_heat_archive(raw: Dict[str, Any], archive_dir: str, snap_date: date, run_id: Optional[int]) -> str:
    """원본 응답 gzip JSON. 08:00 보관본(YYYY-MM-DD.json.gz)과 이름이 다르고, 있으면 .heat.run{id} 로(덮어쓰기 0)."""
    d = Path(archive_dir) / f"{snap_date.year:04d}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{snap_date.isoformat()}.heat.json.gz"
    if path.exists():
        path = d / f"{snap_date.isoformat()}.heat.run{run_id}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    return str(path)


# ───────────────────────── 실행 ─────────────────────────

def _fetch_pages(td: ThemeData, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [p["response"] for p in raw["themes"][str(td.row["theme_no"])]]


def run_heat(
    conn=None,
    *,
    dry_run: bool = False,
    force: bool = False,
    archive_dir: str = DEFAULT_ARCHIVE_DIR,
    limit_themes: Optional[int] = None,
    client: Optional[NaverThemeClient] = None,
    now: Optional[datetime] = None,
) -> HeatResult:
    started = now or datetime.now(timezone.utc)
    snap_date = kst_snap_date(started)
    res = HeatResult(status="failed", snap_date=snap_date)
    store = None
    if not dry_run:
        if conn is None:
            raise ValueError("dry_run 이 아니면 DB 연결이 필요하다")
        store = HeatStore(conn)
        if not force and store.has_ok_run(snap_date):
            res.status = "skipped"
            res.note = f"snap_date={snap_date} 에 status='ok' 열기 run 이 이미 있어 건너뜀(--force 로 재실행)"
            return res
        res.run_id = store.start_run(snap_date)

    client = client or NaverThemeClient()
    raw: Dict[str, Any] = {
        "snap_date": snap_date.isoformat(),
        "kind": "heat",
        "started_at": started.isoformat(),
        "list_pages": [],
        "themes": {},
    }
    notes: List[str] = []
    try:
        try:
            list_rows, res.market_status, res.total_count_expected = fetch_theme_list(client, raw)
        except (FetchError, CircuitOpen) as e:
            res.errors.append(f"목록: {e}")
            res.n_errors += 1
            list_rows = []

        skipped_reason = None
        if not list_rows:
            notes.append("목록 실패 또는 0건")
        elif res.market_status != CLOSED:
            skipped_reason = f"마감 전(marketStatus={res.market_status}) — 값이 확정되지 않아 저장 안 함"
        else:
            if limit_themes:
                list_rows = list_rows[:limit_themes]
                notes.append(f"--limit-themes {limit_themes}")
            if res.total_count_expected and not limit_themes and len(list_rows) != res.total_count_expected:
                notes.append(f"목록 totalCount={res.total_count_expected} 인데 수집 {len(list_rows)}")
            circuit_open = False
            n_ineligible = 0
            for lr in list_rows:
                try:
                    td = fetch_theme_detail(client, lr, raw)
                except CircuitOpen as e:
                    res.errors.append(f"테마 {lr['theme_no']}: {e}")
                    res.n_errors += 1
                    circuit_open = True
                    break
                except FetchError as e:
                    res.errors.append(f"테마 {lr['theme_no']}: {e}")
                    res.n_errors += 1
                    logger.warning("테마 %s 실패: %s", lr["theme_no"], e)
                    continue
                res.n_themes += 1
                h = parse_heat(_fetch_pages(td, raw), lr)
                res.basis_date = res.basis_date or h["basis_date"]
                why = None
                if h["market_status"] != CLOSED:
                    why = f"marketStatus={h['market_status']}"
                elif h["metrics_reset"] or h["change_rate"] is None:
                    why = "장 전 초기화/값 없음"
                elif h["basis_date"] != snap_date:
                    why = f"기준일 {h['basis_date']} ≠ snap_date {snap_date}"
                if why:
                    n_ineligible += 1
                    if res.n_inserted == 0 and n_ineligible >= STALE_ABORT_AFTER:
                        skipped_reason = f"확정 값 없음(휴장일·미확정 의심) — {why} · 첫 {n_ineligible}테마 부적격으로 중단"
                        break
                    res.errors.append(f"테마 {lr['theme_no']} 부적격: {why}")
                    res.n_errors += 1
                    continue
                n_ineligible = 0
                if store:
                    try:
                        res.n_inserted += store.insert_heat(snap_date, res.run_id, h, td.fetched_at)
                    except Exception as e:
                        res.errors.append(f"테마 {lr['theme_no']} 저장: {type(e).__name__}: {e}")
                        res.n_errors += 1
                        logger.exception("테마 %s 저장 실패", lr["theme_no"])
                else:
                    res.n_inserted += 1  # dry-run: 저장했을 행 수
            if circuit_open:
                notes.append("회로 차단(연속 실패)으로 중단")

        # 상태 판정
        if skipped_reason:
            res.status = "skipped"
            notes.append(skipped_reason)
        elif not list_rows or res.n_themes == 0 or any("회로" in n for n in notes):
            res.status = "failed"
        elif res.n_inserted == 0:
            res.status = "failed"
            notes.append("확정 값 0행")
        elif res.n_errors:
            res.status = "partial"
        else:
            res.status = "ok"

        notes.append(f"관측 테마 {res.n_themes} · 저장 {res.n_inserted} · 기준일 {res.basis_date}")
        if res.errors:
            notes.append("오류: " + " | ".join(res.errors[:5]) + (" ..." if len(res.errors) > 5 else ""))
        if not dry_run and res.n_themes:
            try:
                res.archive_path = write_heat_archive(raw, archive_dir, snap_date, res.run_id)
                notes.append(f"보관: {res.archive_path}")
            except Exception as e:
                notes.append(f"보관 실패: {type(e).__name__}: {e}")
                logger.exception("원본 보관 실패")
        res.note = " ; ".join(notes)
        if store:
            store.finish_run(res.run_id, res)
        return res
    except Exception as e:
        if store and res.run_id:
            res.status = "failed"
            res.note = f"예외: {type(e).__name__}: {e}"
            try:
                conn.rollback()
                store.finish_run(res.run_id, res)
            except Exception:
                logger.exception("run 행 갱신 실패")
        raise
