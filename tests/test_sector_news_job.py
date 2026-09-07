import logging
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from news_scraper.sector_news_job import run_sector_news_job

NOW = datetime(2026, 9, 8, 8, 50)     # 화 08:50 — 동결 아님


def _db(news=None, sector_map=({"005930": "261"}, {"261": "반도체 제조업"}), map_exc=None):
    db = MagicMock()
    db.get_news_in_window.return_value = news if news is not None else [
        {"news_id": "a", "title": "반도체 훈풍", "content": "", "source": "naver_finance",
         "sentiment_score": 0.5, "related_stocks": "005930"},
        {"news_id": "b", "title": "은행 실적", "content": "", "source": "mk_news",
         "sentiment_score": 0.3, "related_stocks": ""},
    ]
    if map_exc is not None:
        db.get_sector_map_as_of.side_effect = map_exc
    else:
        db.get_sector_map_as_of.return_value = sector_map
    db.write_sector_news_result.side_effect = lambda td, scores, hits: (len(scores), len(hits))
    return db


def test_job_happy_path_writes_and_reports():
    db = _db()
    s = run_sector_news_job(db, now=NOW)
    assert s["ok"] and not s["frozen"] and s["trade_date"] == "2026-09-08"
    db.get_news_in_window.assert_called_once_with(datetime(2026, 9, 7, 15, 30), NOW)
    db.get_sector_map_as_of.assert_called_once_with(date(2026, 9, 7), ["005930"])
    td, scores, hits = db.write_sector_news_result.call_args[0]
    assert td == date(2026, 9, 8) and {x["sector_key"] for x in scores} == {"261", "641"}
    assert all(x["dict_version"] == "2026-09-07.1" for x in scores)
    assert s["stock_route"] is True and s["n_sectors"] == 2 and s["mapped_codes"] == 1


def test_job_frozen_window_skips_write():
    db = _db()
    s = run_sector_news_job(db, now=datetime(2026, 9, 8, 10, 0))
    assert s["ok"] and s["frozen"] and s["trade_date"] == "2026-09-08"
    db.write_sector_news_result.assert_not_called()
    db.get_news_in_window.assert_not_called()


def test_job_route_b_disabled_when_fn_missing(caplog):
    class UndefinedFunction(Exception):
        pass
    db = _db(map_exc=UndefinedFunction("function fn_sector_map_as_of(date) does not exist"))
    with caplog.at_level(logging.WARNING):
        s = run_sector_news_job(db, now=NOW)
    assert s["ok"] and s["stock_route"] is False
    _, scores, _ = db.write_sector_news_result.call_args[0]
    assert all(x["n_stock"] == 0 for x in scores)
    assert any("경로 B 비활성" in r.message for r in caplog.records)


def test_job_bad_dictionary_aborts_without_write(tmp_path, caplog):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: ''\nsectors: {}\n", encoding="utf-8")
    db = _db()
    with caplog.at_level(logging.ERROR):
        s = run_sector_news_job(db, now=NOW, kw_path=bad)
    assert not s["ok"] and s["error"].startswith("dict:")
    db.write_sector_news_result.assert_not_called()


def test_job_swallows_db_exception():
    db = _db()
    db.get_news_in_window.side_effect = RuntimeError("db down")
    s = run_sector_news_job(db, now=NOW)
    assert not s["ok"] and "RuntimeError" in s["error"]


def test_job_reports_skipped_stock_route(caplog):
    many = ",".join(["005930", "000660", "105560", "111111", "222222", "333333"])
    db = _db(news=[{"news_id": "z", "title": "[인사] 국토교통부", "content": "", "source": "naver_finance",
                    "sentiment_score": 0.3, "related_stocks": many}])
    with caplog.at_level(logging.WARNING):
        s = run_sector_news_job(db, now=NOW)
    assert s["ok"] and s["stock_route_skipped"] == 1
    assert any("건너뛴 뉴스 1건" in r.message for r in caplog.records)


def test_scheduler_registers_job_and_runs_once_on_start(monkeypatch):
    import news_scraper.scheduler as sch
    monkeypatch.setattr(sch, "NewsDatabase", lambda *a, **k: MagicMock())
    for name in ("NaverFinanceCrawler", "DARTCrawler", "HankyungCrawler", "MKNewsCrawler", "GlobalNewsCrawler"):
        monkeypatch.setattr(sch, name, lambda *a, **k: MagicMock())
    s = sch.NewsScheduler()
    calls = []
    monkeypatch.setattr(s, "run_sector_news_aggregation", lambda: calls.append("agg") or {"ok": True})
    monkeypatch.setattr(s, "collect_all_news", lambda: calls.append("collect"))
    monkeypatch.setattr(s.scheduler, "start", lambda: None)   # BlockingScheduler 를 실제로 돌리지 않는다
    s.start()                                                   # 내부에서 setup_schedule() → 첫 수집 → 집계 1회
    assert calls == ["collect", "agg"]
    # 잡은 미기동 스케줄러의 pending 목록에서 조회된다(APScheduler 3.x get_job 은 STOPPED 상태에서 _pending_jobs 를 본다)
    assert s.scheduler.get_job("sector_news_aggregation") is not None
    assert s.scheduler.get_job("smart_collection") is not None


def test_start_survives_aggregation_import_error(monkeypatch):
    import news_scraper.scheduler as sch
    monkeypatch.setattr(sch, "NewsDatabase", lambda *a, **k: MagicMock())
    for name in ("NaverFinanceCrawler", "DARTCrawler", "HankyungCrawler", "MKNewsCrawler", "GlobalNewsCrawler"):
        monkeypatch.setattr(sch, name, lambda *a, **k: MagicMock())
    s = sch.NewsScheduler()
    calls = []
    shutdown_calls = []
    monkeypatch.setattr(
        s, "run_sector_news_aggregation",
        lambda: (_ for _ in ()).throw(ImportError("No module named yaml")),
    )
    monkeypatch.setattr(s, "collect_all_news", lambda: calls.append("collect"))
    monkeypatch.setattr(s.scheduler, "start", lambda: None)
    monkeypatch.setattr(s.scheduler, "shutdown", lambda *a, **k: shutdown_calls.append(True))
    s.start()
    assert calls == ["collect"]
    assert s.scheduler.get_job("smart_collection") is not None
    assert shutdown_calls == []


def test_job_malformed_yaml_reports_dict_error(tmp_path):
    bad = tmp_path / "malformed.yaml"
    bad.write_text("version: [unclosed\nsectors: {}", encoding="utf-8")
    db = _db()
    s = run_sector_news_job(db, now=NOW, kw_path=bad)
    assert not s["ok"] and s["error"].startswith("dict:")
    db.write_sector_news_result.assert_not_called()
