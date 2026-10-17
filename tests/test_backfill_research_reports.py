"""리서치 리포트 백필 CLI — dry-run 은 DB 에 붙지 않고 --max-pages 를 지킨다. 실 네트워크·DB 0."""
import importlib.util
from pathlib import Path

import pytest
from test_research_collector import FakeFetch, _pages_desc

SCRIPT = Path(__file__).parent.parent / "scripts" / "backfill_research_reports.py"


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location("backfill_research_reports", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _no_connect(*a, **k):
    raise AssertionError("dry-run 은 DB 에 붙지 않는다")


def test_dry_run_does_not_connect_and_respects_max_pages(mod, monkeypatch, capsys):
    fetch = FakeFetch(_pages_desc(3, 3))
    monkeypatch.setattr(mod, "_connect", _no_connect)
    monkeypatch.setattr(mod.rc, "fetch_page", fetch)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    code = mod.main(["--config", "nope.yaml", "--dry-run", "--max-pages", "2"])

    assert code == 0 and len(fetch.calls) == 2
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "넣을 행(추정)=6" in out


def test_fetch_error_exit_code_1(mod, monkeypatch):
    fetch = FakeFetch([mod.rc.ResearchFetchError("HTTP 503")])
    monkeypatch.setattr(mod, "_connect", _no_connect)
    monkeypatch.setattr(mod.rc, "fetch_page", fetch)

    assert mod.main(["--config", "nope.yaml", "--dry-run"]) == 1


def test_start_index_flag(mod, monkeypatch, capsys):
    fetch = FakeFetch(_pages_desc(5, 3))
    monkeypatch.setattr(mod, "_connect", _no_connect)
    monkeypatch.setattr(mod.rc, "fetch_page", fetch)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    code = mod.main(["--config", "nope.yaml", "--dry-run", "--start-index", "3", "--max-pages", "2"])

    assert code == 0 and [i for i, _ in fetch.calls] == [3, 4]
    assert "시작 index=3" in capsys.readouterr().out


def test_help_on_cp949_console_does_not_crash(mod, monkeypatch):
    # Windows 콘솔(cp949)에 파이프될 때 한글 도움말이 UnicodeEncodeError 로 죽지 않아야 한다
    import io
    import sys
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", out)
    with pytest.raises(SystemExit) as e:
        mod.main(["--help"])
    assert e.value.code == 0
