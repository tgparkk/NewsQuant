"""네이버 테마 스냅샷 — 파서·KST 경계·skip 판정·저장(모의 DB). 실 DB·실 네트워크 접속 0."""
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from news_scraper import theme_snapshot as ts

FIX = Path(__file__).parent / "fixtures" / "naver_theme"
NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


def _load(name):
    with open(FIX / name, encoding="utf-8") as f:
        return json.load(f)


# ── 목록 파싱 ──
def test_list_parse_rows_unique_decimal():
    rows = ts.parse_list_page(_load("th_list_3.json"))
    assert len(rows) == 64
    assert len({r["theme_no"] for r in rows}) == 64
    assert all(isinstance(r["change_rate"], Decimal) for r in rows)
    assert all(isinstance(r["theme_no"], int) for r in rows)


@pytest.mark.parametrize("v", ["", "N/A", None, "  ", "abc"])
def test_change_rate_blank_is_none(v):
    assert ts.parse_change_rate(v) is None


def test_change_rate_decimal():
    assert ts.parse_change_rate("9.38") == Decimal("9.38")
    assert ts.parse_change_rate("-1.2") == Decimal("-1.2")


# ── 상세 파싱 ──
def test_detail_union_586():
    d = _load("th_586.json")  # stocks 3 / map 15
    assert len(d["stocks"]) == 3 and len(d["themeItemInfoMap"]) == 15
    row, members, mismatch = ts.parse_theme_detail([d])
    assert len(members) == 15
    assert mismatch == 12
    assert row["theme_no"] == 586 and row["description"]
    assert row["member_count"] == 15 and row["change_rate"] == Decimal("9.38")
    assert all(len(m["stock_code"]) == 6 and m["stock_code"].isdigit() for m in members)
    assert all(m["reason"] for m in members)
    assert len([m for m in members if m["stock_name"]]) == 3
    assert sum(1 for m in members if m["stock_name"] is None) == 12


def test_detail_big_union_148():
    d = _load("th_big.json")  # stocks 100 / map 148
    row, members, mismatch = ts.parse_theme_detail([d])
    assert len(members) == 148
    assert mismatch == 48
    assert row["theme_no"] == 27


def test_detail_pages_merge():
    d = _load("th_586.json")
    stocks = d["stocks"]
    p1 = dict(d, stocks=stocks[:2])
    p2 = dict(d, stocks=stocks[2:])
    _, members, _ = ts.parse_theme_detail([p1, p2])
    assert len(members) == 15
    assert sum(1 for m in members if m["stock_name"]) == 3


def test_detail_falls_back_to_list_row():
    d = _load("th_586.json")
    d["groupInfo"] = {}
    lr = {"theme_no": 586, "theme_name": "x", "member_count": 15, "change_rate": Decimal("1.0"),
          "rise_count": 1, "fall_count": 0, "steady_count": 0}
    row, _, _ = ts.parse_theme_detail([d], lr)
    assert row["theme_no"] == 586 and row["theme_name"] == "x"


# ── KST 경계 ──
def test_snap_date_kst_boundary():
    assert ts.kst_snap_date(datetime(2026, 10, 5, 15, 30, tzinfo=timezone.utc)) == date(2026, 10, 6)
    assert ts.kst_snap_date(datetime(2026, 10, 5, 14, 59, tzinfo=timezone.utc)) == date(2026, 10, 5)
    kst = timezone(timedelta(hours=9))
    assert ts.kst_snap_date(datetime(2026, 10, 5, 0, 5, tzinfo=kst)) == date(2026, 10, 5)
    with pytest.raises(ValueError):
        ts.kst_snap_date(datetime(2026, 10, 5, 1, 0))


# ── 가짜 클라이언트 / 모의 DB ──
class FakeClient:
    def __init__(self, fail_nos=(), all_fail=False, circuit_on_detail=False):
        self.fail_nos = set(fail_nos)
        self.all_fail = all_fail
        self.circuit_on_detail = circuit_on_detail

    def get_json(self, url):
        if self.all_fail:
            raise ts.FetchError("boom")
        if "/theme?" in url:
            lst = _load("th_list_3.json")
            lst["totalCount"] = len(lst["groups"])  # 한 페이지짜리 목록으로 축소
            return lst, NOW
        if self.circuit_on_detail:
            raise ts.CircuitOpen("open")
        no = int(url.split("/theme/")[1].split("?")[0])
        if no in self.fail_nos:
            raise ts.FetchError("fail %d" % no)
        d = _load("th_586.json")
        d["groupInfo"] = dict(d["groupInfo"], no=no)
        return d, NOW


def _mock_conn(has_ok=False):
    conn = MagicMock()
    cur = MagicMock()
    def fetchone():
        sql = cur.execute.call_args.args[0]
        if "RETURNING run_id" in sql:
            return (7,)
        return (1,) if has_ok else None

    cur.fetchone.side_effect = fetchone
    cur.rowcount = 1
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


def test_skip_when_ok_run_exists():
    conn, cur = _mock_conn(has_ok=True)
    res = ts.run_snapshot(conn, client=FakeClient(), now=NOW)
    assert res.status == "skipped" and res.exit_code == 0
    sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert not any("INSERT" in s for s in sqls)


def test_force_runs_even_with_ok_run(tmp_path):
    conn, _ = _mock_conn(has_ok=True)
    res = ts.run_snapshot(conn, force=True, limit_themes=2, client=FakeClient(),
                          archive_dir=str(tmp_path), now=NOW)
    assert res.status == "ok"


def test_dry_run_no_db_no_archive(tmp_path):
    res = ts.run_snapshot(None, dry_run=True, limit_themes=3, client=FakeClient(),
                          archive_dir=str(tmp_path), now=NOW)
    assert res.status == "ok" and res.n_themes == 3 and res.n_members == 45
    assert list(tmp_path.iterdir()) == []


def test_write_path_counts_and_archive(tmp_path):
    conn, cur = _mock_conn()
    res = ts.run_snapshot(conn, limit_themes=2, client=FakeClient(),
                          archive_dir=str(tmp_path), now=NOW)
    assert res.status == "ok" and res.exit_code == 0 and res.run_id == 7
    assert res.n_inserted_themes == 2 and res.n_inserted_members == 30
    sqls = [c.args[0] for c in cur.execute.call_args_list]
    data_inserts = [s for s in sqls if "INSERT INTO theme_daily" in s or "INSERT INTO theme_member_daily" in s]
    assert len(data_inserts) == 2 + 30
    assert all("ON CONFLICT DO NOTHING" in s for s in data_inserts)
    path = tmp_path / "2026" / "2026-10-05.json.gz"
    assert path.exists()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["list_pages"]) == 1 and len(raw["themes"]) == 2
    # 같은 날 파일이 있으면 덮어쓰지 않는다
    res2 = ts.run_snapshot(conn, force=True, limit_themes=1, client=FakeClient(),
                           archive_dir=str(tmp_path), now=NOW)
    assert (tmp_path / "2026" / "2026-10-05.run7.json.gz").exists()
    assert path.exists() and res2.archive_path.endswith("run7.json.gz")


def test_partial_on_theme_failure(tmp_path):
    conn, _ = _mock_conn()
    first_no = ts.parse_list_page(_load("th_list_3.json"))[0]["theme_no"]
    res = ts.run_snapshot(conn, limit_themes=3, client=FakeClient(fail_nos=[first_no]),
                          archive_dir=str(tmp_path), now=NOW)
    assert res.status == "partial" and res.exit_code == 2
    assert res.n_errors == 1 and res.n_themes == 2


def test_failed_when_list_fails(tmp_path):
    conn, _ = _mock_conn()
    res = ts.run_snapshot(conn, client=FakeClient(all_fail=True), archive_dir=str(tmp_path), now=NOW)
    assert res.status == "failed" and res.exit_code == 1


def test_circuit_open_aborts_as_failed(tmp_path):
    conn, _ = _mock_conn()
    res = ts.run_snapshot(conn, client=FakeClient(circuit_on_detail=True),
                          archive_dir=str(tmp_path), now=NOW)
    assert res.status == "failed" and "회로" in res.note


# ── 클라이언트: 재시도·페이싱 ──
def test_client_retries_then_succeeds():
    sleeps = []
    resp_bad = MagicMock(status_code=500)
    resp_ok = MagicMock(status_code=200)
    resp_ok.json.return_value = {"a": 1}
    session = MagicMock()
    session.get.side_effect = [resp_bad, resp_ok]
    c = ts.NaverThemeClient(session=session, sleep=sleeps.append, clock=lambda: 0.0)
    data, fetched = c.get_json("http://x")
    assert data == {"a": 1} and fetched.tzinfo is not None
    assert 1 in sleeps  # 지수 백오프 2**0


def test_client_permanent_status_not_retried():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=404)
    c = ts.NaverThemeClient(session=session, sleep=lambda s: None, clock=lambda: 0.0)
    with pytest.raises(ts.FetchError):
        c.get_json("http://x")
    assert session.get.call_count == 1


def test_client_paces_at_least_one_second():
    sleeps = []
    resp = MagicMock(status_code=200)
    resp.json.return_value = {}
    session = MagicMock()
    session.get.return_value = resp
    c = ts.NaverThemeClient(session=session, sleep=sleeps.append, clock=lambda: 100.0)
    c.get_json("http://x")
    c.get_json("http://x")
    assert sleeps and sleeps[0] >= 1.0
