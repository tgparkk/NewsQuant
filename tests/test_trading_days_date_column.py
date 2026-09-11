"""trading_days() 가 daily_prices.date 컬럼 타입 변화에 견고한지(I2).

daily_prices 는 이 저장소가 아니라 다른 저장소(kis-trading-template)가
소유한다. 지금은 TEXT 'YYYY-MM-DD' 지만, 그쪽이 DATE 로 마이그레이션하면
psycopg2 는 datetime.date 를 그대로 돌려준다. 예전 코드는 그 값을
strptime(date, ...) 에 넣어 TypeError 를 내고 `except (ValueError,
TypeError): continue` 가 «형식이 이상한 값» 취급으로 건너뛰었다 — 그러면
모든 날짜가 조용히 스킵되고 백테스트가 경고 없이 빈 결과를 낸다.

실 DB 는 마이그레이션 «전» 상태만 볼 수 있어 이 시나리오를 재현할 수
없으므로, 커서를 흉내낸 가짜 DB 로 두 컬럼 타입을 직접 주입해 검증한다.
"""
from datetime import date

from news_scraper.backtest.signal_replay import MIN_ROWS_PER_DAY, trading_days


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        pass

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)

    def rollback(self):
        pass


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def get_connection(self):
        return _FakeConn(self._rows)

    def _put_connection(self, conn):
        pass


def test_date_컬럼이_datetime_date_로_와도_거래일로_잡힌다():
    """TEXT→DATE 마이그레이션 이후를 흉내낸다 — 문자열이 아니라
    datetime.date 값이 그대로 온다. 월요일이고 행수도 충분하니 거래일로
    잡혀야 한다."""
    rows = [(date(2026, 6, 15), MIN_ROWS_PER_DAY + 10)]

    days = trading_days(_FakeDB(rows), date(2026, 6, 15), date(2026, 6, 15))

    assert days == [date(2026, 6, 15)]


def test_형식이_이상한_문자열은_그대로_건너뛴다():
    """마이그레이션과 무관하게, 진짜 깨진 텍스트는 여전히 걸러내야 한다 —
    TypeError 캐치를 없앤 것이 ValueError 캐치까지 없앤 건 아니다."""
    rows = [("이상한값", MIN_ROWS_PER_DAY + 10)]

    days = trading_days(_FakeDB(rows), date(2026, 6, 15), date(2026, 6, 15))

    assert days == []
