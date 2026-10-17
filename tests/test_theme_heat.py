"""네이버 테마 «열기» 마감 후 수집 — 파싱·게이트·저장(모의 DB). 실 DB·실 네트워크 접속 0."""
import gzip
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from news_scraper import theme_heat as th
from news_scraper import theme_snapshot as ts

FIX = Path(__file__).parent / "fixtures" / "naver_theme"
# 2026-10-05 11:30 UTC = 20:30 KST (장 마감 뒤). fixture 의 localTradedAt 은 10-02 라 아래 헬퍼가 날짜를 바꾼다.
NOW = datetime(2026, 10, 5, 11, 30, tzinfo=timezone.utc)


def _load(name):
    with open(FIX / name, encoding="utf-8") as f:
        return json.load(f)


def _detail(name="th_586.json", day="2026-10-05", no=None):
    """localTradedAt 의 날짜를 day 로 바꾼 상세 응답."""
    d = _load(name)
    for s in d["stocks"]:
        s["localTradedAt"] = day + s["localTradedAt"][10:]
    if no is not None:
        d["groupInfo"] = dict(d["groupInfo"], no=no)
    return d


def _list(market="CLOSE"):
    lst = _load("th_list_3.json")
    lst["totalCount"] = len(lst["groups"])
    lst["marketStatus"] = market
    return lst


# ── 파싱 ──
def test_parse_heat_closed_fixture():
    row = th.parse_heat([_detail(day="2026-10-05")])
    assert row["theme_no"] == 586 and row["member_count"] == 15
    assert row["change_rate"] == Decimal("9.38")
    assert (row["rise_count"], row["fall_count"], row["steady_count"]) == (15, 0, 0)
    assert row["market_status"] == "CLOSE"
    assert row["basis_date"].isoformat() == "2026-10-05"
    assert row["valid"] is True


def test_parse_heat_basis_date_is_mode_of_stock_dates():
    d = _detail(day="2026-10-05")
    d["stocks"][0]["localTradedAt"] = "2026-09-01T09:00:00+09:00"  # 거래정지 종목 하나
    assert th.parse_heat([d])["basis_date"].isoformat() == "2026-10-05"


def test_parse_heat_preopen_reset_is_invalid_and_null():
    row = th.parse_heat([_detail("th_586_preopen.json")])
    assert row["valid"] is False and row["metrics_reset"] is True
    assert row["change_rate"] is None and row["rise_count"] is None
    assert row["market_status"] == "PREOPEN"


def test_parse_heat_open_market_is_invalid_even_with_values():
    d = _detail()
    d["marketStatus"] = "OPEN"
    row = th.parse_heat([d])
    assert row["valid"] is False and row["change_rate"] == Decimal("9.38")


def test_parse_heat_calc_rate_only_when_all_members_present():
    d = _detail()
    row = th.parse_heat([d])
    assert row["calc_change_rate"] is None  # stocks 3 / 15 — 일부만 와서 평균을 내지 않는다
    d["totalCount"] = 3
    d["groupInfo"] = dict(d["groupInfo"], totalCount=3)
    row = th.parse_heat([d])
    # (29.95 + 29.80 + 12.82) / 3 — 네이버 changeRate 는 구성종목 fluctuationsRatio 의 동일가중 평균
    assert row["calc_change_rate"] == Decimal("24.19")


def test_parse_heat_list_rate_kept_for_audit():
    lr = {"theme_no": 586, "theme_name": "x", "member_count": 15, "change_rate": Decimal("9.30"),
          "rise_count": 15, "fall_count": 0, "steady_count": 0}
    row = th.parse_heat([_detail()], lr)
    assert row["list_change_rate"] == Decimal("9.30") and row["change_rate"] == Decimal("9.38")


# ── 실행 ──
class FakeClient:
    def __init__(self, market="CLOSE", day="2026-10-05", detail="th_586.json", fail_nos=()):
        self.market, self.day, self.detail, self.fail_nos = market, day, detail, set(fail_nos)
        self.detail_calls = 0

    def get_json(self, url):
        if "/theme?" in url:
            return _list(self.market), NOW
        no = int(url.split("/theme/")[1].split("?")[0])
        self.detail_calls += 1
        if no in self.fail_nos:
            raise ts.FetchError("fail %d" % no)
        d = _detail(self.detail, self.day, no)
        if self.market != "CLOSE":
            d["marketStatus"] = self.market
        return d, NOW


def _mock_conn(has_ok=False):
    conn = MagicMock()
    cur = MagicMock()

    def fetchone():
        sql = cur.execute.call_args.args[0]
        if "RETURNING run_id" in sql:
            return (9,)
        return (1,) if has_ok else None

    cur.fetchone.side_effect = fetchone
    cur.rowcount = 1
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


def _sqls(cur):
    return [c.args[0] for c in cur.execute.call_args_list]


def test_skip_when_ok_heat_run_exists():
    conn, cur = _mock_conn(has_ok=True)
    client = FakeClient()
    res = th.run_heat(conn, client=client, now=NOW)
    assert res.status == "skipped" and res.exit_code == 0 and client.detail_calls == 0
    assert any("theme_heat_run" in s for s in _sqls(cur))
    assert not any("INSERT" in s for s in _sqls(cur))


def test_ok_run_never_looks_at_membership_tables(tmp_path):
    conn, cur = _mock_conn()
    th.run_heat(conn, limit_themes=2, client=FakeClient(), archive_dir=str(tmp_path), now=NOW)
    joined = " ".join(_sqls(cur))
    assert "theme_snapshot_run" not in joined and "theme_daily" not in joined
    assert "theme_member_daily" not in joined


def test_write_path_inserts_heat_rows_and_archives(tmp_path):
    conn, cur = _mock_conn()
    res = th.run_heat(conn, limit_themes=2, client=FakeClient(), archive_dir=str(tmp_path), now=NOW)
    assert res.status == "ok" and res.exit_code == 0 and res.run_id == 9
    assert res.n_themes == 2 and res.n_inserted == 2
    inserts = [c for c in cur.execute.call_args_list if "INSERT INTO theme_heat_daily" in c.args[0]]
    assert len(inserts) == 2 and all("ON CONFLICT DO NOTHING" in c.args[0] for c in inserts)
    params = inserts[0].args[1]
    assert Decimal("9.38") in params and 15 in params and 9 in params  # change_rate · member_count · run_id
    path = tmp_path / "2026" / "2026-10-05.heat.json.gz"
    assert path.exists() and res.archive_path == str(path)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        raw = json.load(f)
    assert len(raw["list_pages"]) == 1 and len(raw["themes"]) == 2
    # 08:00 스냅샷 보관본 이름과 겹치지 않고, 같은 이름이 있으면 덮어쓰지 않는다
    assert not (tmp_path / "2026" / "2026-10-05.json.gz").exists()
    th.run_heat(conn, force=True, limit_themes=1, client=FakeClient(), archive_dir=str(tmp_path), now=NOW)
    assert (tmp_path / "2026" / "2026-10-05.heat.run9.json.gz").exists() and path.exists()


def test_dry_run_writes_nothing(tmp_path):
    res = th.run_heat(None, dry_run=True, limit_themes=3, client=FakeClient(),
                      archive_dir=str(tmp_path), now=NOW)
    assert res.status == "ok" and res.n_themes == 3 and list(tmp_path.iterdir()) == []


def test_market_not_closed_skips_without_detail_calls(tmp_path):
    conn, cur = _mock_conn()
    client = FakeClient(market="OPEN")
    res = th.run_heat(conn, client=client, archive_dir=str(tmp_path), now=NOW)
    assert res.status == "skipped" and "마감 전" in res.note and client.detail_calls == 0
    assert not any("INSERT INTO theme_heat_daily" in s for s in _sqls(cur))
    assert list(tmp_path.iterdir()) == []


def test_holiday_basis_mismatch_stops_early_and_stores_nothing(tmp_path):
    conn, cur = _mock_conn()
    client = FakeClient(day="2026-10-02")  # 휴장일: 응답의 기준일이 직전 거래일
    res = th.run_heat(conn, client=client, archive_dir=str(tmp_path), now=NOW)
    assert res.status == "skipped" and "기준일" in res.note
    assert client.detail_calls == 3  # 64 테마를 다 돌지 않는다
    assert not any("INSERT INTO theme_heat_daily" in s for s in _sqls(cur))


def test_preopen_reset_responses_store_nothing(tmp_path):
    conn, cur = _mock_conn()
    res = th.run_heat(conn, client=FakeClient(detail="th_586_preopen.json"),
                      archive_dir=str(tmp_path), now=NOW)
    assert res.status == "skipped" and res.n_inserted == 0
    assert not any("INSERT INTO theme_heat_daily" in s for s in _sqls(cur))


def test_partial_on_theme_failure(tmp_path):
    conn, _ = _mock_conn()
    first_no = ts.parse_list_page(_list())[0]["theme_no"]
    res = th.run_heat(conn, limit_themes=3, client=FakeClient(fail_nos=[first_no]),
                      archive_dir=str(tmp_path), now=NOW)
    assert res.status == "partial" and res.exit_code == 2 and res.n_errors == 1 and res.n_inserted == 2


def test_failed_when_list_fails(tmp_path):
    class Boom:
        def get_json(self, url):
            raise ts.FetchError("boom")

    conn, _ = _mock_conn()
    res = th.run_heat(conn, client=Boom(), archive_dir=str(tmp_path), now=NOW)
    assert res.status == "failed" and res.exit_code == 1


def test_theme_snapshot_module_has_no_heat_dependency():
    # 08:00 경로 모듈은 열기 모듈을 모른다(단방향 의존)
    assert "theme_heat" not in Path(ts.__file__).read_text(encoding="utf-8")
