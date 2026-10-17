"""증권사 리서치 리포트 수집기 — 파싱·UPSERT 규칙·정방향 중단 규칙·백필(모의 DB). 실 DB·실 네트워크 접속 0."""
import copy
import json
import logging
import re
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest

from news_scraper import research_collector as rc

FIX = Path(__file__).parent / "fixtures" / "naver_research"


def _load(name):
    with open(FIX / name, encoding="utf-8") as f:
        return json.load(f)


def _item(nid, write_date="2026-10-16", **over):
    """실 응답 첫 항목을 틀로 nid·날짜만 바꾼 항목(값은 모두 문자열 — API 와 같다)."""
    it = copy.deepcopy(_load("company_index0_size5.json")["items"][0])
    it.update(nid=str(nid), writeDate=write_date, **over)
    return it


def _page(items, has_next=True):
    return {"hasNext": has_next, "totalCount": "88824", "items": items}


# ── 가짜 DB / 가짜 fetch ──
class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("db boom")
        if "to_regclass" in sql:
            self._result = [("research_reports" if self.conn.has_table else None,)]
        elif "max(write_date)" in sql:
            dates = [r["write_date"] for r in self.conn.table.values() if r.get("write_date")]
            self._result = [(max(dates) if dates else None,)]
        elif sql.lstrip().upper().startswith("SELECT NID FROM RESEARCH_REPORTS"):
            wanted = set(params[0])
            self._result = [(n,) for n in sorted(wanted & set(self.conn.table))]
        elif "INSERT INTO research_reports" in sql:
            row = dict(zip(rc.COLUMNS, params))
            inserted = row["nid"] not in self.conn.table
            if inserted:
                self.conn.table[row["nid"]] = row
            else:  # ON CONFLICT 흉내: read_count 만
                self.conn.table[row["nid"]]["read_count"] = row["read_count"]
            self.conn.inserted_rows.append(row)
            self._result = [(inserted,)]
        else:
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result or [])


class FakeConn:
    def __init__(self, known=(), fail_on=None, has_table=True, known_date=None):
        self.table = {n: {"nid": n, "write_date": known_date} for n in known}
        self.executed = []
        self.inserted_rows = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_on = fail_on
        self.has_table = has_table
        self.borrowed = False
        self.borrows = 0

    @contextmanager
    def borrow(self):
        """풀에서 잠깐 빌리는 연결 흉내 — 빌린 동안 borrowed=True."""
        assert not self.borrowed, "연결을 겹쳐 빌렸다"
        self.borrowed = True
        self.borrows += 1
        try:
            yield self
        finally:
            self.borrowed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeFetch:
    """index → 페이지(dict) 또는 예외. 호출 기록을 남긴다."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, index, size):
        self.calls.append((index, size))
        p = self.pages[index]
        if isinstance(p, Exception):
            raise p
        return p


class FakeFeed:
    """실제 API 처럼 전체 목록(최신 nid 먼저)을 index·size 로 잘라 준다(쪽 크기를 바꿔도 겹침이 재현된다)."""

    def __init__(self, items, max_size=50):
        self.items = items
        self.max_size = max_size
        self.calls = []

    def __call__(self, index, size):
        self.calls.append((index, size))
        if size > self.max_size:
            raise rc.ResearchFetchError("HTTP 400 too_big")
        chunk = self.items[index * size:(index + 1) * size]
        return _page(chunk, has_next=(index + 1) * size < len(self.items))


def _feed_items(n, start_nid=5000, start_date=date(2026, 10, 16), per_day=None):
    """nid 내림차순 항목 n 개. per_day 를 주면 그 개수마다 하루씩 과거로."""
    out = []
    for i in range(n):
        d = start_date - timedelta(days=(i // per_day) if per_day else 0)
        out.append(_item(start_nid - i, d.isoformat()))
    return out


def _fwd(conn, fetch, sleeps=None, **kw):
    """정방향 수집 — 잠은 기록만 하고, 잘 때 연결을 빌리고 있지 않은지 확인한다."""
    def sleep(sec):
        assert not conn.borrowed, "잠자는 동안 연결을 쥐고 있다"
        if sleeps is not None:
            sleeps.append(sec)
    return rc.collect_forward(conn.borrow, fetch=fetch, sleep=sleep, **kw)


@pytest.fixture(autouse=True)
def _reset_table_state():
    rc._TABLE_STATE.update(ready=False, warned=False)
    yield
    rc._TABLE_STATE.update(ready=False, warned=False)


def _pages_desc(n_pages, per_page, start_nid=1000, dates=None, last_has_next=True):
    """nid 내림차순 페이지들. dates[i] = i번째 페이지 항목 날짜."""
    pages, nid = [], start_nid
    for i in range(n_pages):
        d = (dates or ["2026-10-16"] * n_pages)[i]
        items = []
        for _ in range(per_page):
            items.append(_item(nid, d))
            nid -= 1
        pages.append(_page(items, has_next=(i < n_pages - 1) or last_has_next))
    return pages


# ── 파싱 ──
def test_parse_real_fixture_rows():
    items = _load("company_index0_size5.json")["items"]
    rows = [rc.parse_item(it) for it in items]
    r = rows[0]
    assert r["nid"] == 96804 and isinstance(r["nid"], int)
    assert r["write_date"] == date(2026, 10, 16)
    assert r["item_code"] == "034020" and r["item_name"] == "두산에너빌리티"
    assert r["broker_code"] == "57" and r["broker_name"] == "하나증권"
    assert r["title"] == "연내 SMR 추가 수주 기대"
    assert r["goal_price"] == 120000 and r["read_count"] == 8549
    assert r["opinion_text"] == "Buy" and r["opinion_type"] == "buy"
    assert r["backfilled"] is False
    assert set(r) == set(rc.COLUMNS)
    assert all(row is not None for row in rows)


def test_parse_summary_html_stripped_with_line_breaks():
    r = rc.parse_item(_load("company_index0_size5.json")["items"][0])
    s = r["summary"]
    assert "<" not in s and ">" not in s
    lines = s.split("\n")
    assert lines[0] == "목표주가 120,000원으로 하향, 투자의견 매수 유지"
    assert lines[1].startswith("두산에너빌리티 목표주가")
    assert all(line == line.strip() and line for line in lines)


def test_parse_summary_br_and_entities():
    # 실 응답 4번째 항목: <br> 로 나뉜 문단 + R&amp;D
    r = rc.parse_item(_load("company_index0_size5.json")["items"][3])
    assert "R&D" in r["summary"] and "&amp;" not in r["summary"]
    assert len(r["summary"].split("\n")) >= 3


@pytest.mark.parametrize("html, expected", [
    ("<p>a</p><p>b<br/>c</p>", "a\nb\nc"),
    ("<p>  x &nbsp; y </p>", "x y"),
    ("<p><br></p>", None),
    ("", None),
    (None, None),
    ("plain", "plain"),
])
def test_html_to_text(html, expected):
    assert rc.html_to_text(html) == expected


@pytest.mark.parametrize("v, expected", [
    ("120000", 120000),
    ("120,000", 120000),
    (" 5000 ", 5000),
    ("0", None),
    ("", None),
    (None, None),
    ("-100", None),
    ("N/A", None),
    ("abc", None),
    ("1.5e3", 1500),
    ("NaN", None),
    ("1e30", None),  # BIGINT 넘침
])
def test_goal_price_edge_cases(v, expected):
    assert rc.parse_goal_price(v) == expected


def test_parse_missing_optional_fields_are_none():
    it = {"nid": "5", "title": " 제목 ", "writeDate": "2026-10-16"}
    r = rc.parse_item(it)
    assert r["nid"] == 5 and r["title"] == "제목"
    for k in ("item_code", "item_name", "broker_code", "broker_name", "summary",
              "goal_price", "opinion_text", "opinion_type", "read_count"):
        assert r[k] is None, k


def test_parse_empty_strings_become_none():
    r = rc.parse_item(_item(7, itemCode="", itemName="", brokerName=" ", opinionText="",
                            opinionType="", readCount="", goalPrice="", content=""))
    assert r["item_code"] is None and r["item_name"] is None and r["broker_name"] is None
    assert r["opinion_text"] is None and r["opinion_type"] is None
    assert r["read_count"] is None and r["goal_price"] is None and r["summary"] is None


@pytest.mark.parametrize("bad", [
    {"nid": "", "title": "t", "writeDate": "2026-10-16"},
    {"nid": "x", "title": "t", "writeDate": "2026-10-16"},
    {"title": "t", "writeDate": "2026-10-16"},
    {"nid": "1", "title": "", "writeDate": "2026-10-16"},
    {"nid": "1", "writeDate": "2026-10-16"},
    {"nid": "1", "title": "t", "writeDate": "2026/10/16"},
    {"nid": "1", "title": "t"},
    "not a dict",
])
def test_parse_invalid_required_returns_none(bad):
    assert rc.parse_item(bad) is None


def test_parse_overlong_code_is_none():
    r = rc.parse_item(_item(8, itemCode="X" * 13, brokerCode="9" * 17))
    assert r["item_code"] is None and r["broker_code"] is None


@pytest.mark.parametrize("v, expected", [("8,549", 8549), ("-1", None), (str(2**31), None), ("x", None)])
def test_read_count_range(v, expected):
    assert rc.parse_item(_item(10, readCount=v))["read_count"] == expected


def test_parse_backfilled_flag():
    assert rc.parse_item(_item(9), backfilled=True)["backfilled"] is True


# ── UPSERT 규칙(시점 무결성) ──
def test_upsert_only_updates_read_count_and_updated_at():
    sql = " ".join(rc.UPSERT_SQL.split())
    assert "INSERT INTO research_reports" in sql
    assert "ON CONFLICT (nid) DO UPDATE SET" in sql
    set_clause = sql.split("DO UPDATE SET", 1)[1].split("RETURNING", 1)[0]
    assigned = set(re.findall(r"(\w+)\s*=", set_clause))
    assert assigned == {"read_count", "updated_at"}
    for col in ("first_seen_at", "backfilled", "title", "summary", "goal_price", "write_date"):
        assert col not in set_clause


def test_upsert_columns_match_placeholders():
    sql = rc.UPSERT_SQL
    assert sql.count("%s") == len(rc.COLUMNS)
    for col in rc.COLUMNS:
        assert col in sql
    assert "first_seen_at" not in sql.split("ON CONFLICT")[0]


def test_ddl_file_matches_columns_and_never_touches_news():
    ddl = (Path(__file__).parent.parent / "docs" / "research_reports_ddl_2026-10-17.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE research_reports" in ddl
    for col in rc.COLUMNS + ("first_seen_at", "updated_at"):
        assert re.search(rf"^\s*{col}\s", ddl, re.MULTILINE), col
    assert "nid" in ddl and "PRIMARY KEY" in ddl
    assert re.search(r"\(item_code,\s*write_date\)", ddl)
    assert re.search(r"\(write_date\)", ddl)
    code = re.sub(r"--[^\n]*", "", ddl)  # 주석 제외
    for forbidden in ("news_stock", "related_stocks", "theme_", " news "):
        assert forbidden not in code


def test_module_never_touches_news_tables():
    src = Path(rc.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))
    for forbidden in ("INTO news", "FROM news", "news_stock", "related_stocks", "insert_news", "theme_"):
        assert forbidden not in code


# ── fetch_page ──
class FakeResp:
    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        if self.exc:
            raise self.exc
        return self.resp


def test_fetch_page_sends_headers_and_params():
    payload = _load("company_index0_size5.json")
    s = FakeSession(FakeResp(200, payload))
    assert rc.fetch_page(3, 30, session=s) == payload
    call = s.calls[0]
    assert call["url"] == rc.API_URL
    assert call["params"] == {"index": 3, "size": 30}
    assert call["headers"]["Referer"] == "https://stock.naver.com/research/company"
    assert "Mozilla/5.0" in call["headers"]["User-Agent"]
    assert 0 < call["timeout"] <= 15


@pytest.mark.parametrize("session", [
    FakeSession(FakeResp(500, {"x": 1})),
    FakeSession(FakeResp(403, {"x": 1})),
    FakeSession(FakeResp(200, None, text="<html>")),
    FakeSession(FakeResp(200, {"hasNext": False})),          # items 없음
    FakeSession(FakeResp(200, {"items": "nope"})),           # items 가 리스트가 아님
    FakeSession(FakeResp(200, ["a"])),                       # dict 가 아님
    FakeSession(exc=OSError("timeout")),
])
def test_fetch_page_errors_raise_fetch_error(session):
    with pytest.raises(rc.ResearchFetchError):
        rc.fetch_page(0, 30, session=session)
    assert len(session.calls) == 1  # 재시도 없음


# ── 정방향 수집 ──
def test_forward_stops_after_page_with_known_nid():
    pages = _pages_desc(3, 30, start_nid=1000)
    conn = FakeConn(known={985, 984})  # 첫 페이지 안(1000..971)
    fetch = FakeFetch(pages)
    res = _fwd(conn, fetch)
    assert fetch.calls == [(0, 30)]
    assert res["new"] == 28 and res["skipped"] == 2
    assert res["stop_reason"] == "known_nid"
    assert conn.commits >= 1


def test_forward_known_nid_on_second_page_sleeps_between_pages():
    pages = _pages_desc(3, 30, start_nid=1000)
    conn, sleeps = FakeConn(known={960}), []
    fetch = FakeFetch(pages)
    res = _fwd(conn, fetch, sleeps)
    assert fetch.calls == [(0, 30), (1, 30)]
    assert res["new"] == 59 and res["skipped"] == 1 and res["stop_reason"] == "known_nid"
    assert sleeps == [1.0]  # 요청 사이에만


def test_forward_stops_when_has_next_false():
    pages = _pages_desc(1, 5, last_has_next=False) + _pages_desc(1, 5, start_nid=500)
    fetch = FakeFetch(pages)
    res = _fwd(FakeConn(), fetch)
    assert fetch.calls == [(0, 30)]
    assert res["new"] == 5 and res["stop_reason"] == "no_next"


def test_forward_known_rows_update_read_count_only():
    conn = FakeConn()
    conn.table[1000] = {"nid": 1000, "title": "옛 제목", "backfilled": True, "read_count": 1}
    _fwd(conn, FakeFetch(_pages_desc(1, 3, start_nid=1000)))
    row = conn.table[1000]
    assert row["title"] == "옛 제목" and row["backfilled"] is True
    assert row["read_count"] == 8549


def test_forward_invalid_items_are_counted_not_inserted():
    items = [_item(1000), {"nid": "", "title": "x"}, _item(999)]
    res = _fwd(FakeConn(), FakeFetch([_page(items, has_next=False)]))
    assert res["new"] == 2 and res["invalid"] == 1


def test_forward_does_not_hold_connection_while_fetching():
    conn = FakeConn(known={960})
    inner = FakeFetch(_pages_desc(3, 30, start_nid=1000))

    def fetch(index, size):
        assert not conn.borrowed, "요청 중에 연결을 쥐고 있다"
        return inner(index, size)

    res = _fwd(conn, fetch)
    assert res["ok"] is True and conn.borrows >= 3  # 표 확인·최근 날짜 + 쪽마다 짧게


def test_forward_fetch_error_warns_once_and_returns(caplog):
    fetch = FakeFetch([rc.ResearchFetchError("HTTP 503")])
    conn = FakeConn()
    with caplog.at_level(logging.INFO, logger="news_scraper.research_collector"):
        res = _fwd(conn, fetch)
    assert res["ok"] is False and "503" in res["error"]
    assert res["requests"] == 1 and res["new"] == 0
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert not [s for s, _ in conn.executed if "INSERT" in s]


def test_forward_error_on_second_page_keeps_first_page():
    pages = _pages_desc(1, 30) + [rc.ResearchFetchError("timeout")]
    conn = FakeConn()
    res = _fwd(conn, FakeFetch(pages))
    assert res["ok"] is False and res["new"] == 30 and len(conn.table) == 30
    assert conn.commits == 1


def test_forward_unexpected_exception_never_raises():
    def boom(index, size):
        raise KeyError("weird")
    res = _fwd(FakeConn(), boom)
    assert res["ok"] is False and "KeyError" in res["error"]


def test_forward_db_error_rolls_back_and_returns():
    conn = FakeConn(fail_on="INSERT INTO research_reports")
    res = _fwd(conn, FakeFetch(_pages_desc(2, 30)))
    assert res["ok"] is False and conn.rollbacks == 1 and conn.commits == 0


def test_forward_logs_one_info_summary_line(caplog):
    conn = FakeConn(known={985})
    with caplog.at_level(logging.INFO, logger="news_scraper.research_collector"):
        _fwd(conn, FakeFetch(_pages_desc(2, 30)))
    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 1
    assert "요청 1" in infos[0] and "신규 29" in infos[0] and "생략 1" in infos[0]


# ── 따라잡기(밤·주말 밀린 리포트) ──
def test_catchup_inserts_all_120_new_then_stops_at_known(caplog):
    items = _feed_items(300, start_nid=5000)
    known = {5000 - i for i in range(120, 300)}  # 121번째부터는 이미 있다
    conn, sleeps = FakeConn(known=known, known_date=date(2026, 10, 16)), []
    feed = FakeFeed(items)
    with caplog.at_level(logging.INFO, logger="news_scraper.research_collector"):
        res = _fwd(conn, feed, sleeps)
    # 30건×2쪽 뒤 50건 쪽으로 — 60 // 50 = 1 쪽부터(겹침 10건은 이번 회차 것이라 「아는 nid」 아님)
    assert feed.calls == [(0, 30), (1, 30), (1, 50), (2, 50)]
    assert res["ok"] is True and res["new"] == 120 and res["stop_reason"] == "known_nid"
    assert {5000 - i for i in range(120)} <= set(conn.table)
    assert res["catchup_pages"] == 2
    assert sleeps == [1.0, 1.0, 1.0]
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert all(size <= 50 for _, size in feed.calls)


def test_catchup_stops_at_7_day_bound():
    # 하루 20건씩 과거로 · 표의 최근 작성일 10-16 → 10-09 보다 오래된 항목이 나온 쪽 뒤 멈춤
    items = _feed_items(1000, start_nid=5000, per_day=20)
    conn = FakeConn(known={1}, known_date=date(2026, 10, 16))
    feed = FakeFeed(items)
    res = _fwd(conn, feed)
    # 50건 쪽 3(150..199) 의 가장 오래된 항목 = 10-16 - 9일 = 10-07 < 10-09
    assert feed.calls == [(0, 30), (1, 30), (1, 50), (2, 50), (3, 50)]
    assert res["ok"] is True and res["stop_reason"] == "date_bound"
    assert res["new"] == 200


def test_catchup_page_cap_40_warns(caplog):
    feed = FakeFeed(_feed_items(5000, start_nid=9000))
    conn = FakeConn()  # 빈 표 → 날짜 경계 없음
    with caplog.at_level(logging.INFO, logger="news_scraper.research_collector"):
        res = _fwd(conn, feed)
    assert len(feed.calls) == 2 + 40
    assert feed.calls[2] == (1, 50) and feed.calls[-1] == (40, 50)
    assert res["stop_reason"] == "catchup_cap" and res["catchup_pages"] == 40
    assert res["new"] == 41 * 50
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_catchup_no_next_stops():
    feed = FakeFeed(_feed_items(130, start_nid=5000))
    res = _fwd(FakeConn(), feed)
    assert feed.calls == [(0, 30), (1, 30), (1, 50), (2, 50)]
    assert res["stop_reason"] == "no_next" and res["new"] == 130


# ── 표 없음(DDL 적용 전) ──
def test_missing_table_skips_without_http_and_warns_once(caplog):
    conn = FakeConn(has_table=False)
    fetch = FakeFetch(_pages_desc(2, 30, last_has_next=False))
    with caplog.at_level(logging.INFO, logger="news_scraper.research_collector"):
        r1 = _fwd(conn, fetch)
        r2 = _fwd(conn, fetch)
    assert fetch.calls == []
    assert r1["ok"] is False and r1["stop_reason"] == "no_table" and r2["stop_reason"] == "no_table"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    # 나중에 표가 생기면 다시 확인해서 돈다
    conn.has_table = True
    r3 = _fwd(conn, fetch)
    assert r3["ok"] is True and fetch.calls


def test_table_check_cached_once_ready():
    conn = FakeConn(known={985})
    _fwd(conn, FakeFetch(_pages_desc(1, 30)))
    _fwd(conn, FakeFetch(_pages_desc(1, 30)))
    checks = [s for s, _ in conn.executed if "to_regclass" in s]
    assert len(checks) == 1


# ── 백필 ──
def test_backfill_stops_at_cutoff_and_flags_rows():
    dates = ["2024-10-20", "2024-10-18", "2024-10-17", "2024-10-16"]
    pages = _pages_desc(4, 3, dates=dates)
    # 셋째 페이지 마지막 항목만 컷오프 아래로
    pages[2]["items"][-1]["writeDate"] = "2024-10-16"
    conn, sleeps = FakeConn(), []
    fetch = FakeFetch(pages)
    res = rc.run_backfill(conn, fetch=fetch, sleep=sleeps.append, cutoff=date(2024, 10, 17))
    assert fetch.calls == [(0, 50), (1, 50), (2, 50)]
    assert res["ok"] is True and res["stop_reason"] == "cutoff"
    assert res["inserted"] == 8 and res["below_cutoff"] == 1
    assert all(r["backfilled"] is True for r in conn.inserted_rows)
    assert all(r["write_date"] >= date(2024, 10, 17) for r in conn.inserted_rows)
    assert sleeps == [1.0, 1.0]  # 요청 사이에만


def test_backfill_default_cutoff_is_two_years():
    assert rc.BACKFILL_CUTOFF == date(2024, 10, 17)


def test_backfill_skips_existing_nids():
    pages = _pages_desc(2, 3, start_nid=100, last_has_next=False)
    conn = FakeConn(known={100, 99})
    conn.table[100] = {"nid": 100, "read_count": 1}
    res = rc.run_backfill(conn, fetch=FakeFetch(pages), sleep=lambda s: None)
    assert res["inserted"] == 4 and res["skipped"] == 2
    assert {r["nid"] for r in conn.inserted_rows} == {98, 97, 96, 95}
    assert conn.table[100]["read_count"] == 1  # 기존 행은 건드리지 않는다
    assert res["stop_reason"] == "no_next"


def test_backfill_is_rerunnable():
    pages = _pages_desc(2, 3, start_nid=100, last_has_next=False)
    conn = FakeConn()
    rc.run_backfill(conn, fetch=FakeFetch(pages), sleep=lambda s: None)
    res = rc.run_backfill(conn, fetch=FakeFetch(pages), sleep=lambda s: None)
    assert res["inserted"] == 0 and res["skipped"] == 6


def test_backfill_max_pages():
    fetch = FakeFetch(_pages_desc(5, 3))
    res = rc.run_backfill(FakeConn(), fetch=fetch, sleep=lambda s: None, max_pages=2)
    assert len(fetch.calls) == 2 and res["stop_reason"] == "max_pages"


def test_backfill_dry_run_writes_nothing():
    fetch = FakeFetch(_pages_desc(2, 3, last_has_next=False))
    res = rc.run_backfill(None, fetch=fetch, sleep=lambda s: None, dry_run=True)
    assert res["ok"] is True and res["would_insert"] == 6 and res["inserted"] == 0


def test_backfill_dry_run_with_conn_reads_only():
    conn = FakeConn(known={1000})
    res = rc.run_backfill(conn, fetch=FakeFetch(_pages_desc(1, 3, last_has_next=False)),
                          sleep=lambda s: None, dry_run=True)
    assert res["would_insert"] == 2 and res["skipped"] == 1
    assert not [s for s, _ in conn.executed if "INSERT" in s] and conn.commits == 0


def test_backfill_fetch_error_stops_without_raise():
    pages = _pages_desc(1, 3) + [rc.ResearchFetchError("HTTP 429")]
    res = rc.run_backfill(FakeConn(), fetch=FakeFetch(pages), sleep=lambda s: None)
    assert res["ok"] is False and res["inserted"] == 3 and res["last_index"] == 1
    assert "429" in res["error"]

