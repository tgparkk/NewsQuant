"""스케줄러가 리서치 리포트 수집을 30분 독립 잡으로 걸고, 잡이 예외를 밖으로 내지 않는지 검증한다."""
from datetime import datetime, timedelta

import pytest
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from news_scraper import research_collector as rc
from news_scraper.scheduler import NewsScheduler


class FakeDB:
    def __init__(self, fail=False):
        self.fail = fail
        self.got, self.put = [], []

    def get_connection(self):
        if self.fail:
            raise RuntimeError("pool exhausted")
        conn = object()
        self.got.append(conn)
        return conn

    def _put_connection(self, conn):
        self.put.append(conn)


@pytest.fixture(autouse=True)
def _reset_table_state():
    rc._TABLE_STATE.update(ready=False, warned=False)
    yield
    rc._TABLE_STATE.update(ready=False, warned=False)


@pytest.fixture
def scheduler():
    """DB·크롤러 초기화를 건너뛴 빈 스케줄러."""
    s = NewsScheduler.__new__(NewsScheduler)
    s.scheduler = BlockingScheduler(timezone=pytz.timezone("Asia/Seoul"))
    return s


def test_research_job_registered_every_30_minutes(scheduler):
    scheduler.setup_schedule()

    job = scheduler.scheduler.get_job("research_reports")
    assert job is not None
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == 30 * 60
    assert job.func == scheduler.run_research_collection
    assert job.max_instances == 1
    # 기동 2분 뒤 첫 실행 — 밤·주말 밀린 리포트를 바로 따라잡는다
    now = datetime.now(pytz.timezone("Asia/Seoul"))
    assert now + timedelta(minutes=1) < job.next_run_time <= now + timedelta(minutes=2, seconds=5)
    # 기존 수집 잡과 별개
    assert scheduler.scheduler.get_job("smart_collection") is not None


def test_research_job_passes_pooled_connection_and_returns_it(scheduler, monkeypatch):
    scheduler.db = FakeDB()
    seen = []

    def fake_collect(borrow):
        for _ in range(2):  # 짧게 두 번 빌린다
            with borrow() as conn:
                seen.append(conn)
        return {"ok": True}

    monkeypatch.setattr(rc, "collect_forward", fake_collect)

    assert scheduler.run_research_collection() == {"ok": True}
    assert len(seen) == 2 and seen == scheduler.db.got and scheduler.db.put == scheduler.db.got


def test_research_job_never_raises_on_connection_error(scheduler):
    scheduler.db = FakeDB(fail=True)

    res = scheduler.run_research_collection()

    assert res["ok"] is False and "pool exhausted" in res["error"]


def test_research_job_never_raises_on_collector_error(scheduler, monkeypatch):
    scheduler.db = FakeDB()

    def boom(borrow):
        with borrow():
            raise RuntimeError("unexpected")

    monkeypatch.setattr(rc, "collect_forward", boom)

    res = scheduler.run_research_collection()

    assert res["ok"] is False and "unexpected" in res["error"]
    assert scheduler.db.put == scheduler.db.got  # 연결은 반환된다
