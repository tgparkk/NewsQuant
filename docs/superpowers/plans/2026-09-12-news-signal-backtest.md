# 뉴스 신호 백테스트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 「뉴스 신호가 다음 수익을 예측하는가」에 IC·분위수 수익으로 답하는 백테스트를 만든다.

**Architecture:** 생산 `TradingAnalyzer` 에 시계와 가격 조회를 주입 가능하게 만들어 과거 시점으로 그대로 돌린다(스냅샷 재현형). 신호와 백테스트가 갈라질 수 없게 하는 것이 핵심이다. 파이프라인은 ① 재처리 → ② 신호 재현 → ③ 수익 결합 → ④ 측정 네 단계이고, 각 단계는 앞 단계의 산출물만 읽는다.

**Tech Stack:** Python 3.9 · PostgreSQL(`kis_template` @ localhost:5433) · pandas 2.2 · pytest. **새 의존성을 더하지 않는다** — 스피어만 상관은 pandas `rank()` + `corr()`, t통계량은 직접 계산한다(`scipy` 는 설치돼 있지만 `requirements.txt` 에 없다).

**Spec:** `docs/superpowers/specs/2026-09-12-news-signal-backtest-design.md`

## Global Constraints

- **생산 동작 불변.** `analyze_today_stocks()` 를 인자 없이 부르면 리팩터링 전과 **완전히 같은 결과**를 내야 한다. Task 2 의 골든 테스트가 이것을 지킨다.
- **미래 참조 금지.** 뉴스는 `published_at <= as_of`, 가격은 `date < as_of.date()` 까지만 본다. Task 1·2·4 에 각각 테스트를 건다.
- **운영 테이블을 덮어쓰지 않는다.** 재처리 결과는 `news_reprocessed` 에 쌓는다. `news` 는 읽기만 한다.
- **DB 컬럼 형식.** `daily_prices.date` 는 TEXT `'YYYY-MM-DD'` 다 — 조인할 때 `to_char(d, 'YYYY-MM-DD')` 를 쓴다. 틀리면 조인이 **조용히 0행**이 된다. `stock_code` 는 `character varying` 이고 패딩된 행이 0 이므로 `trim()` 은 무해한 방어일 뿐이다.
- **배치 스크립트는 기본 dry-run**, `--apply` 로만 쓴다. `scripts/backfill_dart_published_at.py` 관례를 따른다.
- **DB 테스트는** `pytest.mark.db` + 센티널 관례를 따른다. `tests/test_dart_backfill.py` 를 본보기로 삼는다.
- 코드·주석·커밋 메시지는 한국어. 기존 파일의 문체를 따른다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `news_scraper/backtest/__init__.py` | 패키지 |
| `news_scraper/backtest/price_asof.py` | `daily_prices` 를 as-of 로 읽는 가격 어댑터 (Task 1) |
| `news_scraper/trading_analyzer.py` (수정) | 시계·가격 주입 가능화 (Task 2) |
| `news_scraper/backtest/reprocess.py` | `news` → `news_reprocessed` 재계산 (Task 3) |
| `scripts/reprocess_news.py` | Task 3 배치 진입점 |
| `news_scraper/backtest/signal_replay.py` | 거래일×창 → `backtest_signal` (Task 4) |
| `news_scraper/backtest/returns.py` | 신호에 수익 붙이기 (Task 5) |
| `news_scraper/backtest/metrics.py` | IC·분위수·히트율·순열검정 (Task 6) |
| `scripts/run_news_backtest.py` | ②~④ 실행 + 리포트 (Task 7) |

---

## Task 1: `daily_prices` as-of 가격 어댑터

**Files:**
- Create: `news_scraper/backtest/__init__.py`
- Create: `news_scraper/backtest/price_asof.py`
- Test: `tests/test_price_asof.py`

**Interfaces:**
- Consumes: `NewsDatabase.get_connection()` / `_put_connection(conn)` (기존).
- Produces:
  - `DailyPriceAsOf(db, as_of: datetime)` — `PriceFetcher` 와 **같은 호출 형태**를 갖는다.
  - `.get_daily_price(stock_code: str, pages: int = 1) -> pandas.DataFrame | None` — 컬럼 `날짜`(str `'YYYY-MM-DD'`), `종가`(float), 날짜 **내림차순**. 데이터가 없으면 `None`.
  - `.preload(stock_codes: list[str]) -> None` — 여러 종목을 한 번의 쿼리로 캐시에 올린다.

> **왜 이 인터페이스인가** — `TradingAnalyzer._adjust_for_price_reaction` 이 `df.sort_values('날짜', ascending=False)` 후 `df.iloc[0]['종가']` 와 `df.iloc[min(days, len(df)-1)]['종가']` 를 쓴다(`trading_analyzer.py:375-382`). 컬럼 이름과 정렬을 맞춰야 그대로 주입된다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_price_asof.py`:

```python
"""실 DB 왕복 — as-of 가격 어댑터.

백테스트에서 가장 조용히 틀리는 게 미래 참조다. 어댑터가 as_of 이후 종가를
«절대» 돌려주지 않는다는 것이 이 파일의 존재 이유다.
"""
from datetime import datetime

import pytest

from news_scraper.backtest.price_asof import DailyPriceAsOf

pytestmark = pytest.mark.db

CODE = "005930"          # 삼성전자 — daily_prices 에 확실히 있다
AS_OF = datetime(2026, 6, 15, 9, 0, 0)


def test_as_of_이후_날짜를_돌려주지_않는다(db):
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)

    df = fetcher.get_daily_price(CODE)

    assert df is not None and len(df) > 0
    assert df["날짜"].max() < "2026-06-15"


def test_최신_날짜가_맨_앞이다(db):
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)

    df = fetcher.get_daily_price(CODE)

    assert list(df["날짜"]) == sorted(df["날짜"], reverse=True)


def test_선반영_체크에_필요한_행수를_돌려준다(db):
    """_adjust_for_price_reaction 이 iloc[3] 까지 본다."""
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)

    df = fetcher.get_daily_price(CODE)

    assert len(df) >= 4


def test_종가는_숫자다(db):
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)

    df = fetcher.get_daily_price(CODE)

    assert float(df.iloc[0]["종가"]) > 0


def test_없는_종목은_None_이다(db):
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)

    assert fetcher.get_daily_price("000000") is None


def test_preload_후에는_쿼리를_더_하지_않는다(db):
    fetcher = DailyPriceAsOf(db, as_of=AS_OF)
    fetcher.preload([CODE, "000660"])

    before = fetcher.query_count
    fetcher.get_daily_price(CODE)
    fetcher.get_daily_price("000660")

    assert fetcher.query_count == before
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_price_asof.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'news_scraper.backtest'`

- [ ] **Step 3: 최소 구현을 쓴다**

`news_scraper/backtest/__init__.py`:

```python
"""뉴스 신호 백테스트.

설계: docs/superpowers/specs/2026-09-12-news-signal-backtest-design.md
"""
```

`news_scraper/backtest/price_asof.py`:

```python
"""daily_prices 를 as-of 시점까지만 읽는 가격 어댑터.

TradingAnalyzer 는 지금 PriceFetcher 로 «실시간» HTTP 를 종목당 1회 쏜다
(359종목 27초). 과거 시점으로 돌릴 수도 없고 느리다. 같은 호출 형태를
유지한 채 daily_prices 를 읽는 것으로 갈아끼운다.

핵심 규칙: as_of 날짜 «이전» 종가만 돌려준다. 신호 시각이 D 09:00 이면
그날 종가는 아직 존재하지 않으므로 D 를 포함하면 곧바로 미래 참조가 된다.
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# _adjust_for_price_reaction 이 iloc[3] 까지 보므로 넉넉히 담아 둔다.
LOOKBACK_ROWS = 10


class DailyPriceAsOf:
    """PriceFetcher 와 같은 자리에 꽂히는 as-of 가격 조회기."""

    def __init__(self, db, as_of: datetime):
        self.db = db
        self.as_of_date = as_of.date().isoformat()
        self._cache: Dict[str, pd.DataFrame] = {}
        self.query_count = 0

    def preload(self, stock_codes: List[str]) -> None:
        """여러 종목을 한 번에 담는다. 종목당 왕복을 없애는 것이 목적이다."""
        codes = sorted({c.strip() for c in stock_codes if c and c.strip()})
        if not codes:
            return
        rows = self._fetch(codes)
        self.query_count += 1
        by_code: Dict[str, list] = {c: [] for c in codes}
        for code, date_str, close in rows:
            by_code[code.strip()].append((date_str, close))
        for code, items in by_code.items():
            self._cache[code] = self._to_frame(items)

    def get_daily_price(self, stock_code: str, pages: int = 1) -> Optional[pd.DataFrame]:
        """pages 인자는 PriceFetcher 와 형태를 맞추기 위한 것으로 쓰지 않는다."""
        code = (stock_code or "").strip()
        if not code:
            return None
        if code not in self._cache:
            rows = self._fetch([code])
            self.query_count += 1
            self._cache[code] = self._to_frame([(d, c) for _, d, c in rows])
        df = self._cache[code]
        return None if df.empty else df

    def _fetch(self, codes: List[str]):
        conn = self.db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT stock_code, date, close FROM (
                        SELECT stock_code, date, close,
                               row_number() OVER (PARTITION BY stock_code
                                                  ORDER BY date DESC) rn
                        FROM daily_prices
                        WHERE trim(stock_code) = ANY(%s)
                          AND date < %s
                          AND close IS NOT NULL AND close > 0
                    ) t WHERE rn <= %s
                """, (codes, self.as_of_date, LOOKBACK_ROWS))
                return cur.fetchall()
        finally:
            conn.rollback()
            self.db._put_connection(conn)

    @staticmethod
    def _to_frame(items) -> pd.DataFrame:
        if not items:
            return pd.DataFrame(columns=["날짜", "종가"])
        df = pd.DataFrame(items, columns=["날짜", "종가"])
        df["날짜"] = df["날짜"].astype(str)
        df["종가"] = df["종가"].astype(float)
        return df.sort_values("날짜", ascending=False).reset_index(drop=True)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_price_asof.py -v`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add news_scraper/backtest/__init__.py news_scraper/backtest/price_asof.py tests/test_price_asof.py
git commit -m "feat(backtest): daily_prices 를 as-of 로 읽는 가격 어댑터"
```

---

## Task 2: `TradingAnalyzer` 를 과거 시점으로 돌릴 수 있게 한다

**Files:**
- Modify: `news_scraper/trading_analyzer.py` (`__init__` `:24-29`, `analyze_today_stocks` `:31-47`, `_volume_cache` 클래스 속성 `:411-412`, `_load_volume_cache` `:414-446`)
- Create: `tests/fixtures/analyze_today_golden.json` — `{"news_rows": [...], "stock_stats": [...]}`. 입력 뉴스를 같이 담아 날짜에 묶이지 않게 한다.
- Test: `tests/test_trading_analyzer_pit.py`

**Interfaces:**
- Consumes: `DailyPriceAsOf` (Task 1).
- Produces:
  - `TradingAnalyzer(db_path=..., price_fetcher=None)` — `price_fetcher` 를 주면 그걸 쓴다.
  - `TradingAnalyzer.analyze_stocks(news_rows: list[dict], as_of: datetime) -> dict` — 뉴스 목록을 직접 받는 순수 집계. 반환 형태는 `analyze_today_stocks()` 와 같다(`total_news`, `stocks_mentioned`, `buy_candidates`, `sell_candidates`, `watch_candidates`, `stock_stats`, `analysis_date`).
  - `analyze_today_stocks()` — 인자 없이 부르면 **지금과 완전히 같은 결과**.

> **여기서 같이 고치는 두 가지**
> 1. `_volume_cache` · `_volume_cache_loaded` 가 **클래스 속성**이라 인스턴스 사이로 새 나간다(`:411-412`). 거래일마다 새 분석기를 만드는 백테스트에서는 첫 거래일 캐시가 169일 내내 재사용된다. 인스턴스 속성으로 내린다.
> 2. `_load_volume_cache` 가 **날짜 제한 없이** `news` 전체를 읽는다(`:422-427`). 과거 시점 재현에서 D 이후 뉴스로 기준선을 만들면 곧바로 미래 참조다. `as_of` 를 받게 한다.
>
> **생산 동작은 건드리지 않는다.** `as_of=None` 이면 지금 코드 그대로 돈다. 「최근 날짜 1개를 버리고 그 앞 20일」이라는 현행 규칙은 그날 뉴스가 아직 없으면 D-1 을 버리는 문제가 있지만, 그건 이 작업의 범위가 아니다 — §후속에 적어 둔다.

- [ ] **Step 1: 골든 픽스처를 뜬다 (리팩터링 «전» 의 출력 + 그때 읽은 뉴스)**

골든에 **입력 뉴스까지 같이 담는다.** `analyze_today_stocks()` 는 `datetime.now()` 를
읽으므로 출력만 저장하면 다음 날 입력이 달라져 테스트가 깨진다 — 날짜에 묶이지 않게
입력을 고정한다.

```bash
PYTHONIOENCODING=utf-8 python - <<'PY'
import json
from datetime import datetime
from news_scraper.trading_analyzer import TradingAnalyzer

a = TradingAnalyzer()
today = datetime.now()
start = today.replace(hour=0, minute=0, second=0, microsecond=0)
end = today.replace(hour=23, minute=59, second=59, microsecond=999999)
rows = a.db.get_news_by_date_range(start.isoformat(), end.isoformat())

result = a.analyze_today_stocks()

# 가격에 의존하지 않는 필드만 고정한다. adjusted_sentiment·composite_score·
# volume_signal 은 리팩터링 «전» 코드에서 실시간 HTTP 주가를 타므로 재실행마다
# 값이 달라질 수 있다. 이번에 의도적으로 주입 가능하게 바꾸는 부분이라
# 동치성 비교의 대상이 아니다.
PURE = ("news_count", "avg_sentiment", "avg_overall",
        "positive_count", "negative_count", "neutral_count", "positive_ratio")

golden = {
    "news_rows": [
        {"news_id": n.get("news_id"), "title": n.get("title"),
         "content": n.get("content"), "published_at": n.get("published_at"),
         "related_stocks": n.get("related_stocks"),
         "sentiment_score": n.get("sentiment_score"),
         "overall_score": n.get("overall_score")}
        for n in rows
    ],
    "stock_stats": sorted(
        [{k: s[k] for k in ("stock_code", *PURE)} for s in result["stock_stats"]],
        key=lambda s: s["stock_code"],
    ),
}
with open("tests/fixtures/analyze_today_golden.json", "w", encoding="utf-8") as f:
    json.dump(golden, f, ensure_ascii=False, indent=2, default=str)
print("뉴스", len(golden["news_rows"]), "종목", len(golden["stock_stats"]))
PY
```

> 뉴스가 0건이면(장 시작 전 등) 골든이 비어 동치성 테스트가 아무것도 지키지 못한다.
> 출력된 「뉴스 N」이 0 이면 **멈추고 보고한다.**

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_trading_analyzer_pit.py`:

```python
"""TradingAnalyzer 를 과거 시점으로 돌릴 수 있는가.

원장은 어제 만들어져 359행뿐이라 과거 신호를 news 에서 재구성해야 한다.
그러려면 시계와 가격 조회를 주입할 수 있어야 한다.

생산 동작이 바뀌면 안 된다 — 그것을 지키는 게 골든 테스트다.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from news_scraper.trading_analyzer import TradingAnalyzer

pytestmark = pytest.mark.db

GOLDEN = Path(__file__).parent / "fixtures" / "analyze_today_golden.json"


class FakePriceFetcher:
    """호출 사실만 기록한다. 가격은 없다고 답한다."""

    def __init__(self):
        self.calls = []

    def get_daily_price(self, stock_code, pages=1):
        self.calls.append(stock_code)
        return None


def _news(news_id, published_at, code, sentiment, overall):
    return {
        "news_id": news_id, "title": f"t{news_id}", "content": "c",
        "published_at": published_at, "related_stocks": code,
        "sentiment_score": sentiment, "overall_score": overall,
    }


def test_뉴스_목록을_직접_받아_집계한다(db):
    a = TradingAnalyzer(price_fetcher=FakePriceFetcher())
    rows = [
        _news("n1", datetime(2026, 6, 15, 8, 0), "005930", 0.8, 0.9),
        _news("n2", datetime(2026, 6, 15, 8, 30), "005930", 0.6, 0.7),
    ]

    result = a.analyze_stocks(rows, as_of=datetime(2026, 6, 15, 9, 0))

    stats = {s["stock_code"]: s for s in result["stock_stats"]}
    assert stats["005930"]["news_count"] == 2
    assert stats["005930"]["avg_sentiment"] == pytest.approx(0.7)


def test_주입한_가격조회기를_쓴다(db):
    fake = FakePriceFetcher()
    a = TradingAnalyzer(price_fetcher=fake)

    a.analyze_stocks(
        [_news("n1", datetime(2026, 6, 15, 8, 0), "005930", 0.8, 0.9)],
        as_of=datetime(2026, 6, 15, 9, 0),
    )

    assert fake.calls == ["005930"]


def test_볼륨_캐시가_인스턴스마다_따로다(db):
    """클래스 속성이면 첫 거래일 캐시가 169일 내내 재사용된다."""
    a = TradingAnalyzer(price_fetcher=FakePriceFetcher())
    b = TradingAnalyzer(price_fetcher=FakePriceFetcher())

    a._volume_cache["ZZZZZZ"] = 99

    assert "ZZZZZZ" not in b._volume_cache


def test_볼륨_기준선이_as_of_이전_뉴스만_쓴다(db):
    """as_of 이후 뉴스로 기준선을 만들면 미래 참조다."""
    a = TradingAnalyzer(price_fetcher=FakePriceFetcher())

    a._load_volume_cache(as_of=datetime(2026, 3, 2))
    early = dict(a._volume_cache)

    b = TradingAnalyzer(price_fetcher=FakePriceFetcher())
    b._load_volume_cache(as_of=datetime(2026, 9, 1))

    assert early != b._volume_cache


PURE_FIELDS = ("news_count", "avg_sentiment", "avg_overall",
               "positive_count", "negative_count", "neutral_count", "positive_ratio")


def test_골든에_뉴스와_종목이_들어있다():
    """비어 있으면 아래 동치성 테스트가 아무것도 지키지 못한다."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert len(golden["news_rows"]) > 0
    assert len(golden["stock_stats"]) > 0


def test_집계_로직이_리팩터링_전과_같다(db):
    """골든에 담아 둔 «그때 그 뉴스» 를 그대로 먹여 비교한다.

    가격에 의존하는 adjusted_sentiment·composite_score·volume_signal 은 뺀다 —
    리팩터링 전 코드가 실시간 HTTP 주가를 타서 재실행마다 달라질 수 있고,
    가격 조회는 이번에 «의도적으로» 주입 가능하게 바꾸는 부분이다.
    """
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rows = [dict(n) for n in golden["news_rows"]]

    result = TradingAnalyzer(price_fetcher=FakePriceFetcher()).analyze_stocks(rows)

    got = sorted(result["stock_stats"], key=lambda s: s["stock_code"])
    want = golden["stock_stats"]
    assert [g["stock_code"] for g in got] == [w["stock_code"] for w in want]
    for g, w in zip(got, want):
        for field in PURE_FIELDS:
            assert g[field] == pytest.approx(w[field]), f"{g['stock_code']}.{field}"


def test_생산_경로가_오류없이_돌고_같은_키를_돌려준다(db):
    """analyze_today_stocks() 를 인자 없이 부르는 경로가 살아 있는가."""
    result = TradingAnalyzer().analyze_today_stocks()

    assert set(result) >= {"total_news", "stocks_mentioned", "buy_candidates",
                           "sell_candidates", "watch_candidates", "stock_stats"}
```

- [ ] **Step 3: 실패를 확인한다**

Run: `python -m pytest tests/test_trading_analyzer_pit.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'price_fetcher'`

- [ ] **Step 4: `__init__` 을 고친다**

`news_scraper/trading_analyzer.py` `:24-29` 를 다음으로 바꾼다:

```python
    def __init__(self, db_path: str = "news_data.db", price_fetcher=None):
        """
        Args:
            db_path: 데이터베이스 파일 경로
            price_fetcher: 주가 조회기. 백테스트는 DailyPriceAsOf 를 넣어
                «과거 시점» 으로 돌린다. 생략하면 생산용 PriceFetcher.
        """
        self.db = NewsDatabase(db_path)
        self.price_fetcher = price_fetcher or PriceFetcher()
        # 클래스 속성이면 인스턴스 사이로 새 나간다. 거래일마다 분석기를
        # 새로 만드는 백테스트에서는 첫날 캐시가 내내 재사용된다.
        self._volume_cache: Dict = {}
        self._volume_cache_loaded: bool = False
```

그리고 `:411-412` 의 클래스 속성 두 줄을 **지운다**:

```python
    # 종목별 일평균 뉴스 수 캐시 (세션 내 재사용)
    _volume_cache: Dict = {}
    _volume_cache_loaded: bool = False
```

- [ ] **Step 5: `analyze_today_stocks` 를 껍데기로 만든다**

`:31-47` 의 앞부분(오늘 날짜 계산 + 조회)을 이렇게 바꾼다:

```python
    def analyze_today_stocks(self) -> Dict:
        """
        오늘자 뉴스 기반 종목 분석 (생산 경로).

        창 계산과 조회만 하고 집계는 analyze_stocks() 에 넘긴다.
        인자 없이 부르는 이 경로의 결과는 예전과 «완전히 같아야» 한다.
        """
        today = datetime.now()
        start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)

        today_news = self.db.get_news_by_date_range(
            start_date.isoformat(),
            end_date.isoformat()
        )
        return self.analyze_stocks(today_news, as_of=None)

    def analyze_stocks(self, news_rows: List[Dict], as_of: Optional[datetime] = None) -> Dict:
        """뉴스 목록을 받아 종목별 신호를 만든다.

        as_of 를 주면 볼륨 기준선을 그 시점 «이전» 뉴스로만 만든다.
        생산 경로는 None 을 넘겨 기존 동작을 그대로 쓴다.
        """
        today_news = news_rows
        self._as_of = as_of
```

이 아래는 기존 `analyze_today_stocks` 본문(`if len(today_news) == 0:` 부터 끝까지)을 **그대로 둔다**.

- [ ] **Step 6: `_load_volume_cache` 에 as-of 를 넣는다**

`:414` 의 시그니처와 쿼리를 바꾼다:

```python
    def _load_volume_cache(self, as_of: Optional[datetime] = None):
        """전 종목의 일별 뉴스 수를 한 번에 로드 (LIKE 반복 대신 한 번 풀스캔).

        as_of 를 주면 그 시점 «이전» 뉴스만 센다. 주지 않으면 예전처럼
        전체를 읽고 최근 날짜 1개를 버린다(생산 경로).
        """
        if self._volume_cache_loaded:
            return

        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            if as_of is None:
                cursor.execute("""
                    SELECT DATE(published_at) as d, related_stocks
                    FROM news
                    WHERE related_stocks IS NOT NULL AND related_stocks != ''
                    ORDER BY d DESC
                """)
            else:
                cursor.execute("""
                    SELECT DATE(published_at) as d, related_stocks
                    FROM news
                    WHERE related_stocks IS NOT NULL AND related_stocks != ''
                      AND published_at < %s
                    ORDER BY d DESC
                """, (as_of,))
            rows = cursor.fetchall()
            self.db._put_connection(conn)
```

그리고 `:440-446` 의 일평균 계산에서 **as_of 가 있으면 최근 날짜를 버리지 않는다**:

```python
            # 종목별 일평균 (최근 20일)
            # 생산 경로는 오늘자가 섞여 있으므로 최근 1일을 버린다.
            # as_of 경로는 쿼리에서 이미 잘렸으므로 버리면 안 된다.
            skip = 0 if as_of is not None else 1
            for code, daily in stock_daily.items():
                dates = sorted(daily.keys(), reverse=True)
                if len(dates) <= skip:
                    self._volume_cache[code] = 0
                else:
                    counts = [daily[d] for d in dates[skip:skip + 20]]
```

`_volume_signal` 의 `self._load_volume_cache()` 호출을 `self._load_volume_cache(getattr(self, "_as_of", None))` 로 바꾼다.

- [ ] **Step 7: 통과를 확인한다**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_trading_analyzer_pit.py -v`
Expected: 7 passed

- [ ] **Step 8: 전체 스위트가 깨지지 않았는지 본다**

Run: `python -m pytest tests/ -q`
Expected: 기존 272 + 신규 통과, 실패 0

- [ ] **Step 9: 커밋**

```bash
git add news_scraper/trading_analyzer.py tests/test_trading_analyzer_pit.py tests/fixtures/analyze_today_golden.json
git commit -m "refactor(analyzer): 시계·가격 조회를 주입 가능하게 — 과거 시점 재현의 전제"
```

---

## Task 3: 재처리 — `news_reprocessed`

**Files:**
- Create: `news_scraper/backtest/reprocess.py`
- Create: `scripts/reprocess_news.py`
- Test: `tests/test_reprocess_news.py`

**Interfaces:**
- Consumes: `BaseCrawler.extract_stock_codes`, `SentimentAnalyzer.analyze_news`.
- Produces:
  - `ensure_table(db) -> None`
  - `code_version() -> str` — `git rev-parse --short HEAD` (Task 4 도 쓴다)
  - `reprocess(db, apply: bool = False, limit: int | None = None, only_news_id: str | None = None) -> dict` — `{"candidates": int, "written": int, "applied": bool}`
  - 테이블 `news_reprocessed(news_id TEXT PK, published_at TIMESTAMP, source TEXT, title TEXT, related_stocks TEXT, sentiment_score DOUBLE PRECISION, importance_score DOUBLE PRECISION, impact_score DOUBLE PRECISION, timeliness_score DOUBLE PRECISION, overall_score DOUBLE PRECISION, code_version TEXT, reprocessed_at TIMESTAMP DEFAULT now())`

> `scripts/reprocess_data.py` 는 쓰지 않는다 — 점수 있는 행을 스킵하고, 대상이 오늘로 하드코딩돼 있고, 본문 크롤링과 한 루프라 `sleep 1.5s` 가 있고, `overall_score` 가중치가 본체와 다르다(0.5/0.2/0.2/0.1 vs `analyze_news` 의 0.4/0.3/0.2/0.1).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_reprocess_news.py`:

```python
"""실 DB 왕복 — news → news_reprocessed 재처리.

저장된 related_stocks 는 어제 고친 추출기(b75de2a)의 출력이고
sentiment_score 는 구 로직이다. 그대로 백테스트하면 이미 고친 버그가
섞인 파이프라인을 측정하게 된다. 그래서 현재 코드로 다시 돌린다.

news 는 «읽기만» 한다 — 운영 테이블을 또 덮어쓰지 않는다.
"""
from datetime import datetime

import pytest

from news_scraper.backtest.reprocess import ensure_table, reprocess

pytestmark = pytest.mark.db

SENTINEL = "test-reprocess-0001"


@pytest.fixture
def sentinel_row(db):
    ensure_table(db)
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news_reprocessed WHERE news_id = %s", (SENTINEL,))
            cur.execute("DELETE FROM news WHERE news_id = %s", (SENTINEL,))
            cur.execute("""
                INSERT INTO news (news_id, title, content, published_at, source,
                                  category, url, related_stocks, sentiment_score)
                VALUES (%s, %s, %s, %s, 'test', '테스트', %s, %s, %s)
            """, (SENTINEL, "삼성전자 4분기 실적 사상 최대",
                  "삼성전자가 4분기 영업이익이 늘었다고 밝혔다.",
                  datetime(2026, 6, 15, 10, 0), f"https://example.invalid/{SENTINEL}",
                  "999999", -0.9))
        conn.commit()
    finally:
        db._put_connection(conn)

    yield

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news_reprocessed WHERE news_id = %s", (SENTINEL,))
            cur.execute("DELETE FROM news WHERE news_id = %s", (SENTINEL,))
        conn.commit()
    finally:
        db._put_connection(conn)


def _row(db, news_id):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT related_stocks, sentiment_score, code_version
                           FROM news_reprocessed WHERE news_id = %s""", (news_id,))
            return cur.fetchone()
    finally:
        conn.rollback()
        db._put_connection(conn)


def test_apply_없이는_쓰지_않는다(db, sentinel_row):
    stats = reprocess(db, apply=False, only_news_id=SENTINEL)

    assert stats["candidates"] == 1
    assert stats["written"] == 0
    assert _row(db, SENTINEL) is None


def test_현재_추출기로_종목을_다시_붙인다(db, sentinel_row):
    reprocess(db, apply=True, only_news_id=SENTINEL)

    related, _, _ = _row(db, SENTINEL)
    assert "005930" in related.split(",")
    assert "999999" not in related.split(",")


def test_현재_로직으로_감성을_다시_매긴다(db, sentinel_row):
    """저장돼 있던 -0.9 는 구 로직 값이다."""
    reprocess(db, apply=True, only_news_id=SENTINEL)

    _, sentiment, _ = _row(db, SENTINEL)
    assert sentiment > 0


def test_어느_코드의_출력인지_남긴다(db, sentinel_row):
    reprocess(db, apply=True, only_news_id=SENTINEL)

    _, _, code_version = _row(db, SENTINEL)
    assert code_version


def test_두_번_돌려도_한_행이다(db, sentinel_row):
    reprocess(db, apply=True, only_news_id=SENTINEL)
    reprocess(db, apply=True, only_news_id=SENTINEL)

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM news_reprocessed WHERE news_id = %s",
                        (SENTINEL,))
            assert cur.fetchone()[0] == 1
    finally:
        conn.rollback()
        db._put_connection(conn)


def test_원본_news_를_건드리지_않는다(db, sentinel_row):
    reprocess(db, apply=True, only_news_id=SENTINEL)

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT related_stocks, sentiment_score FROM news WHERE news_id = %s",
                        (SENTINEL,))
            assert cur.fetchone() == ("999999", -0.9)
    finally:
        conn.rollback()
        db._put_connection(conn)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_reprocess_news.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'news_scraper.backtest.reprocess'`

- [ ] **Step 3: 구현한다**

`news_scraper/backtest/reprocess.py`:

```python
"""news 를 현재 코드로 다시 돌려 news_reprocessed 에 쌓는다.

왜 필요한가 — 저장된 related_stocks 는 2026-09-12 에 고친 추출기(b75de2a)
이전의 출력이다. 같은 본문 4,000건에 구·신 코드를 각각 돌려 비교하면 기사
1,619건(40%)의 결과가 바뀐다. sentiment_score 도 구 로직이다. 그대로
백테스트하면 «이미 고친 버그가 섞인» 파이프라인을 측정하게 된다.

왜 별도 테이블인가 — 원본을 보존해야 재처리 로직이 또 바뀌었을 때 다시
만들 수 있고, DART 백필(6978b7c)처럼 운영 테이블을 또 건드리지 않아도 된다.
"""
import logging
import subprocess
from typing import Dict, Optional

logger = logging.getLogger(__name__)

TABLE = "news_reprocessed"

_CREATE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    news_id           TEXT PRIMARY KEY,
    published_at      TIMESTAMP NOT NULL,
    source            TEXT,
    title             TEXT,
    related_stocks    TEXT,
    sentiment_score   DOUBLE PRECISION,
    importance_score  DOUBLE PRECISION,
    impact_score      DOUBLE PRECISION,
    timeliness_score  DOUBLE PRECISION,
    overall_score     DOUBLE PRECISION,
    code_version      TEXT,
    reprocessed_at    TIMESTAMP NOT NULL DEFAULT now()
)
"""
_INDEX = f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_published ON {TABLE} (published_at)"


def code_version() -> str:
    """이 테이블은 «어느 시점 코드의 출력인가» 가 곧 의미다."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def ensure_table(db) -> None:
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE)
            cur.execute(_INDEX)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_connection(conn)


def _analyzers():
    from news_scraper.base_crawler import BaseCrawler
    from news_scraper.sentiment_analyzer import SentimentAnalyzer

    class _Extractor(BaseCrawler):
        def crawl_news_list(self, max_pages: int = 5):
            return []

        def crawl_news_detail(self, url: str):
            return None

    return _Extractor("reprocess"), SentimentAnalyzer()


def reprocess(db, apply: bool = False, limit: Optional[int] = None,
              only_news_id: Optional[str] = None) -> Dict:
    ensure_table(db)
    extractor, analyzer = _analyzers()
    version = code_version()

    where = "WHERE news_id = %s" if only_news_id else ""
    params = (only_news_id,) if only_news_id else ()
    tail = f" LIMIT {int(limit)}" if limit else ""

    conn = db.get_connection()
    written = 0
    try:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT news_id, title, content, published_at, source
                            FROM news {where} ORDER BY news_id{tail}""", params)
            rows = cur.fetchall()
            candidates = len(rows)

            if apply:
                for news_id, title, content, published_at, source in rows:
                    text = f"{title or ''} {content or ''}"
                    scored = analyzer.analyze_news({"title": title or "",
                                                    "content": content or ""})
                    cur.execute(f"""
                        INSERT INTO {TABLE}
                          (news_id, published_at, source, title, related_stocks,
                           sentiment_score, importance_score, impact_score,
                           timeliness_score, overall_score, code_version, reprocessed_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                        ON CONFLICT (news_id) DO UPDATE SET
                           published_at = EXCLUDED.published_at,
                           related_stocks = EXCLUDED.related_stocks,
                           sentiment_score = EXCLUDED.sentiment_score,
                           importance_score = EXCLUDED.importance_score,
                           impact_score = EXCLUDED.impact_score,
                           timeliness_score = EXCLUDED.timeliness_score,
                           overall_score = EXCLUDED.overall_score,
                           code_version = EXCLUDED.code_version,
                           reprocessed_at = now()
                    """, (news_id, published_at, source, title,
                          extractor.extract_stock_codes(text),
                          scored.get("sentiment_score"), scored.get("importance_score"),
                          scored.get("impact_score"), scored.get("timeliness_score"),
                          scored.get("overall_score"), version))
                    written += 1
        if apply:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_connection(conn)

    return {"candidates": candidates, "written": written, "applied": apply}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_reprocess_news.py -v`
Expected: 6 passed

- [ ] **Step 5: 배치 진입점을 만든다**

`scripts/reprocess_news.py`:

```python
"""news 전체를 현재 코드로 다시 돌려 news_reprocessed 에 쌓는다.

    python scripts/reprocess_news.py               # 대상만 센다
    python scripts/reprocess_news.py --apply       # 실제 실행 (약 34분)
    python scripts/reprocess_news.py --apply --limit 1000   # 맛보기

설계: docs/superpowers/specs/2026-09-12-news-signal-backtest-design.md §4
"""
import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다")
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N건만")
    args = ap.parse_args()

    from news_scraper.backtest.reprocess import reprocess
    from news_scraper.database import NewsDatabase

    db = NewsDatabase()
    t0 = time.monotonic()
    stats = reprocess(db, apply=args.apply, limit=args.limit)
    el = time.monotonic() - t0

    print(f"대상 {stats['candidates']:,}건 · 기록 {stats['written']:,}건 "
          f"· {el / 60:.1f}분 (apply={args.apply})")
    if not args.apply:
        print("\n※ --apply 없이 돌렸다. 아무것도 쓰지 않았다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: 맛보기로 돌려 본다**

Run: `python scripts/reprocess_news.py --apply --limit 500`
Expected: `대상 500건 · 기록 500건` 이 출력되고 오류 없음

- [ ] **Step 7: 커밋**

```bash
git add news_scraper/backtest/reprocess.py scripts/reprocess_news.py tests/test_reprocess_news.py
git commit -m "feat(backtest): news 를 현재 코드로 재처리해 news_reprocessed 에 쌓는다"
```

---

## Task 4: 신호 재현 — `backtest_signal`

**Files:**
- Create: `news_scraper/backtest/signal_replay.py`
- Test: `tests/test_signal_replay.py`

**Interfaces:**
- Consumes: `DailyPriceAsOf` (Task 1), `TradingAnalyzer.analyze_stocks` (Task 2), `news_reprocessed` (Task 3).
- Produces:
  - `WINDOW_KINDS = ("prod_calendar", "sector_1530")`
  - `window_bounds(trade_date: date, kind: str) -> tuple[datetime, datetime]` — `as_of` 는 언제나 `trade_date 09:00`.
  - `trading_days(db, start: date, end: date) -> list[date]` — `daily_prices` 의 거래일.
  - `replay_day(db, trade_date, kind) -> list[dict]`
  - `ensure_table(db)` / `replay_range(db, start, end, apply=False) -> dict`
  - 테이블 `backtest_signal(trade_date DATE, window_kind TEXT, as_of TIMESTAMP, stock_code TEXT, news_count INT, avg_sentiment DOUBLE PRECISION, adjusted_sentiment DOUBLE PRECISION, avg_overall DOUBLE PRECISION, volume_signal DOUBLE PRECISION, composite_score DOUBLE PRECISION, code_version TEXT, PRIMARY KEY (trade_date, window_kind, stock_code))`

> 창의 차이는 **시작점 하나뿐**이다. `prod_calendar` = `[D 00:00, D 09:00]`, `sector_1530` = `(D-1 15:30, D 09:00]`. 즉 **D-1 장 마감 후 뉴스를 넣느냐 빼느냐**.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_signal_replay.py`:

```python
"""신호 재현 — 과거 거래일의 신호를 point-in-time 으로 다시 만든다.

미래 참조가 이 파일의 주제다. 창 경계를 한 칸 잘못 잡으면 백테스트는
조용히 훌륭한 성과를 낸다.
"""
from datetime import date, datetime

import pytest

from news_scraper.backtest.signal_replay import WINDOW_KINDS, window_bounds

pytestmark = pytest.mark.db

D = date(2026, 6, 15)      # 월요일


def test_as_of_는_언제나_거래일_09시다():
    for kind in WINDOW_KINDS:
        _, as_of = window_bounds(D, kind)

        assert as_of == datetime(2026, 6, 15, 9, 0)


def test_생산_창은_그날_자정부터다():
    start, _ = window_bounds(D, "prod_calendar")

    assert start == datetime(2026, 6, 15, 0, 0)


def test_섹터_창은_직전_평일_1530_부터다():
    start, _ = window_bounds(D, "sector_1530")

    assert start == datetime(2026, 6, 12, 15, 30)   # 금요일


def test_두_창의_차이는_시작점_하나뿐이다():
    prod_start, prod_as_of = window_bounds(D, "prod_calendar")
    sect_start, sect_as_of = window_bounds(D, "sector_1530")

    assert prod_as_of == sect_as_of
    assert sect_start < prod_start


def test_알_수_없는_창은_거부한다():
    with pytest.raises(ValueError):
        window_bounds(D, "made_up")


def test_재현된_신호에_as_of_이후_뉴스가_섞이지_않는다(db):
    """news_reprocessed 를 직접 조회해 창 밖 뉴스가 없음을 확인한다."""
    from news_scraper.backtest.signal_replay import _news_in_window

    start, as_of = window_bounds(D, "sector_1530")
    rows = _news_in_window(db, start, as_of)

    assert all(start < r["published_at"] <= as_of for r in rows)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_signal_replay.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'news_scraper.backtest.signal_replay'`

- [ ] **Step 3: 구현한다**

`news_scraper/backtest/signal_replay.py`:

```python
"""과거 거래일의 종목 신호를 point-in-time 으로 다시 만든다.

원장(newsquant_signal_ledger)은 2026-09-11 에 만들어져 359행뿐이다.
그래서 과거 신호는 news_reprocessed 에서 재구성한다.

창이 둘이다(스펙 §1 결정 2). as_of 는 둘 다 D 09:00 으로 고정하고
«시작점만» 바꾼다 — 차이는 D-1 장 마감 후 뉴스를 넣느냐 빼느냐 하나다.
봇이 09:00 에 후보를 읽기 때문에 09:00 이 결정 시각이다.
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

TABLE = "backtest_signal"
WINDOW_KINDS = ("prod_calendar", "sector_1530")

DECISION_TIME = time(9, 0)     # 봇이 후보를 읽는 시각
MARKET_CLOSE = time(15, 30)

_CREATE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    trade_date          DATE NOT NULL,
    window_kind         TEXT NOT NULL,
    as_of               TIMESTAMP NOT NULL,
    stock_code          TEXT NOT NULL,
    news_count          INTEGER,
    avg_sentiment       DOUBLE PRECISION,
    adjusted_sentiment  DOUBLE PRECISION,
    avg_overall         DOUBLE PRECISION,
    volume_signal       DOUBLE PRECISION,
    composite_score     DOUBLE PRECISION,
    code_version        TEXT,
    PRIMARY KEY (trade_date, window_kind, stock_code)
)
"""


def prev_weekday(d: date) -> date:
    out = d - timedelta(days=1)
    while out.weekday() >= 5:
        out -= timedelta(days=1)
    return out


def window_bounds(trade_date: date, kind: str) -> Tuple[datetime, datetime]:
    """(창 시작, as_of). as_of 는 언제나 거래일 09:00."""
    as_of = datetime.combine(trade_date, DECISION_TIME)
    if kind == "prod_calendar":
        return datetime.combine(trade_date, time(0, 0)), as_of
    if kind == "sector_1530":
        return datetime.combine(prev_weekday(trade_date), MARKET_CLOSE), as_of
    raise ValueError(f"알 수 없는 창: {kind!r} — {WINDOW_KINDS} 중 하나여야 한다")


def ensure_table(db) -> None:
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_connection(conn)


def trading_days(db, start: date, end: date) -> List[date]:
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT date FROM daily_prices
                           WHERE date >= %s AND date <= %s ORDER BY date""",
                        (start.isoformat(), end.isoformat()))
            return [datetime.strptime(r[0], "%Y-%m-%d").date() for r in cur.fetchall()]
    finally:
        conn.rollback()
        db._put_connection(conn)


def _news_in_window(db, start: datetime, as_of: datetime) -> List[Dict]:
    """창 (start, as_of] 의 재처리된 뉴스. 미래 참조가 여기서 막힌다."""
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT news_id, title, published_at, related_stocks,
                       sentiment_score, overall_score
                FROM news_reprocessed
                WHERE published_at > %s AND published_at <= %s
                  AND related_stocks <> ''
                ORDER BY published_at, news_id
            """, (start, as_of))
            return [{"news_id": r[0], "title": r[1], "content": "",
                     "published_at": r[2], "related_stocks": r[3],
                     "sentiment_score": r[4], "overall_score": r[5]}
                    for r in cur.fetchall()]
    finally:
        conn.rollback()
        db._put_connection(conn)


def replay_day(db, trade_date: date, kind: str) -> List[Dict]:
    """거래일 하나 × 창 하나 → 종목별 신호 행."""
    from news_scraper.backtest.price_asof import DailyPriceAsOf
    from news_scraper.trading_analyzer import TradingAnalyzer

    start, as_of = window_bounds(trade_date, kind)
    rows = _news_in_window(db, start, as_of)
    if not rows:
        return []

    codes = set()
    for r in rows:
        codes.update(c.strip() for c in (r["related_stocks"] or "").split(",") if c.strip())

    prices = DailyPriceAsOf(db, as_of=as_of)
    prices.preload(sorted(codes))

    analyzer = TradingAnalyzer(price_fetcher=prices)
    result = analyzer.analyze_stocks(rows, as_of=as_of)

    out = []
    for s in result.get("stock_stats", []):
        out.append({
            "trade_date": trade_date, "window_kind": kind, "as_of": as_of,
            "stock_code": s["stock_code"], "news_count": s["news_count"],
            "avg_sentiment": s["avg_sentiment"],
            "adjusted_sentiment": s["adjusted_sentiment"],
            "avg_overall": s["avg_overall"], "volume_signal": s["volume_signal"],
            "composite_score": s["composite_score"],
        })
    return out


def replay_range(db, start: date, end: date, apply: bool = False) -> Dict:
    from news_scraper.backtest.reprocess import code_version

    ensure_table(db)
    version = code_version()
    days = trading_days(db, start, end)
    total = 0

    for d in days:
        for kind in WINDOW_KINDS:
            rows = replay_day(db, d, kind)
            total += len(rows)
            if not (apply and rows):
                continue
            conn = db.get_connection()
            try:
                with conn.cursor() as cur:
                    for r in rows:
                        cur.execute(f"""
                            INSERT INTO {TABLE}
                              (trade_date, window_kind, as_of, stock_code, news_count,
                               avg_sentiment, adjusted_sentiment, avg_overall,
                               volume_signal, composite_score, code_version)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (trade_date, window_kind, stock_code)
                            DO UPDATE SET
                              as_of = EXCLUDED.as_of,
                              news_count = EXCLUDED.news_count,
                              avg_sentiment = EXCLUDED.avg_sentiment,
                              adjusted_sentiment = EXCLUDED.adjusted_sentiment,
                              avg_overall = EXCLUDED.avg_overall,
                              volume_signal = EXCLUDED.volume_signal,
                              composite_score = EXCLUDED.composite_score,
                              code_version = EXCLUDED.code_version
                        """, (r["trade_date"], r["window_kind"], r["as_of"],
                              r["stock_code"], r["news_count"], r["avg_sentiment"],
                              r["adjusted_sentiment"], r["avg_overall"],
                              r["volume_signal"], r["composite_score"], version))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                db._put_connection(conn)
        logger.info(f"[백테스트] {d} 재현 완료 (누적 {total}행)")

    return {"days": len(days), "rows": total, "applied": apply}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_signal_replay.py -v`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add news_scraper/backtest/signal_replay.py tests/test_signal_replay.py
git commit -m "feat(backtest): 과거 거래일 신호를 point-in-time 으로 재현한다"
```

---

## Task 5: 수익 결합

**Files:**
- Create: `news_scraper/backtest/returns.py`
- Test: `tests/test_backtest_returns.py`

**Interfaces:**
- Consumes: `backtest_signal` (Task 4), `daily_prices`.
- Produces:
  - `HORIZONS = (0, 1, 5)` — 청산이 D 종가(0) / D+1 종가(1) / D+5 종가(5).
  - `CORPORATE_ACTION_LIMIT = 0.30`
  - `load_returns(db, start: date, end: date) -> pandas.DataFrame` — 컬럼 `trade_date, stock_code, ret_h0, ret_h1, ret_h5`.
  - `attach_returns(signals: pandas.DataFrame, rets: pandas.DataFrame) -> pandas.DataFrame` — `excess_h0/h1/h5` 를 붙인다(같은 거래일·같은 창의 횡단면 평균 차감).

> 지수를 쓰지 않는 이유: `market_index` 는 2026-02-12 에서 끊기고 `index_daily` 는 2026-06-15 부터라 169 거래일 중 4개월이 빈다(스펙 §0.6).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_backtest_returns.py`:

```python
"""수익 결합 — 신호에 이후 수익을 붙인다.

returns_1d 는 수정주가가 아니다. 거래소 가격제한폭이 ±30% 이므로 그걸
넘는 값은 정의상 수익이 아니라 기업행위다(액면분할 등).
"""
from datetime import date

import pandas as pd
import pytest

from news_scraper.backtest.returns import CORPORATE_ACTION_LIMIT, attach_returns


def _signals():
    return pd.DataFrame([
        {"trade_date": date(2026, 6, 15), "window_kind": "sector_1530",
         "stock_code": "A", "composite_score": 0.9},
        {"trade_date": date(2026, 6, 15), "window_kind": "sector_1530",
         "stock_code": "B", "composite_score": 0.1},
    ])


def _rets(a_h1, b_h1):
    return pd.DataFrame([
        {"trade_date": date(2026, 6, 15), "stock_code": "A",
         "ret_h0": 0.0, "ret_h1": a_h1, "ret_h5": 0.0},
        {"trade_date": date(2026, 6, 15), "stock_code": "B",
         "ret_h0": 0.0, "ret_h1": b_h1, "ret_h5": 0.0},
    ])


def test_횡단면_평균을_뺀다():
    out = attach_returns(_signals(), _rets(0.04, 0.02))

    got = dict(zip(out["stock_code"], out["excess_h1"]))
    assert got["A"] == pytest.approx(0.01)    # 0.04 - 평균 0.03
    assert got["B"] == pytest.approx(-0.01)


def test_초과수익의_합은_0이다():
    out = attach_returns(_signals(), _rets(0.04, 0.02))

    assert out["excess_h1"].sum() == pytest.approx(0.0)


def test_기업행위_관측은_버린다():
    """±30% 를 넘으면 수익이 아니라 액면분할이다."""
    out = attach_returns(_signals(), _rets(0.55, 0.02))

    assert "A" not in set(out["stock_code"])
    assert "B" in set(out["stock_code"])


def test_제한폭_경계값은_남긴다():
    out = attach_returns(_signals(), _rets(CORPORATE_ACTION_LIMIT, 0.02))

    assert "A" in set(out["stock_code"])


def test_수익이_없는_신호는_빠진다():
    rets = _rets(0.04, 0.02)
    rets = rets[rets["stock_code"] == "A"]

    out = attach_returns(_signals(), rets)

    assert set(out["stock_code"]) == {"A"}


def test_창이_다르면_따로_평균낸다():
    sig = _signals()
    other = sig.copy()
    other["window_kind"] = "prod_calendar"
    other = other[other["stock_code"] == "A"]

    out = attach_returns(pd.concat([sig, other]), _rets(0.04, 0.02))

    prod = out[out["window_kind"] == "prod_calendar"]
    assert prod["excess_h1"].iloc[0] == pytest.approx(0.0)   # 혼자면 초과수익 0


@pytest.mark.db
def test_실DB_조인이_0행을_내지_않는다(db):
    """daily_prices.date 는 TEXT 'YYYY-MM-DD' 다.
    형식을 틀리면 조인 결과가 «조용히» 0행이 된다 — 설계 중 실제로 겪었다."""
    from news_scraper.backtest.returns import load_returns

    out = load_returns(db, date(2026, 6, 1), date(2026, 6, 30))

    assert len(out) > 0
    assert out["ret_h0"].notna().sum() > 0
    assert out["ret_h1"].notna().sum() > 0
    assert isinstance(out["trade_date"].iloc[0], date)


@pytest.mark.db
def test_실DB_수익에_기업행위가_남아있지_않다(db):
    """±30% 를 넘는 일간 변동 구간은 load_returns 가 이미 뺐어야 한다."""
    from news_scraper.backtest.returns import load_returns

    out = load_returns(db, date(2026, 6, 1), date(2026, 6, 30))

    assert out["ret_h0"].abs().max() <= CORPORATE_ACTION_LIMIT + 1e-9
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_backtest_returns.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'news_scraper.backtest.returns'`

- [ ] **Step 3: 구현한다**

`news_scraper/backtest/returns.py`:

```python
"""신호에 이후 수익을 붙이고 초과수익을 만든다.

진입은 D 시가다 — 봇이 09:00 에 후보를 읽고 개장에 매매하는 규약과 맞춘다.
청산은 D 종가 / D+1 종가 / D+5 종가 셋을 모두 잰다.

초과수익은 «일별 횡단면 평균 차감» 이다. 지수를 쓰지 않는 이유는 데이터가
없기 때문이다 — market_index 는 2026-02-12 에서 끊기고 index_daily 는
2026-06-15 부터라 169 거래일 중 넉 달이 빈다. IC 는 어차피 순위상관이라
횡단면이고 시장중립이다.

daily_prices.returns_1d 는 (close-prev)/prev 의 «소수» 이고 수정주가가
아니다. 거래소 일간 가격제한폭이 ±30% 이므로 그걸 넘는 값은 정의상 수익이
아니라 기업행위다 — 2026년 430,912건 중 441건(0.102%)뿐이다.
"""
import logging
from datetime import date
from typing import List

import pandas as pd

logger = logging.getLogger(__name__)

HORIZONS = (0, 1, 5)
CORPORATE_ACTION_LIMIT = 0.30


def load_returns(db, start: date, end: date) -> pd.DataFrame:
    """거래일별 (종목, 진입 시가 기준 수익). 기업행위 구간은 뺀다."""
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                WITH p AS (
                    SELECT trim(stock_code) AS stock_code, date, open, close, returns_1d,
                           row_number() OVER (PARTITION BY trim(stock_code)
                                              ORDER BY date) rn
                    FROM daily_prices
                    WHERE date >= %s AND date <= %s
                      AND open > 0 AND close > 0
                ), f AS (
                    -- 진입일부터 D+5 까지 «어느 하루라도» 제한폭을 넘었는지 본다.
                    -- 중간 하루만 분할이어도 h5 수익이 통째로 망가진다.
                    SELECT p.*,
                           GREATEST(
                             COALESCE(abs(returns_1d), 0),
                             COALESCE(MAX(abs(returns_1d)) OVER (
                                 PARTITION BY stock_code ORDER BY rn
                                 ROWS BETWEEN 1 FOLLOWING AND 5 FOLLOWING), 0)
                           ) AS max_abs_move
                    FROM p
                )
                SELECT e.stock_code, e.date, e.open,
                       h0.close, h1.close, h5.close, e.max_abs_move
                FROM f e
                LEFT JOIN p h0 ON h0.stock_code = e.stock_code AND h0.rn = e.rn
                LEFT JOIN p h1 ON h1.stock_code = e.stock_code AND h1.rn = e.rn + 1
                LEFT JOIN p h5 ON h5.stock_code = e.stock_code AND h5.rn = e.rn + 5
            """, (start.isoformat(), end.isoformat()))
            rows = cur.fetchall()
    finally:
        conn.rollback()
        db._put_connection(conn)

    out: List[dict] = []
    for code, d, open_, c0, c1, c5, max_move in rows:
        if max_move is not None and max_move > CORPORATE_ACTION_LIMIT:
            continue
        rec = {"trade_date": pd.Timestamp(d).date(), "stock_code": code}
        for h, close in ((0, c0), (1, c1), (5, c5)):
            rec[f"ret_h{h}"] = None if close is None else (close - open_) / open_
        out.append(rec)
    return pd.DataFrame(out)


def attach_returns(signals: pd.DataFrame, rets: pd.DataFrame) -> pd.DataFrame:
    """신호에 수익을 붙이고 거래일·창별 횡단면 평균을 뺀다."""
    if signals.empty or rets.empty:
        return pd.DataFrame()

    df = signals.merge(rets, on=["trade_date", "stock_code"], how="inner")

    for h in HORIZONS:
        col = f"ret_h{h}"
        if col not in df.columns:
            continue
        # 기업행위는 load_returns 가 이미 뺐지만, 직접 만든 표로 부를 수도 있다.
        df.loc[df[col].abs() > CORPORATE_ACTION_LIMIT, col] = None
        grp = df.groupby(["trade_date", "window_kind"])[col]
        df[f"excess_h{h}"] = df[col] - grp.transform("mean")

    keep = df[[f"ret_h{h}" for h in HORIZONS]].notna().any(axis=1)
    return df[keep].reset_index(drop=True)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_backtest_returns.py -v`
Expected: 8 passed

- [ ] **Step 5: 커밋**

```bash
git add news_scraper/backtest/returns.py tests/test_backtest_returns.py
git commit -m "feat(backtest): 신호에 수익을 붙이고 횡단면 초과수익을 만든다"
```

---

## Task 6: 측정 — IC · 분위수 · 히트율 · 순열검정

**Files:**
- Create: `news_scraper/backtest/metrics.py`
- Test: `tests/test_backtest_metrics.py`

**Interfaces:**
- Consumes: Task 5 의 `attach_returns` 결과 프레임.
- Produces:
  - `daily_ic(df, score_col='composite_score', ret_col='excess_h1') -> pandas.Series` — 인덱스가 `trade_date`.
  - `ic_summary(ic: pandas.Series) -> dict` — `{"n_days", "mean_ic", "std_ic", "t_stat"}`.
  - `quantile_returns(df, ret_col, n_q=5) -> pandas.DataFrame` — 컬럼 `quantile, mean_excess, n`.
  - `hit_rate(df, ret_col, top_n=10) -> float`
  - `permutation_test(df, ret_col, n_iter=500, seed=0) -> dict` — `{"observed", "p_value", "n_iter"}`

> **새 의존성을 더하지 않는다.** 스피어만은 `rank()` 후 피어슨(pandas `corr()`)으로 구한다. t통계량은 `mean / (std / sqrt(n))` 로 직접 계산한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_backtest_metrics.py`:

```python
"""측정 — 「신호가 수익을 예측하는가」에 답하는 숫자들.

169 거래일은 IC 유의성에 넉넉한 표본이 아니다. 그래서 순열 검정을 같이
돌려 「IC 0.03」이 우연과 구별되는지 말할 수 있게 한다.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from news_scraper.backtest.metrics import (
    daily_ic, hit_rate, ic_summary, permutation_test, quantile_returns,
)


def _frame(pairs, day=date(2026, 6, 15)):
    return pd.DataFrame([
        {"trade_date": day, "window_kind": "sector_1530",
         "stock_code": f"S{i}", "composite_score": s, "excess_h1": r}
        for i, (s, r) in enumerate(pairs)
    ])


def test_완전_상관이면_IC가_1이다():
    df = _frame([(0.1, 0.01), (0.2, 0.02), (0.3, 0.03), (0.4, 0.04)])

    assert daily_ic(df).iloc[0] == pytest.approx(1.0)


def test_완전_역상관이면_IC가_마이너스_1이다():
    df = _frame([(0.1, 0.04), (0.2, 0.03), (0.3, 0.02), (0.4, 0.01)])

    assert daily_ic(df).iloc[0] == pytest.approx(-1.0)


def test_종목이_2개_미만인_날은_IC를_내지_않는다():
    df = _frame([(0.1, 0.01)])

    assert len(daily_ic(df)) == 0


def test_IC요약이_표본수와_t통계량을_준다():
    ic = pd.Series([0.1, 0.2, 0.15], index=[date(2026, 6, d) for d in (15, 16, 17)])

    out = ic_summary(ic)

    assert out["n_days"] == 3
    assert out["mean_ic"] == pytest.approx(0.15)
    assert out["t_stat"] > 0


def test_분위수_수익이_단조롭다():
    df = _frame([(i / 10, i / 100) for i in range(1, 11)])

    q = quantile_returns(df, "excess_h1", n_q=5)

    assert list(q["mean_excess"]) == sorted(q["mean_excess"])


def test_히트율은_상위_N의_양의_비율이다():
    df = _frame([(0.9, 0.01), (0.8, -0.01), (0.1, 0.05)])

    assert hit_rate(df, "excess_h1", top_n=2) == pytest.approx(0.5)


def test_무작위_신호는_순열검정을_통과하지_못한다():
    rng = np.random.default_rng(7)
    days = [date(2026, 6, 1) + timedelta(days=i) for i in range(30)]
    rows = []
    for d in days:
        for i in range(20):
            rows.append({"trade_date": d, "window_kind": "sector_1530",
                         "stock_code": f"S{i}",
                         "composite_score": rng.normal(),
                         "excess_h1": rng.normal()})

    out = permutation_test(pd.DataFrame(rows), "excess_h1", n_iter=200, seed=1)

    assert out["p_value"] > 0.05
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_backtest_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'news_scraper.backtest.metrics'`

- [ ] **Step 3: 구현한다**

`news_scraper/backtest/metrics.py`:

```python
"""「신호가 수익을 예측하는가」에 답하는 숫자들.

IC(정보계수)가 핵심이다 — 거래일마다 신호 점수와 이후 초과수익의 순위상관을
구하고, 그 일별 시계열의 평균이 0 과 구별되는지를 본다.

169 거래일은 넉넉한 표본이 아니다. 그래서 순열 검정을 같이 돌린다.
일별 IC 는 자기상관이 있으므로 단순 t통계량의 한계는 리포트에 적는다.

새 의존성을 더하지 않는다 — 스피어만은 rank() 후 피어슨으로,
t통계량은 mean/(std/sqrt(n)) 로 직접 구한다.
"""
import logging
import math
from typing import Dict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_STOCKS_PER_DAY = 2


def daily_ic(df: pd.DataFrame, score_col: str = "composite_score",
             ret_col: str = "excess_h1") -> pd.Series:
    """거래일별 스피어만 순위상관. 종목이 2개 미만인 날은 건너뛴다."""
    out = {}
    for day, g in df.dropna(subset=[score_col, ret_col]).groupby("trade_date"):
        if len(g) < MIN_STOCKS_PER_DAY:
            continue
        ic = g[score_col].rank().corr(g[ret_col].rank())
        if pd.notna(ic):
            out[day] = ic
    return pd.Series(out, dtype=float).sort_index()


def ic_summary(ic: pd.Series) -> Dict:
    """평균 IC 와 t통계량. 표본 수를 «항상» 같이 돌려준다."""
    n = int(ic.notna().sum())
    if n == 0:
        return {"n_days": 0, "mean_ic": float("nan"),
                "std_ic": float("nan"), "t_stat": float("nan")}
    mean = float(ic.mean())
    std = float(ic.std(ddof=1)) if n > 1 else float("nan")
    t = mean / (std / math.sqrt(n)) if n > 1 and std and std > 0 else float("nan")
    return {"n_days": n, "mean_ic": mean, "std_ic": std, "t_stat": t}


def quantile_returns(df: pd.DataFrame, ret_col: str = "excess_h1",
                     n_q: int = 5, score_col: str = "composite_score") -> pd.DataFrame:
    """일별로 점수를 n_q 분위로 나눠 분위별 평균 초과수익을 낸다."""
    work = df.dropna(subset=[score_col, ret_col]).copy()
    if work.empty:
        return pd.DataFrame(columns=["quantile", "mean_excess", "n"])

    def _label(g):
        if g[score_col].nunique() < n_q:
            return pd.Series([np.nan] * len(g), index=g.index)
        return pd.qcut(g[score_col].rank(method="first"), n_q, labels=False)

    work["quantile"] = (work.groupby("trade_date", group_keys=False)
                            .apply(_label))
    work = work.dropna(subset=["quantile"])
    agg = (work.groupby("quantile")[ret_col]
               .agg(mean_excess="mean", n="size").reset_index())
    agg["quantile"] = agg["quantile"].astype(int)
    return agg.sort_values("quantile").reset_index(drop=True)


def hit_rate(df: pd.DataFrame, ret_col: str = "excess_h1", top_n: int = 10,
             score_col: str = "composite_score") -> float:
    """일별 상위 top_n 종목의 초과수익이 양인 비율."""
    work = df.dropna(subset=[score_col, ret_col])
    picked = (work.sort_values(score_col, ascending=False)
                  .groupby("trade_date").head(top_n))
    return float((picked[ret_col] > 0).mean()) if len(picked) else float("nan")


def permutation_test(df: pd.DataFrame, ret_col: str = "excess_h1",
                     n_iter: int = 500, seed: int = 0,
                     score_col: str = "composite_score") -> Dict:
    """거래일 안에서 점수를 섞어 평균 IC 분포를 만들고 실제값 위치를 본다."""
    observed = float(daily_ic(df, score_col, ret_col).mean())
    rng = np.random.default_rng(seed)
    work = df.dropna(subset=[score_col, ret_col]).copy()

    hits = 0
    for _ in range(n_iter):
        shuffled = work.copy()
        shuffled[score_col] = (work.groupby("trade_date")[score_col]
                                   .transform(lambda s: rng.permutation(s.values)))
        if abs(float(daily_ic(shuffled, score_col, ret_col).mean())) >= abs(observed):
            hits += 1

    return {"observed": observed,
            "p_value": (hits + 1) / (n_iter + 1),
            "n_iter": n_iter}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_backtest_metrics.py -v`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add news_scraper/backtest/metrics.py tests/test_backtest_metrics.py
git commit -m "feat(backtest): IC·분위수·히트율·순열검정"
```

---

## Task 7: 실행 스크립트와 리포트

**Files:**
- Create: `scripts/run_news_backtest.py`
- Test: 없음 (Task 1~6 이 로직을 덮는다. 이 파일은 조립과 출력만 한다)

**Interfaces:**
- Consumes: Task 4 `replay_range`·`WINDOW_KINDS`, Task 5 `load_returns`·`attach_returns`, Task 6 전부.

- [ ] **Step 1: 스크립트를 쓴다**

`scripts/run_news_backtest.py`:

```python
"""뉴스 신호 백테스트 — 신호 재현 → 수익 결합 → 측정 → 리포트.

    python scripts/reprocess_news.py --apply          # 먼저 (약 34분)
    python scripts/run_news_backtest.py --replay --apply
    python scripts/run_news_backtest.py               # 측정만 다시

설계: docs/superpowers/specs/2026-09-12-news-signal-backtest-design.md
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_START = date(2026, 1, 7)
DEFAULT_END = date(2026, 9, 11)


def _load_signals(db, start, end) -> pd.DataFrame:
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT trade_date, window_kind, stock_code, composite_score
                FROM backtest_signal
                WHERE trade_date >= %s AND trade_date <= %s
            """, (start, end))
            return pd.DataFrame(cur.fetchall(),
                                columns=["trade_date", "window_kind",
                                         "stock_code", "composite_score"])
    finally:
        conn.rollback()
        db._put_connection(conn)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--replay", action="store_true", help="신호를 다시 재현한다")
    ap.add_argument("--apply", action="store_true", help="재현 결과를 저장한다")
    ap.add_argument("--start", default=DEFAULT_START.isoformat())
    ap.add_argument("--end", default=DEFAULT_END.isoformat())
    ap.add_argument("--permutations", type=int, default=500)
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    from news_scraper.backtest.metrics import (
        daily_ic, hit_rate, ic_summary, permutation_test, quantile_returns,
    )
    from news_scraper.backtest.returns import HORIZONS, attach_returns, load_returns
    from news_scraper.backtest.signal_replay import WINDOW_KINDS, replay_range
    from news_scraper.database import NewsDatabase

    db = NewsDatabase()

    if args.replay:
        stats = replay_range(db, start, end, apply=args.apply)
        print(f"재현: 거래일 {stats['days']} · 신호 {stats['rows']:,}행 "
              f"(apply={stats['applied']})")
        if not args.apply:
            print("※ --apply 없이 돌렸다. 저장하지 않았다.\n")

    signals = _load_signals(db, start, end)
    if signals.empty:
        print("backtest_signal 이 비었다. --replay --apply 를 먼저 돌려라.")
        return 1

    rets = load_returns(db, start, end)
    df = attach_returns(signals, rets)

    print(f"\n기간 {start} ~ {end} · 신호 {len(signals):,}행 · 수익 결합 {len(df):,}행")
    print("=" * 74)

    for kind in WINDOW_KINDS:
        sub = df[df["window_kind"] == kind]
        if sub.empty:
            print(f"\n[{kind}] 관측 없음")
            continue
        print(f"\n[{kind}] 관측 {len(sub):,} · 거래일 {sub['trade_date'].nunique()}")
        for h in HORIZONS:
            col = f"excess_h{h}"
            if col not in sub.columns or sub[col].notna().sum() == 0:
                continue
            s = ic_summary(daily_ic(sub, ret_col=col))
            print(f"  h{h}: 평균IC {s['mean_ic']:+.4f} · t {s['t_stat']:+.2f} "
                  f"· 거래일 {s['n_days']} · 히트율 {hit_rate(sub, col):.3f}")

        q = quantile_returns(sub, "excess_h1")
        if not q.empty:
            cells = " ".join(f"Q{int(r.quantile) + 1} {r.mean_excess:+.4f}"
                             for r in q.itertuples())
            print(f"  h1 분위수: {cells}")
            spread = q["mean_excess"].iloc[-1] - q["mean_excess"].iloc[0]
            print(f"  h1 Q5-Q1 스프레드: {spread:+.4f}")

        p = permutation_test(sub, "excess_h1", n_iter=args.permutations)
        print(f"  순열검정: 관측 평균IC {p['observed']:+.4f} · "
              f"p={p['p_value']:.3f} ({p['n_iter']}회)")

    print("\n" + "=" * 74)
    print("한계: 생존 편향(상장폐지 종목 없음, 결과를 낙관적으로 만든다) · "
          "수정주가 부재(±30% 밖만 제거) · 표본 169 거래일 · "
          "일별 IC 자기상관(t통계량은 참고값)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 짧은 구간으로 연기 시험**

Run:
```bash
python scripts/run_news_backtest.py --replay --apply --start 2026-06-01 --end 2026-06-30 --permutations 50
```
Expected: 재현 행수와 창 2종의 IC·분위수·순열검정이 출력되고 오류 없음

- [ ] **Step 3: 전체 스위트**

Run: `python -m pytest tests/ -q`
Expected: 실패 0

- [ ] **Step 4: 커밋**

```bash
git add scripts/run_news_backtest.py
git commit -m "feat(backtest): 실행 스크립트와 리포트"
```

- [ ] **Step 5: 전체 기간을 돌리고 결과를 읽는다**

Run:
```bash
python scripts/reprocess_news.py --apply
python scripts/run_news_backtest.py --replay --apply
```

**읽는 법** — 스펙 §11 의 마지막 줄을 지킨다: **IC 가 0 과 구별되지 않으면 그렇게 보고한다. 예측력이 없다는 것도 답이다.** 순열 검정 p 값이 0.05 보다 크면 「우연과 구별되지 않는다」가 결론이고, 그걸 좋게 보이도록 지표를 바꾸지 않는다.

---

## 후속 (이번 범위 밖, 기록만)

1. **`_load_volume_cache` 의 생산 경로 규칙** — 「최근 날짜 1개를 버리고 그 앞 20일」인데, 그날 뉴스가 아직 없으면 D-1 을 버린다. 09:05 스냅샷에서 실제로 일어날 수 있다. 생산 동작 불변 원칙 때문에 이번에는 두었다.
2. **종목 사전 재생성** — 절단 별칭이 덮어쓴 골프존(215000)·F&F(383220)·컴투스(078340)·대상(001680) 복구. 생존 편향도 일부 줄어든다.
3. **시황 기사·ELS 정형 공시 필터** — 집계 단계 과제. 백테스트 결과가 「시황 기사가 노이즈다」를 가리키면 우선순위가 올라간다.
