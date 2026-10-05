"""네이버 테마 일일 스냅샷 수집기 (가져오기 · 파싱 · 저장).

테마 소속·편입 사유·테마 설명을 매일 «그대로» 찍어 둔다(PIT). 과거 이력 API 가 없어 백필 불가.
설계: docs/theme_snapshot_2026-10-05.md · DDL: docs/theme_snapshot_ddl_2026-10-05.sql

- 기존 수집기·news 표와 무관한 독립 모듈(소비자 연결 0).
- INSERT 는 ON CONFLICT DO NOTHING — 하루의 첫 관측만 남는다(덮어쓰기 0).
"""

import gzip
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .http_guard import AdaptiveDelay, CircuitBreaker, CircuitOpen, is_retryable_status

logger = logging.getLogger(__name__)

LIST_URL = "https://m.stock.naver.com/api/stocks/theme?page={page}&pageSize=100"
DETAIL_URL = "https://m.stock.naver.com/api/stocks/theme/{no}?page={page}&pageSize=100"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://stock.naver.com/market/stock/kr/theme",
    "Accept": "application/json",
}
DEFAULT_ARCHIVE_DIR = "D:/archive/naver-theme-snapshots"
KST = timezone(timedelta(hours=9))  # Asia/Seoul (DST 없음)
REQUEST_TIMEOUT = 20
MAX_ATTEMPTS = 3
MAX_PAGES = 20  # 무한 루프 방어


class FetchError(Exception):
    """요청이 재시도 끝에 실패했다."""


# ───────────────────────── 파싱 ─────────────────────────

def kst_snap_date(now: Optional[datetime] = None) -> date:
    """실행 시작 시각의 Asia/Seoul 날짜."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("tz-aware datetime 이 필요하다")
    return now.astimezone(KST).date()


def parse_change_rate(value: Any) -> Optional[Decimal]:
    """'9.38' → Decimal('9.38') · 빈값/'N/A'/해석불가 → None."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("%", "")
    if not s or s.upper() in ("N/A", "NA", "-"):
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _int_or_none(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _theme_row(group: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "theme_no": int(group["no"]),
        "theme_name": group.get("name") or "",
        "member_count": _int_or_none(group.get("totalCount")),
        "change_rate": parse_change_rate(group.get("changeRate")),
        "rise_count": _int_or_none(group.get("riseCount")),
        "fall_count": _int_or_none(group.get("fallCount")),
        "steady_count": _int_or_none(group.get("steadyCount")),
    }


def parse_list_page(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """목록 한 페이지 → 테마 행 리스트(description 없음)."""
    return [_theme_row(g) for g in payload.get("groups") or []]


def parse_theme_detail(
    pages: List[Dict[str, Any]], list_row: Optional[Dict[str, Any]] = None
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], int]:
    """상세 페이지(들) → (테마 행, 멤버 행 리스트, 어긋남 수).

    멤버 = themeItemInfoMap 키 ∪ stocks[].itemCode. 어긋남 = 한쪽에만 있는 종목코드 수.
    reason = map 값(없으면 None) · stock_name = stocks[].stockName(없으면 None).
    """
    first = pages[0]
    group = first.get("groupInfo") or {}
    row = _theme_row(group) if group.get("no") is not None else dict(list_row or {})
    if list_row:  # groupInfo 에 빠진 값은 목록에서 보충
        for k, v in list_row.items():
            if row.get(k) in (None, "") and v is not None:
                row[k] = v
    row["description"] = first.get("themeDescription") or None

    names: Dict[str, Optional[str]] = {}
    reasons: Dict[str, Optional[str]] = {}
    for p in pages:
        for s in p.get("stocks") or []:
            code = s.get("itemCode")
            if code:
                names[code] = s.get("stockName") or None
        for code, reason in (p.get("themeItemInfoMap") or {}).items():
            reasons[code] = reason or None

    mismatch = len(set(names) ^ set(reasons))
    members = [
        {"stock_code": c, "stock_name": names.get(c), "reason": reasons.get(c)}
        for c in sorted(set(names) | set(reasons))
    ]
    return row, members, mismatch


# ───────────────────────── 가져오기 ─────────────────────────

class NaverThemeClient:
    """요청 간 ≥1초 · 재시도 3회(지수 백오프) · http_guard 재사용."""

    def __init__(self, session=None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 breaker: Optional[CircuitBreaker] = None):
        if session is None:
            import requests
            session = requests.Session()
        self.session = session
        self._sleep = sleep
        self._clock = clock
        self.delay = AdaptiveDelay(base=1.0)
        self.breaker = breaker or CircuitBreaker(threshold=5, cooldown=10 ** 9)
        self._last = None  # type: Optional[float]

    def _pace(self) -> None:
        if self._last is not None:
            wait = self.delay.current() - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def get_json(self, url: str) -> Tuple[Dict[str, Any], datetime]:
        """(응답 JSON, fetched_at tz-aware). 실패 시 FetchError · 회로 열림 시 CircuitOpen."""
        self.breaker.guard()
        last_err = "알 수 없음"
        for attempt in range(MAX_ATTEMPTS):
            self._pace()
            try:
                resp = self.session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                fetched_at = datetime.now(timezone.utc)
                status = resp.status_code
                if status == 200:
                    data = resp.json()
                    self.delay.reward()
                    self.breaker.record_success()
                    return data, fetched_at
                last_err = f"HTTP {status}"
                if status == 429:
                    self.delay.penalize()
                if not is_retryable_status(status):
                    break
            except Exception as e:  # 네트워크·JSON 오류
                last_err = f"{type(e).__name__}: {e}"
            if attempt < MAX_ATTEMPTS - 1:
                self._sleep(2 ** attempt)
        self.breaker.record_failure()
        raise FetchError(f"{url} → {last_err}")


@dataclass
class ThemeData:
    row: Dict[str, Any]
    members: List[Dict[str, Any]]
    mismatch: int
    fetched_at: datetime


@dataclass
class SnapshotResult:
    status: str  # ok | partial | failed | skipped
    snap_date: date
    run_id: Optional[int] = None
    n_themes: int = 0
    n_members: int = 0
    n_inserted_themes: int = 0
    n_inserted_members: int = 0
    n_mismatch_themes: int = 0
    n_mismatch_codes: int = 0
    n_errors: int = 0
    market_status: Optional[str] = None
    note: str = ""
    archive_path: Optional[str] = None
    total_count_expected: Optional[int] = None
    errors: List[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return {"ok": 0, "skipped": 0, "partial": 2}.get(self.status, 1)


def fetch_theme_list(client: NaverThemeClient, raw: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str], int]:
    """목록 전 페이지 → (테마 행, marketStatus, totalCount)."""
    rows: List[Dict[str, Any]] = []
    market_status = None
    total = 0
    for page in range(1, MAX_PAGES + 1):
        payload, fetched_at = client.get_json(LIST_URL.format(page=page))
        raw["list_pages"].append({"page": page, "fetched_at": fetched_at.isoformat(), "response": payload})
        market_status = payload.get("marketStatus") or market_status
        total = int(payload.get("totalCount") or 0)
        rows.extend(parse_list_page(payload))
        if not payload.get("groups") or len(rows) >= total:
            break
    seen, uniq = set(), []
    for r in rows:
        if r["theme_no"] not in seen:
            seen.add(r["theme_no"])
            uniq.append(r)
    return uniq, market_status, total


def fetch_theme_detail(client: NaverThemeClient, list_row: Dict[str, Any], raw: Dict[str, Any]) -> ThemeData:
    """한 테마의 상세(totalCount>100 이면 다음 페이지도)."""
    no = list_row["theme_no"]
    pages: List[Dict[str, Any]] = []
    first_fetched = None
    for page in range(1, MAX_PAGES + 1):
        payload, fetched_at = client.get_json(DETAIL_URL.format(no=no, page=page))
        first_fetched = first_fetched or fetched_at
        pages.append(payload)
        raw["themes"].setdefault(str(no), []).append(
            {"page": page, "fetched_at": fetched_at.isoformat(), "response": payload}
        )
        total = int(payload.get("totalCount") or 0)
        if total <= page * 100 or not payload.get("stocks"):
            break
    row, members, mismatch = parse_theme_detail(pages, list_row)
    return ThemeData(row=row, members=members, mismatch=mismatch, fetched_at=first_fetched)


# ───────────────────────── 저장 ─────────────────────────

class ThemeStore:
    """psycopg2 연결을 받아 run·theme 단위로 쓴다(테스트에서는 모의 연결)."""

    def __init__(self, conn):
        self.conn = conn

    def has_ok_run(self, snap_date: date) -> bool:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM theme_snapshot_run WHERE snap_date = %s AND status = 'ok' LIMIT 1",
                (snap_date,),
            )
            found = cur.fetchone() is not None
        self.conn.commit()
        return found

    def start_run(self, snap_date: date) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO theme_snapshot_run (snap_date, status) VALUES (%s, 'running') RETURNING run_id",
                (snap_date,),
            )
            run_id = cur.fetchone()[0]
        self.conn.commit()
        return run_id

    def insert_theme(self, snap_date: date, run_id: int, t: ThemeData) -> Tuple[int, int]:
        """한 트랜잭션: theme_daily 1행 + theme_member_daily N행. → (넣은 테마 행, 넣은 멤버 행)."""
        r = t.row
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO theme_daily
                       (snap_date, theme_no, theme_name, description, member_count, change_rate,
                        rise_count, fall_count, steady_count, fetched_at, run_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    (snap_date, r["theme_no"], r["theme_name"], r.get("description"),
                     r.get("member_count"), r.get("change_rate"), r.get("rise_count"),
                     r.get("fall_count"), r.get("steady_count"), t.fetched_at, run_id),
                )
                n_theme = max(cur.rowcount, 0)
                n_mem = 0
                for m in t.members:
                    cur.execute(
                        """INSERT INTO theme_member_daily
                           (snap_date, theme_no, stock_code, stock_name, reason, fetched_at, run_id)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT DO NOTHING""",
                        (snap_date, r["theme_no"], m["stock_code"], m["stock_name"],
                         m["reason"], t.fetched_at, run_id),
                    )
                    n_mem += max(cur.rowcount, 0)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return n_theme, n_mem

    def finish_run(self, run_id: int, res: SnapshotResult) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE theme_snapshot_run
                   SET status=%s, n_themes=%s, n_members=%s, n_errors=%s,
                       finished_at=now(), market_status=%s, note=%s
                   WHERE run_id=%s""",
                (res.status, res.n_themes, res.n_members, res.n_errors,
                 res.market_status, res.note, run_id),
            )
        self.conn.commit()


def write_archive(raw: Dict[str, Any], archive_dir: str, snap_date: date, run_id: Optional[int]) -> str:
    """그 실행의 모든 응답을 gzip JSON 하나로. 이미 있으면 .run{run_id} 로(덮어쓰기 0)."""
    d = Path(archive_dir) / f"{snap_date.year:04d}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{snap_date.isoformat()}.json.gz"
    if path.exists():
        path = d / f"{snap_date.isoformat()}.run{run_id}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    return str(path)


# ───────────────────────── 실행 ─────────────────────────

def run_snapshot(
    conn=None,
    *,
    dry_run: bool = False,
    force: bool = False,
    archive_dir: str = DEFAULT_ARCHIVE_DIR,
    limit_themes: Optional[int] = None,
    client: Optional[NaverThemeClient] = None,
    now: Optional[datetime] = None,
) -> SnapshotResult:
    started = now or datetime.now(timezone.utc)
    snap_date = kst_snap_date(started)
    res = SnapshotResult(status="failed", snap_date=snap_date)
    store = None
    if not dry_run:
        if conn is None:
            raise ValueError("dry_run 이 아니면 DB 연결이 필요하다")
        store = ThemeStore(conn)
        if not force and store.has_ok_run(snap_date):
            res.status = "skipped"
            res.note = f"snap_date={snap_date} 에 status='ok' run 이 이미 있어 건너뜀(--force 로 재실행)"
            return res
        res.run_id = store.start_run(snap_date)

    client = client or NaverThemeClient()
    raw: Dict[str, Any] = {
        "snap_date": snap_date.isoformat(),
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
        if not list_rows:
            notes.append("목록 실패 또는 0건")
        else:
            if limit_themes:
                list_rows = list_rows[:limit_themes]
                notes.append(f"--limit-themes {limit_themes}")
            if res.total_count_expected and not limit_themes and len(list_rows) != res.total_count_expected:
                notes.append(f"목록 totalCount={res.total_count_expected} 인데 수집 {len(list_rows)}")
            circuit_open = False
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
                res.n_members += len(td.members)
                if td.mismatch:
                    res.n_mismatch_themes += 1
                    res.n_mismatch_codes += td.mismatch
                    logger.warning("테마 %s: stocks[] 와 themeItemInfoMap 어긋남 %d건",
                                   td.row["theme_no"], td.mismatch)
                if store:
                    try:
                        nt, nm = store.insert_theme(snap_date, res.run_id, td)
                    except Exception as e:
                        res.errors.append(f"테마 {lr['theme_no']} 저장: {type(e).__name__}: {e}")
                        res.n_errors += 1
                        logger.exception("테마 %s 저장 실패", lr["theme_no"])
                        continue
                    res.n_inserted_themes += nt
                    res.n_inserted_members += nm
            if circuit_open:
                notes.append("회로 차단(연속 실패)으로 중단")
        # 상태 판정
        if not list_rows or (res.n_themes == 0) or any("회로" in n for n in notes):
            res.status = "failed"
        elif res.n_errors:
            res.status = "partial"
        else:
            res.status = "ok"

        notes.append(f"관측 테마 {res.n_themes} · 멤버 {res.n_members}")
        if store:
            notes.append(f"이번 실행이 넣은 행: theme_daily {res.n_inserted_themes} · theme_member_daily {res.n_inserted_members}")
        if res.n_mismatch_themes:
            notes.append(f"stocks/map 어긋남 {res.n_mismatch_themes}테마 {res.n_mismatch_codes}종목")
        if res.errors:
            notes.append("오류: " + " | ".join(res.errors[:5]) + (" ..." if len(res.errors) > 5 else ""))
        if not dry_run and raw["list_pages"]:
            try:
                res.archive_path = write_archive(raw, archive_dir, snap_date, res.run_id)
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
