# 섹터 선행-후행 백테스트 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 「전날 같은 그룹(WICS 섹터 / 네이버 테마) 종목들이 시장보다 올랐으면 익일 그 종목이 더 오르는가」를 종목 횡단면 IC·분위수·순열검정으로 재는 백테스트를 만들고, 사전 등록 가설 H1 을 판정한 결과 문서를 낸다.

**Architecture:** 새 모듈 `news_scraper/backtest/leadlag.py` 가 `daily_prices` 패널과 그룹표를 읽어 종목별 점수 프레임 `S`(자기 제외 그룹 평균 − 시장 평균, 다중 소속은 평균, `trade_date` = 다음 거래일)를 만든다. 수익 결합·측정은 기존 `backtest/returns.py`·`backtest/metrics.py` 를 그대로 호출한다(수정 없음). 실행기 `scripts/run_leadlag_backtest.py` 는 분류 × 구간 × horizon 의 12 arm 을 돌려 표를 찍고 Holm 보정을 붙인다. 새 DB 표는 없다.

**Tech Stack:** Python 3 · pandas 2.2 · numpy 2.0 · psycopg2(`news_scraper.database.NewsDatabase`) · pytest. 새 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-10-07-sector-leadlag-design.md`

## Global Constraints

- DB 는 **읽기 전용**. 새 표·컬럼·INSERT 없음(스펙 §1.8).
- `daily_prices.date` 는 TEXT `YYYY-MM-DD`. 패널은 **`datetime.date` 객체**로 변환해야 `returns.load_returns` 가 돌려주는 `trade_date`(date 객체)와 병합된다. 형식이 어긋나면 조인이 «조용히» 0 행이 된다(뉴스 스펙 §0.4 교훈).
- `stock_code` 는 `trim()` 해서 쓴다(`returns.py` 와 동일).
- 기업행위 판정은 `|returns_1d| > 0.30` 또는 `returns_1d IS NULL` 또는 `open <= 0 OR close <= 0`(스펙 §4.1). 상수는 `returns.CORPORATE_ACTION_LIMIT` 를 재사용한다.
- 최소 그룹 크기 `MIN_MEMBERS = 5`(그날 패널에 있는 멤버 수 기준, 스펙 §4.2).
- 분류 이름은 `window_kind` 컬럼에 `"theme"` / `"wics"` 로 넣는다(`attach_returns` 가 `(trade_date, window_kind)` 로 횡단면 평균을 뺀다).
- 테마 소속표는 **`snap_date = 2026-10-07` 고정**(스펙 §1.3). WICS 는 `stock_sector` 에서 `sector_name = '기타'` 제외.
- 주 가설 H1 = `theme · excess_h1 · 2024-01-02~2026-10-07`, 순열 500 회, 양측 p < 0.05 & 평균 IC > 0(스펙 §7). 실행기 출력에서 이 arm 을 `[H1]` 로 표시한다.
- 테스트는 실 DB 를 요구하지 않는다. `load_panel`·`load_groups` 의 SQL 은 테스트하지 않고 실행기에서 실측해 푸터에 행 수를 적는다(스펙 §10).
- 커밋 메시지는 한국어 `feat(backtest): …` / `test(backtest): …` 형식, 끝에 아래 두 줄:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_017MjdggtV2tsv8eK5TEoR4p
  ```

## Review Focus

1. **패널에 같은 (date, stock_code) 가 두 번 들어오면** 그룹 합과 개수가 두 배로 잡혀 자기 제외 평균이 틀어진다. `trim()` 으로 코드가 합쳐지면 생길 수 있다. 기대: 중복은 하나만 남긴다. → Task 1 테스트 `test_clean_panel은_중복_행을_하나만_남긴다`.
2. **그룹표에는 있지만 그날 패널에 없는 종목**(상장폐지·거래정지)은 그룹 멤버 수 `n` 에 세면 안 된다. 기대: 패널 기준으로만 센다. → Task 3 테스트 `test_패널에_없는_멤버는_그룹_크기에_세지_않는다`.
3. **패널 또는 그룹표가 비면** `build_scores` 가 예외 없이 올바른 컬럼의 빈 프레임을 돌려주고, 실행기는 「관측 없음」을 찍고 종료 코드 1 을 낸다. → Task 3 테스트 `test_입력이_비면_빈_프레임을_같은_컬럼으로_돌려준다`, Task 6 가드.
4. **date 가 문자열인 채로 들어오면** `load_returns` 결과와 병합이 0 행이 된다. 기대: `clean_panel` 이 `datetime.date` 로 바꾼다. → Task 1 테스트 `test_clean_panel은_문자열_날짜를_date_객체로_바꾼다`.
5. **마지막 거래일의 점수**는 다음 거래일이 없으므로 버려야 한다. 안 버리면 `trade_date` 가 NaN 인 행이 병합·IC 에 섞인다. → Task 2 테스트 `test_마지막_날짜는_다음_거래일이_없어_맵에_없다`, Task 4 테스트 `test_마지막_날짜의_점수는_버린다`.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `news_scraper/backtest/leadlag.py` (신규) | `clean_panel`(순수) · `load_panel`(SQL + clean_panel) · `load_groups`(SQL) · `next_trading_day_map`(순수) · `build_scores`(순수). DB 접근은 `load_*` 둘뿐. |
| `scripts/run_leadlag_backtest.py` (신규) | 인자 파싱 → 분류 × 구간 루프 → `load_*` → `build_scores` → `returns.load_returns`/`attach_returns` → `metrics.*` → 출력. `holm_adjust`(순수) 포함. `run_news_backtest` 의 `_fmt_metric`·`_ic_obs_count`·`_cross_section_stats` 를 import 해 재사용. |
| `tests/test_leadlag.py` (신규) | 스펙 §10 의 1~8 + Review Focus. 손 계산 픽스처. |
| `tests/test_run_leadlag_backtest.py` (신규) | `holm_adjust` 와 arm 표 조립 헬퍼. |
| `docs/superpowers/specs/<실행일>-sector-leadlag-result.md` (신규, Task 8) | 실행 결과·판정. |

`backtest/returns.py`·`metrics.py` 는 **수정하지 않는다**.

---

### Task 1: 패널 정제 `clean_panel` + `load_panel`

**Files:**
- Create: `news_scraper/backtest/leadlag.py`
- Test: `tests/test_leadlag.py`

**Interfaces:**
- Consumes: `news_scraper.backtest.returns.CORPORATE_ACTION_LIMIT` (= 0.30)
- Produces:
  - `clean_panel(raw: pd.DataFrame) -> pd.DataFrame` — 입력 컬럼 `stock_code, date, open, close, returns_1d`(date 는 str 또는 date). 출력 컬럼 `date(datetime.date), stock_code(str, trim), ret(float)`. 정렬 `(date, stock_code)`, 인덱스 리셋.
  - `load_panel(db, start: date, end: date) -> pd.DataFrame` — `daily_prices` 를 읽어 `clean_panel` 에 넘긴다.
  - `PANEL_COLUMNS = ("date", "stock_code", "ret")`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_leadlag.py
"""섹터 선행-후행 — 점수 생성 로직을 손 계산 픽스처로 고정한다.

설계: docs/superpowers/specs/2026-10-07-sector-leadlag-design.md §4, §10.
실 DB 는 쓰지 않는다. load_panel/load_groups 의 SQL 은 실행기에서 실측한다.
"""
from datetime import date

import pandas as pd
import pytest

from news_scraper.backtest.leadlag import PANEL_COLUMNS, clean_panel


def _raw(rows):
    """(stock_code, date, open, close, returns_1d) 튜플 → daily_prices 모양 프레임."""
    return pd.DataFrame(rows, columns=["stock_code", "date", "open", "close", "returns_1d"])


def test_clean_panel은_문자열_날짜를_date_객체로_바꾼다():
    """daily_prices.date 는 TEXT 다. date 객체로 바꾸지 않으면 load_returns 의
    trade_date(date 객체)와 병합이 조용히 0 행이 된다."""
    out = clean_panel(_raw([("005930", "2026-06-15", 100, 101, 0.01)]))

    assert list(out.columns) == list(PANEL_COLUMNS)
    assert out.loc[0, "date"] == date(2026, 6, 15)
    assert type(out.loc[0, "date"]) is date
    assert out.loc[0, "ret"] == pytest.approx(0.01)


def test_clean_panel은_기업행위_행을_뺀다():
    """±30% 초과, NULL, open/close 0 은 패널에서 빠진다(스펙 §4.1).
    그룹 합·개수 둘 다에서 빠지는 것은 build_scores 가 이 패널만 받으므로 자동이다."""
    out = clean_panel(_raw([
        ("A", "2026-06-15", 100, 135, 0.35),    # +35% → 기업행위
        ("B", "2026-06-15", 100, 69, -0.31),    # −31% → 기업행위
        ("C", "2026-06-15", 100, 101, None),    # NULL → 전일 종가 없음
        ("D", "2026-06-15", 0, 101, 0.01),      # open 0
        ("E", "2026-06-15", 100, 0, 0.01),      # close 0
        ("F", "2026-06-15", 100, 130, 0.30),    # 정확히 30% 는 남는다
        ("G", "2026-06-15", 100, 102, 0.02),
    ]))

    assert sorted(out["stock_code"]) == ["F", "G"]


def test_clean_panel은_코드를_trim_하고_중복_행을_하나만_남긴다():
    """trim 으로 코드가 합쳐져 같은 (date, stock_code) 가 두 번 생기면 그룹 합이
    두 배가 된다. 첫 행만 남긴다."""
    out = clean_panel(_raw([
        ("005930 ", "2026-06-15", 100, 101, 0.01),
        ("005930", "2026-06-15", 100, 101, 0.01),
        ("000660", "2026-06-15", 100, 103, 0.03),
    ]))

    assert len(out) == 2
    assert list(out["stock_code"]) == ["000660", "005930"]  # (date, stock_code) 정렬
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_leadlag.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'news_scraper.backtest.leadlag'`

- [ ] **Step 3: 최소 구현**

```python
# news_scraper/backtest/leadlag.py
"""섹터 선행-후행 — 「전날 같은 그룹이 시장보다 올랐으면 익일 더 오르는가」.

설계: docs/superpowers/specs/2026-10-07-sector-leadlag-design.md

점수(스펙 §4):
    g_i(D)   = 그룹 g 의 D 수익 평균, i 자신 제외        (n_g(D) >= MIN_MEMBERS 일 때만)
    resid    = g_i(D) − m(D)                              (m = 그날 패널 전체 평균)
    score_i  = i 가 속한 그룹들의 resid 평균
    trade_date = D 의 다음 거래일 (봇은 다음 날 09:00 에 읽고 시가에 들어간다)

이 모듈은 DB 를 읽기만 한다(load_panel/load_groups). 나머지는 순수 함수다.
기업행위 판정(±30%)은 returns.CORPORATE_ACTION_LIMIT 를 그대로 쓴다.
"""
import logging
from datetime import date
from typing import Dict, Sequence

import pandas as pd

from news_scraper.backtest.returns import CORPORATE_ACTION_LIMIT

logger = logging.getLogger(__name__)

PANEL_COLUMNS = ("date", "stock_code", "ret")


def clean_panel(raw: pd.DataFrame) -> pd.DataFrame:
    """daily_prices 모양 프레임 → (date, stock_code, ret) 패널.

    - date 는 TEXT 일 수 있다 → datetime.date 로 바꾼다(안 그러면 load_returns
      결과와 병합이 조용히 0 행이 된다).
    - 기업행위 행 제거: |returns_1d| > CORPORATE_ACTION_LIMIT, NULL, open/close <= 0.
    - stock_code trim 후 같은 (date, stock_code) 는 첫 행만 남긴다.
    """
    if raw.empty:
        return pd.DataFrame(columns=list(PANEL_COLUMNS))

    df = raw.copy()
    df["stock_code"] = df["stock_code"].astype(str).str.strip()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["returns_1d"] = pd.to_numeric(df["returns_1d"], errors="coerce")
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")

    keep = (df["returns_1d"].notna()
            & (df["returns_1d"].abs() <= CORPORATE_ACTION_LIMIT)
            & (df["open"] > 0) & (df["close"] > 0))
    df = df[keep]

    df = (df.rename(columns={"returns_1d": "ret"})[list(PANEL_COLUMNS)]
            .drop_duplicates(subset=["date", "stock_code"], keep="first")
            .sort_values(["date", "stock_code"])
            .reset_index(drop=True))
    df["ret"] = df["ret"].astype(float)
    return df


def load_panel(db, start: date, end: date) -> pd.DataFrame:
    """daily_prices [start, end] 를 읽어 clean_panel 로 정제한다. 필터는 전부
    clean_panel 에서 한다(테스트 가능한 한 곳)."""
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT stock_code, date, open, close, returns_1d
                FROM daily_prices
                WHERE date >= %s AND date <= %s
                ORDER BY date, stock_code
            """, (start.isoformat(), end.isoformat()))
            rows = cur.fetchall()
    finally:
        conn.rollback()
        db._put_connection(conn)
    raw = pd.DataFrame(rows, columns=["stock_code", "date", "open", "close", "returns_1d"])
    return clean_panel(raw)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_leadlag.py -v`
Expected: 3 PASS

- [ ] **Step 5: 커밋**

```bash
git add news_scraper/backtest/leadlag.py tests/test_leadlag.py
git commit -m "feat(backtest): 선행-후행 패널 정제 clean_panel·load_panel — date 객체 변환·±30%·중복 제거"
```

---

### Task 2: `next_trading_day_map`

**Files:**
- Modify: `news_scraper/backtest/leadlag.py`
- Test: `tests/test_leadlag.py`

**Interfaces:**
- Produces: `next_trading_day_map(dates: Sequence[date]) -> Dict[date, date]` — 입력은 거래일 집합(순서 무관, 중복 허용). 각 날짜 → 그 다음 거래일. 마지막 날짜는 키에 없다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_leadlag.py 에 추가
from news_scraper.backtest.leadlag import next_trading_day_map


def test_다음_거래일은_주말과_연휴를_건너뛴다():
    """금 06-12 → 월 06-15, 화 06-16 → 목 06-18(수 휴장). 달력 +1 이 아니라
    «패널에 있는 다음 날짜» 다."""
    days = [date(2026, 6, 16), date(2026, 6, 12), date(2026, 6, 18), date(2026, 6, 15),
            date(2026, 6, 15)]  # 순서 무관·중복 허용

    m = next_trading_day_map(days)

    assert m[date(2026, 6, 12)] == date(2026, 6, 15)
    assert m[date(2026, 6, 15)] == date(2026, 6, 16)
    assert m[date(2026, 6, 16)] == date(2026, 6, 18)


def test_마지막_날짜는_다음_거래일이_없어_맵에_없다():
    m = next_trading_day_map([date(2026, 6, 15), date(2026, 6, 16)])

    assert date(2026, 6, 16) not in m
    assert len(m) == 1


def test_날짜가_하나거나_없으면_빈_맵이다():
    assert next_trading_day_map([date(2026, 6, 15)]) == {}
    assert next_trading_day_map([]) == {}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_leadlag.py -v -k 거래일`
Expected: FAIL — `ImportError: cannot import name 'next_trading_day_map'`

- [ ] **Step 3: 최소 구현**

```python
# news_scraper/backtest/leadlag.py 에 추가
def next_trading_day_map(dates: Sequence[date]) -> Dict[date, date]:
    """거래일 목록 → {D: D 의 다음 거래일}. «다음 거래일» 은 달력 +1 이 아니라
    목록에 있는 다음 날짜다(주말·연휴 자동 건너뜀). 마지막 날짜는 키에 없다."""
    uniq = sorted(set(dates))
    return {d: nxt for d, nxt in zip(uniq, uniq[1:])}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_leadlag.py -v`
Expected: 6 PASS

- [ ] **Step 5: 커밋**

```bash
git add news_scraper/backtest/leadlag.py tests/test_leadlag.py
git commit -m "feat(backtest): next_trading_day_map — 패널 날짜 기준 다음 거래일"
```

---

### Task 3: `build_scores` — 자기 제외 그룹 평균·잔차화·다중 소속 평균

**Files:**
- Modify: `news_scraper/backtest/leadlag.py`
- Test: `tests/test_leadlag.py`

**Interfaces:**
- Consumes: `clean_panel` 출력 형식(`date, stock_code, ret`), `next_trading_day_map`
- Produces:
  - `build_scores(panel: pd.DataFrame, groups: pd.DataFrame, kind: str, min_members: int = MIN_MEMBERS) -> pd.DataFrame`
    - `groups` 컬럼: `stock_code(str), group_id(str|int)`. 한 종목이 여러 행에 있을 수 있다(다중 소속).
    - 출력 컬럼 `SCORE_COLUMNS = ("score_date", "trade_date", "stock_code", "window_kind", "score", "same_excess")`, 정렬 `(trade_date, stock_code)`, 인덱스 리셋.
    - `window_kind` 는 `kind` 그대로.
  - `MIN_MEMBERS = 5`

이 Task 는 §4.2~4.3 과 §4.5 를 다룬다. 날짜 이동(§4.4)은 Task 4.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_leadlag.py 에 추가
from news_scraper.backtest.leadlag import MIN_MEMBERS, SCORE_COLUMNS, build_scores

D1, D2 = date(2026, 6, 15), date(2026, 6, 16)


def _panel(day, rets):
    """{"A": 0.10, ...} → 패널 프레임(한 날짜)."""
    return pd.DataFrame([{"date": day, "stock_code": c, "ret": r} for c, r in rets.items()])


def _groups(mapping):
    """{"g1": ["A","B"], ...} → groups 프레임."""
    return pd.DataFrame([{"stock_code": c, "group_id": g}
                         for g, codes in mapping.items() for c in codes])


# 손 계산 픽스처. g1 = {A,B,C,D,E}(5), g2 = {A,F,G,H,I,J}(6), K 는 무소속.
RETS_D1 = {"A": 0.10, "B": 0.02, "C": 0.00, "D": -0.02, "E": 0.04,
           "F": 0.01, "G": 0.03, "H": -0.01, "I": 0.05, "J": 0.02, "K": -0.03}
GROUPS = {"g1": ["A", "B", "C", "D", "E"], "g2": ["A", "F", "G", "H", "I", "J"]}


def _two_day_panel():
    """D2 는 D1 과 같은 수익으로 한 번 더 — trade_date 가 생기려면 다음 거래일이 필요하다."""
    return pd.concat([_panel(D1, RETS_D1), _panel(D2, RETS_D1)], ignore_index=True)


def _d1_scores():
    s = build_scores(_two_day_panel(), _groups(GROUPS), kind="theme")
    return s[s["score_date"] == D1].set_index("stock_code")


def test_자기_제외_평균이_멤버_루프와_같다():
    """구현은 (sum − r_i)/(n − 1) 로 하지만, 정의는 «i 를 뺀 멤버 평균» 이다.
    B 는 g1 에만 속하므로 score_B = mean(g1 without B) − m."""
    m = sum(RETS_D1.values()) / len(RETS_D1)
    others = [RETS_D1[c] for c in GROUPS["g1"] if c != "B"]
    expected = sum(others) / len(others) - m

    assert _d1_scores().loc["B", "score"] == pytest.approx(expected)


def test_시장_평균은_무소속_종목까지_포함한_전체_평균이다():
    """m(D) 에 K(무소속, −0.03) 가 들어가야 한다(스펙 §4.1). K 를 빼고 계산한 값과
    달라야 한다."""
    m_all = sum(RETS_D1.values()) / len(RETS_D1)
    m_wo_k = sum(v for c, v in RETS_D1.items() if c != "K") / (len(RETS_D1) - 1)
    others = [RETS_D1[c] for c in GROUPS["g1"] if c != "B"]
    loo = sum(others) / len(others)

    got = _d1_scores().loc["B", "score"]
    assert got == pytest.approx(loo - m_all)
    assert got != pytest.approx(loo - m_wo_k)


def test_다중_소속_종목의_점수는_그룹별_잔차의_평균이다():
    """A 는 g1·g2 둘 다. score_A = mean(resid_A,g1, resid_A,g2)."""
    m = sum(RETS_D1.values()) / len(RETS_D1)
    g1 = [RETS_D1[c] for c in GROUPS["g1"] if c != "A"]
    g2 = [RETS_D1[c] for c in GROUPS["g2"] if c != "A"]
    r1 = sum(g1) / len(g1) - m
    r2 = sum(g2) / len(g2) - m

    assert _d1_scores().loc["A", "score"] == pytest.approx((r1 + r2) / 2)


def test_그룹_크기가_MIN_MEMBERS_미만이면_그날_신호가_없다():
    """g3 = {L,M,N,O}(4) → L~O 는 유효 그룹이 없으니 S 에 없다. g1 종목은 그대로."""
    rets = dict(RETS_D1, L=0.01, M=0.02, N=0.03, O=0.04)
    panel = pd.concat([_panel(D1, rets), _panel(D2, rets)], ignore_index=True)
    groups = _groups(dict(GROUPS, g3=["L", "M", "N", "O"]))

    s = build_scores(panel, groups, kind="theme")
    codes = set(s[s["score_date"] == D1]["stock_code"])

    assert MIN_MEMBERS == 5
    assert {"L", "M", "N", "O"}.isdisjoint(codes)
    assert {"A", "B", "F"} <= codes


def test_패널에_없는_멤버는_그룹_크기에_세지_않는다():
    """g1 에 P 를 더하지만 P 는 패널에 없다(상장폐지 등). n_g 는 여전히 5 이고
    B 의 점수는 변하지 않는다. 반대로 g3 = {L,M,N,O,P} 는 패널 기준 4 라 신호 없음."""
    rets = dict(RETS_D1, L=0.01, M=0.02, N=0.03, O=0.04)
    panel = pd.concat([_panel(D1, rets), _panel(D2, rets)], ignore_index=True)
    groups = _groups({"g1": GROUPS["g1"] + ["P"], "g2": GROUPS["g2"],
                      "g3": ["L", "M", "N", "O", "P"]})

    s = build_scores(panel, groups, kind="theme")
    d1 = s[s["score_date"] == D1].set_index("stock_code")

    m = sum(rets.values()) / len(rets)
    others = [rets[c] for c in GROUPS["g1"] if c != "B"]
    assert d1.loc["B", "score"] == pytest.approx(sum(others) / len(others) - m)
    assert "L" not in d1.index


def test_same_excess는_그날_자기_수익에서_시장_평균을_뺀_값이다():
    m = sum(RETS_D1.values()) / len(RETS_D1)

    assert _d1_scores().loc["A", "same_excess"] == pytest.approx(0.10 - m)


def test_window_kind와_컬럼_순서():
    s = build_scores(_two_day_panel(), _groups(GROUPS), kind="wics")

    assert list(s.columns) == list(SCORE_COLUMNS)
    assert set(s["window_kind"]) == {"wics"}


def test_입력이_비면_빈_프레임을_같은_컬럼으로_돌려준다():
    empty_panel = pd.DataFrame(columns=["date", "stock_code", "ret"])
    empty_groups = pd.DataFrame(columns=["stock_code", "group_id"])

    a = build_scores(empty_panel, _groups(GROUPS), kind="theme")
    b = build_scores(_two_day_panel(), empty_groups, kind="theme")

    assert a.empty and list(a.columns) == list(SCORE_COLUMNS)
    assert b.empty and list(b.columns) == list(SCORE_COLUMNS)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_leadlag.py -v`
Expected: 새 테스트 8개 FAIL — `ImportError: cannot import name 'build_scores'`

- [ ] **Step 3: 최소 구현** (날짜 이동은 Task 4 에서 붙인다. 여기서는 `trade_date` 를 임시로 `next_trading_day_map` 으로 채우되 마지막 날 처리는 Task 4 테스트로 고정)

```python
# news_scraper/backtest/leadlag.py 에 추가
MIN_MEMBERS = 5
SCORE_COLUMNS = ("score_date", "trade_date", "stock_code", "window_kind", "score", "same_excess")


def _empty_scores() -> pd.DataFrame:
    return pd.DataFrame(columns=list(SCORE_COLUMNS))


def build_scores(panel: pd.DataFrame, groups: pd.DataFrame, kind: str,
                 min_members: int = MIN_MEMBERS) -> pd.DataFrame:
    """패널 + 그룹표 → 종목 점수 프레임 S (스펙 §4.2~4.5).

    panel  : (date, stock_code, ret)  — clean_panel 출력
    groups : (stock_code, group_id)   — 다중 소속 허용
    kind   : "theme" | "wics"         — window_kind 에 그대로 들어간다

    자기 제외 평균은 합과 개수로 구한다: (sum_g − r_i)/(n_g − 1). 그룹 크기
    n_g 는 «그날 패널에 있는» 멤버 수다(그룹표에만 있는 종목은 세지 않는다).
    """
    if panel.empty or groups.empty:
        return _empty_scores()

    g = groups.copy()
    g["stock_code"] = g["stock_code"].astype(str).str.strip()
    g = g.drop_duplicates(subset=["stock_code", "group_id"])

    # 시장 평균 m(D): 분류 유무와 무관하게 그날 패널 전체.
    market = panel.groupby("date")["ret"].mean().rename("m")

    mem = panel.merge(g, on="stock_code", how="inner")
    if mem.empty:
        return _empty_scores()

    agg = (mem.groupby(["date", "group_id"])["ret"]
              .agg(g_sum="sum", g_n="size").reset_index())
    mem = mem.merge(agg, on=["date", "group_id"], how="left")
    mem = mem[mem["g_n"] >= min_members]
    if mem.empty:
        return _empty_scores()

    mem["loo"] = (mem["g_sum"] - mem["ret"]) / (mem["g_n"] - 1)
    mem = mem.merge(market, left_on="date", right_index=True, how="left")
    mem["resid"] = mem["loo"] - mem["m"]

    score = (mem.groupby(["date", "stock_code"])["resid"].mean()
                .rename("score").reset_index())

    same = panel.merge(market, left_on="date", right_index=True, how="left")
    same["same_excess"] = same["ret"] - same["m"]
    score = score.merge(same[["date", "stock_code", "same_excess"]],
                        on=["date", "stock_code"], how="left")

    nxt = next_trading_day_map(panel["date"].unique())
    score["trade_date"] = score["date"].map(nxt)
    score = score[score["trade_date"].notna()]

    out = score.rename(columns={"date": "score_date"})
    out["window_kind"] = kind
    out = (out[list(SCORE_COLUMNS)]
              .sort_values(["trade_date", "stock_code"])
              .reset_index(drop=True))
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_leadlag.py -v`
Expected: 14 PASS

- [ ] **Step 5: 커밋**

```bash
git add news_scraper/backtest/leadlag.py tests/test_leadlag.py
git commit -m "feat(backtest): build_scores — 자기 제외 그룹 평균·시장 차감·다중 소속 평균·MIN_MEMBERS"
```

---

### Task 4: 날짜 이동과 기존 모듈 연결

**Files:**
- Modify: `news_scraper/backtest/leadlag.py` (필요 시)
- Test: `tests/test_leadlag.py`

**Interfaces:**
- Consumes: `build_scores`, `news_scraper.backtest.returns.attach_returns`, `news_scraper.backtest.metrics.daily_ic`
- Produces: 없음(검증만). 이 Task 가 통과하면 `S` 는 그대로 `attach_returns(S, rets)` 와 `daily_ic(df, "score", "excess_h1")` 에 들어간다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_leadlag.py 에 추가
from news_scraper.backtest.metrics import daily_ic
from news_scraper.backtest.returns import attach_returns


def test_trade_date는_다음_거래일이다():
    """D1(월) 점수 → trade_date D2(화). 금→월·연휴는 next_trading_day_map 테스트가 고정."""
    s = build_scores(_two_day_panel(), _groups(GROUPS), kind="theme")
    d1 = s[s["score_date"] == D1]

    assert set(d1["trade_date"]) == {D2}


def test_마지막_날짜의_점수는_버린다():
    s = build_scores(_two_day_panel(), _groups(GROUPS), kind="theme")

    assert D2 not in set(s["score_date"])
    assert s["trade_date"].notna().all()


def test_출력은_trade_date_stock_code_순으로_정렬돼_재현된다():
    """quantile_returns 의 qcut 은 동점을 입력 순서로 끊으므로 S 의 순서가 결정적이어야 한다."""
    s = build_scores(_two_day_panel(), _groups(GROUPS), kind="theme")
    expected = s.sort_values(["trade_date", "stock_code"]).reset_index(drop=True)

    pd.testing.assert_frame_equal(s, expected)


def test_attach_returns와_daily_ic에_그대로_들어간다():
    """통합(스펙 §10-8). rets 는 load_returns 모양으로 손으로 만든다.
    D2 진입 수익을 D1 점수 순서와 같게 주면 excess_h1 IC 가 +1 이다."""
    s = build_scores(_two_day_panel(), _groups(GROUPS), kind="theme")
    ranked = s.sort_values("score").reset_index(drop=True)
    rets = pd.DataFrame({
        "trade_date": [D2] * len(ranked),
        "stock_code": ranked["stock_code"],
        "ret_h0": [0.001 * i for i in range(len(ranked))],
        "ret_h1": [0.002 * i for i in range(len(ranked))],
        "ret_h5": [None] * len(ranked),
    })

    df = attach_returns(s, rets)

    assert "excess_h1" in df.columns
    assert len(df) == len(s)
    assert df["excess_h1"].notna().all()
    assert df["excess_h5"].isna().all()  # 일부 horizon 만 NaN 이어도 행을 잃지 않는다
    ic = daily_ic(df, score_col="score", ret_col="excess_h1")
    assert list(ic.index) == [D2]
    assert ic.iloc[0] == pytest.approx(1.0)
    same = daily_ic(df, score_col="score", ret_col="same_excess")
    assert len(same) == 1  # 대조군 IC 도 같은 프레임에서 바로 나온다
```

- [ ] **Step 2: 실행**

Run: `python -m pytest tests/test_leadlag.py -v`
Expected: Task 3 구현이 이미 날짜 이동을 포함하므로 4 PASS 가 기대된다. 하나라도 FAIL 이면 `build_scores` 의 `nxt`/정렬 부분을 고친다. (`attach_returns` 는 `trade_date` 로 병합하므로 `S.trade_date` 가 `datetime.date` 여야 한다. `pd.Series.map` 결과가 object dtype 의 date 객체인지 확인.)

- [ ] **Step 3: 커밋**

```bash
git add tests/test_leadlag.py news_scraper/backtest/leadlag.py
git commit -m "test(backtest): 선행-후행 날짜 이동·정렬·attach_returns/daily_ic 통합 고정"
```

---

### Task 5: `load_groups` — WICS·테마 그룹표

**Files:**
- Modify: `news_scraper/backtest/leadlag.py`
- Test: 없음(SQL, 스펙 §10). Task 7 소규모 실측에서 행 수를 확인한다.

**Interfaces:**
- Produces:
  - `KINDS = ("theme", "wics")`
  - `THEME_SNAP_DATE = date(2026, 10, 7)`
  - `load_groups(db, kind: str, theme_snap_date: date = THEME_SNAP_DATE) -> pd.DataFrame` — 컬럼 `stock_code, group_id`. `kind` 가 KINDS 밖이면 `ValueError`.

- [ ] **Step 1: 구현**

```python
# news_scraper/backtest/leadlag.py 에 추가
KINDS = ("theme", "wics")
THEME_SNAP_DATE = date(2026, 10, 7)   # 스펙 §1.3 — 소속표는 이 스냅샷 한 장으로 고정
WICS_EXCLUDED_SECTOR = "기타"           # 스펙 §0.2 — 1,261 종목(31%), 분류 정보 없음


def load_groups(db, kind: str, theme_snap_date: date = THEME_SNAP_DATE) -> pd.DataFrame:
    """분류표 → (stock_code, group_id).

    theme : theme_member_daily 의 snap_date=theme_snap_date 행. group_id = theme_no.
    wics  : stock_sector 에서 sector_name='기타' 제외. group_id = sector_code.
    둘 다 robotrader 소유 표라 읽기만 한다.
    """
    if kind not in KINDS:
        raise ValueError(f"kind 는 {KINDS} 중 하나여야 한다: {kind!r}")

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            if kind == "theme":
                cur.execute("""
                    SELECT trim(stock_code), theme_no
                    FROM theme_member_daily
                    WHERE snap_date = %s
                    ORDER BY 1, 2
                """, (theme_snap_date,))
            else:
                cur.execute("""
                    SELECT trim(stock_code), sector_code
                    FROM stock_sector
                    WHERE sector_name IS DISTINCT FROM %s
                      AND sector_code IS NOT NULL
                    ORDER BY 1, 2
                """, (WICS_EXCLUDED_SECTOR,))
            rows = cur.fetchall()
    finally:
        conn.rollback()
        db._put_connection(conn)

    out = pd.DataFrame(rows, columns=["stock_code", "group_id"])
    logger.info("load_groups(%s): %d행 · 종목 %d · 그룹 %d", kind, len(out),
                out["stock_code"].nunique(), out["group_id"].nunique())
    return out
```

- [ ] **Step 2: 실 DB 로 한 번 실측 (저장 안 함)**

Run:
```bash
python -c "from datetime import date; from news_scraper.database import NewsDatabase; from news_scraper.backtest.leadlag import load_groups, load_panel; db=NewsDatabase(); t=load_groups(db,'theme'); w=load_groups(db,'wics'); p=load_panel(db, date(2026,9,1), date(2026,10,7)); print(len(t), t.stock_code.nunique(), t.group_id.nunique()); print(len(w), w.stock_code.nunique(), w.group_id.nunique()); print(len(p), p.date.nunique(), type(p.date.iloc[0]))"
```
Expected: 테마 `6521 2393 264`, WICS 종목 약 `2824`, 그룹 `78`, 패널 날짜 수 `24`+, `<class 'datetime.date'>`. 수치가 스펙 §0 과 다르면 SQL 을 고친다.

- [ ] **Step 3: 전체 테스트 후 커밋**

Run: `python -m pytest tests/test_leadlag.py tests/test_backtest_returns.py tests/test_backtest_metrics.py -q`
Expected: 전부 PASS

```bash
git add news_scraper/backtest/leadlag.py
git commit -m "feat(backtest): load_groups — 테마(10-07 스냅샷 고정)·WICS(기타 제외) 그룹표"
```

---

### Task 6: 실행기 `scripts/run_leadlag_backtest.py` + `holm_adjust`

**Files:**
- Create: `scripts/run_leadlag_backtest.py`
- Test: `tests/test_run_leadlag_backtest.py`

**Interfaces:**
- Consumes: `leadlag.load_panel/load_groups/build_scores/KINDS/THEME_SNAP_DATE`, `returns.load_returns/attach_returns/HORIZONS`, `metrics.daily_ic/ic_summary/quantile_returns/hit_rate/permutation_test`, `scripts.run_news_backtest._fmt_metric/_ic_obs_count/_cross_section_stats`
- Produces:
  - `holm_adjust(pvals: Dict[str, float]) -> Dict[str, float]` — Holm step-down 보정 p. NaN 은 그대로 NaN 으로 두고 보정 대상(m)에서 뺀다.
  - `PRIMARY_ARM = ("theme", "main", 1)` — (kind, period_name, horizon)
  - `parse_period(s: str) -> Tuple[str, date, date]` — `"main=2024-01-02:2026-10-07"` 형식.
  - CLI: `--kind theme|wics|both`(기본 both) · `--period NAME=START:END`(반복 가능, 기본 `main=2024-01-02:2026-10-07`) · `--permutations`(기본 500) · `--out PATH`(결과 텍스트 저장, 선택)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_run_leadlag_backtest.py
"""run_leadlag_backtest 의 계산 헬퍼 — Holm 보정과 구간 파싱.

출력 조립(표 문자열)은 테스트하지 않는다(run_news_backtest 와 같은 원칙).
"""
from datetime import date

import pytest

from scripts.run_leadlag_backtest import holm_adjust, parse_period


def test_holm_보정은_작은_p부터_역순_배수를_곱하고_단조성을_지킨다():
    """m=3: 정렬 .01(a) .03(c) .04(b) → .01×3=.03, .03×2=.06, .04×1=.04 →
    단조성(앞보다 작아질 수 없음)으로 b 는 .06."""
    adj = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03})

    assert adj["a"] == pytest.approx(0.03)
    assert adj["c"] == pytest.approx(0.06)
    assert adj["b"] == pytest.approx(0.06)


def test_holm_보정은_1을_넘지_않는다():
    adj = holm_adjust({"a": 0.5, "b": 0.6})

    assert adj["a"] == pytest.approx(1.0)
    assert adj["b"] == pytest.approx(1.0)


def test_holm_보정은_NaN을_대상에서_빼고_그대로_돌려준다():
    import math
    adj = holm_adjust({"a": 0.01, "b": float("nan")})

    assert adj["a"] == pytest.approx(0.01)   # m=1
    assert math.isnan(adj["b"])


def test_빈_입력은_빈_출력():
    assert holm_adjust({}) == {}


def test_parse_period():
    assert parse_period("main=2024-01-02:2026-10-07") == (
        "main", date(2024, 1, 2), date(2026, 10, 7))


def test_parse_period는_형식이_틀리면_거부한다():
    with pytest.raises(ValueError):
        parse_period("2024-01-02:2026-10-07")
    with pytest.raises(ValueError):
        parse_period("main=2026-10-07:2024-01-02")  # start > end
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_run_leadlag_backtest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.run_leadlag_backtest'`

- [ ] **Step 3: 구현**

```python
# scripts/run_leadlag_backtest.py
"""섹터 선행-후행 백테스트 — 점수 생성 → 수익 결합 → 측정 → 표.

    python scripts/run_leadlag_backtest.py                                  # H1 arm 포함 main 구간, both
    python scripts/run_leadlag_backtest.py --kind theme --period test=2026-08-01:2026-10-07 --permutations 50
    python scripts/run_leadlag_backtest.py --period main=2024-01-02:2026-10-07 --period aux=2021-01-04:2023-12-29 --out docs/superpowers/specs/leadlag_run.txt

설계: docs/superpowers/specs/2026-10-07-sector-leadlag-design.md

이 파일은 조립과 출력만 한다. 로직은 leadlag.py / returns.py / metrics.py 에
있고 거기서 테스트된다. 여기서 지키는 것:

1. NaN/inf 지표는 "측정불가" 로 찍는다(_fmt_metric, run_news_backtest 재사용).
2. 주 가설 arm(PRIMARY_ARM) 은 [H1] 표시와 함께 판정 줄을 따로 찍는다.
   나머지 arm 의 순열 p 는 Holm 보정값을 나란히 찍는다(스펙 §7).
3. 당일 IC(same_excess) 를 익일 IC 와 같은 줄에 둔다 — 동조화 판별표(§7).
4. 표본(거래일 수·횡단면 중앙값·그룹표 행 수)은 실행마다 실측해 찍는다.
"""
import argparse
import logging
import math
import os
import sys
from datetime import date, datetime
from typing import Dict, List, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_news_backtest import _cross_section_stats, _fmt_metric, _ic_obs_count  # noqa: E402

PRIMARY_ARM = ("theme", "main", 1)          # (kind, period_name, horizon) — 스펙 §7
DEFAULT_PERIOD = "main=2024-01-02:2026-10-07"
HIT_TOP_NS = (10, 50)
N_QUANTILES = 5


def parse_period(s: str) -> Tuple[str, date, date]:
    """'NAME=YYYY-MM-DD:YYYY-MM-DD' → (name, start, end)."""
    if "=" not in s or ":" not in s:
        raise ValueError(f"--period 형식은 NAME=START:END 다: {s!r}")
    name, rng = s.split("=", 1)
    a, b = rng.split(":", 1)
    start = datetime.strptime(a, "%Y-%m-%d").date()
    end = datetime.strptime(b, "%Y-%m-%d").date()
    if not name or start > end:
        raise ValueError(f"--period 가 잘못됐다(이름 없음 또는 start > end): {s!r}")
    return name, start, end


def holm_adjust(pvals: Dict[str, float]) -> Dict[str, float]:
    """Holm step-down. 작은 p 부터 (m − 순위 + 1) 배, 앞 값보다 작아지지 않게,
    1 로 캡. NaN 은 보정 대상에서 빼고 NaN 그대로 돌려준다."""
    valid = {k: v for k, v in pvals.items() if v is not None and math.isfinite(v)}
    out: Dict[str, float] = {k: float("nan") for k in pvals if k not in valid}
    m = len(valid)
    running = 0.0
    for rank, (k, p) in enumerate(sorted(valid.items(), key=lambda kv: kv[1])):
        adj = min(1.0, max(running, p * (m - rank)))
        out[k] = adj
        running = adj
    return out


def _arm_key(kind: str, period: str, h: int) -> str:
    return f"{kind}·{period}·h{h}"


def _run_arm_set(db, kind: str, period: str, start: date, end: date,
                 n_perm: int, lines: List[str]) -> Dict[str, dict]:
    """한 (분류, 구간) 에 대해 h0/h1/h5 를 돌리고 arm_key → 결과 dict 를 돌려준다."""
    from news_scraper.backtest.leadlag import build_scores, load_groups, load_panel
    from news_scraper.backtest.metrics import (daily_ic, hit_rate, ic_summary,
                                               permutation_test, quantile_returns)
    from news_scraper.backtest.returns import HORIZONS, attach_returns, load_returns

    groups = load_groups(db, kind)
    panel = load_panel(db, start, end)
    scores = build_scores(panel, groups, kind=kind)
    lines.append(f"\n[{kind} · {period} {start}~{end}] 그룹표 {len(groups):,}행"
                 f"(종목 {groups['stock_code'].nunique():,} · 그룹 {groups['group_id'].nunique():,})"
                 f" · 패널 {len(panel):,}행 · 거래일 {panel['date'].nunique()} · 점수 {len(scores):,}행")
    if scores.empty:
        lines.append("  관측 없음")
        return {}

    rets = load_returns(db, start, end)
    df = attach_returns(scores, rets)
    if df.empty:
        lines.append("  수익 결합 0행 — trade_date 형식(date 객체) 또는 기간을 확인하라")
        return {}
    lines.append(f"  수익 결합 {len(df):,}행 · 거래일 {df['trade_date'].nunique()}")

    same_ic = daily_ic(df, score_col="score", ret_col="same_excess")
    same_s = ic_summary(same_ic)
    lines.append(f"  당일(대조군) IC {_fmt_metric(same_s['mean_ic'], '+.4f')} "
                 f"· t {_fmt_metric(same_s['t_stat'], '+.2f')} · 거래일 {same_s['n_days']}")

    results: Dict[str, dict] = {}
    for h in HORIZONS:
        col = f"excess_h{h}"
        if col not in df.columns or df[col].notna().sum() == 0:
            continue
        ic = daily_ic(df, score_col="score", ret_col=col)
        s = ic_summary(ic)
        obs = _ic_obs_count(df, ic, score_col="score", ret_col=col)
        cs = _cross_section_stats(df, col, score_col="score")
        med = cs["median"] if cs else float("nan")
        hrs = {n: hit_rate(df, col, top_n=n, score_col="score") for n in HIT_TOP_NS}
        perm = permutation_test(df, col, n_iter=n_perm, score_col="score")
        key = _arm_key(kind, period, h)
        tag = " [H1]" if (kind, period, h) == PRIMARY_ARM else ""
        results[key] = {"kind": kind, "period": period, "h": h, "summary": s,
                        "p": perm["p_value"], "same_ic": same_s["mean_ic"], "tag": tag}
        hr_str = " · ".join(f"히트율top{n} {_fmt_metric(v, '.3f')}" for n, v in hrs.items())
        lines.append(f"  h{h}{tag}: 평균IC {_fmt_metric(s['mean_ic'], '+.4f')} "
                     f"(거래일 {s['n_days']}·관측 {obs:,}·횡단면 중앙값 {_fmt_metric(med, '.0f')}) "
                     f"· t {_fmt_metric(s['t_stat'], '+.2f')} · {hr_str} "
                     f"· 순열 p={_fmt_metric(perm['p_value'], '.3f')} ({perm['n_iter']}회)")

    q = quantile_returns(df, "excess_h1", n_q=N_QUANTILES, score_col="score")
    if not q.empty:
        cells = " ".join(f"Q{int(r.quantile) + 1} {r.mean_excess:+.4f}(n={r.n:,})"
                         for r in q.itertuples())
        spread = q["mean_excess"].iloc[-1] - q["mean_excess"].iloc[0]
        lines.append(f"  h1 분위수(행가중): {cells} · Q5-Q1 {_fmt_metric(spread, '+.4f')} "
                     f"· 동점비율 중앙값 {_fmt_metric(q.attrs.get('tie_fraction_median'), '.3f')}")
    return results


def _verdict(primary: dict) -> str:
    """스펙 §7 — 통과 = p<0.05 & 평균IC>0. 동조화 판별표의 읽기를 같이 적는다."""
    s, p, same = primary["summary"], primary["p"], primary["same_ic"]
    if not (math.isfinite(s["mean_ic"]) and math.isfinite(p)):
        return "H1 판정: 측정불가"
    passed = p < 0.05 and s["mean_ic"] > 0
    reversal = p < 0.05 and s["mean_ic"] < 0
    if passed:
        reading = "선행-후행 있음 → 스펙 §9 (시총 1위 변형·분류 일치 확인)"
    elif reversal:
        reading = "익일 되돌림(음) → 부호 반전 활용은 별건 브레인스토밍"
    else:
        reading = ("동조화뿐, 알파 아님 → 끝" if (math.isfinite(same) and same > 0.05)
                   else "효과 없음(당일 IC 도 작음 → 분류가 그룹을 못 묶음)")
    return (f"H1 판정: {'통과' if passed else '실패'} — 평균IC {s['mean_ic']:+.4f}, "
            f"순열 p={p:.3f}, 당일 IC {_fmt_metric(same, '+.4f')} → {reading}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=("theme", "wics", "both"), default="both")
    ap.add_argument("--period", action="append", default=None,
                    help="NAME=START:END (반복 가능). 기본 " + DEFAULT_PERIOD)
    ap.add_argument("--permutations", type=int, default=500)
    ap.add_argument("--out", default=None, help="출력을 이 파일에도 저장")
    args = ap.parse_args()

    from news_scraper.backtest.leadlag import KINDS, THEME_SNAP_DATE
    from news_scraper.database import NewsDatabase

    kinds = list(KINDS) if args.kind == "both" else [args.kind]
    periods = [parse_period(p) for p in (args.period or [DEFAULT_PERIOD])]
    db = NewsDatabase()

    lines: List[str] = [f"섹터 선행-후행 백테스트 · {datetime.now():%Y-%m-%d %H:%M} · "
                        f"테마 스냅샷 {THEME_SNAP_DATE} · 순열 {args.permutations}회"]
    results: Dict[str, dict] = {}
    for name, start, end in periods:
        for kind in kinds:
            results.update(_run_arm_set(db, kind, name, start, end, args.permutations, lines))

    lines.append("\n" + "=" * 74)
    if not results:
        lines.append("관측 없음")
        print("\n".join(lines))
        return 1

    primary_key = _arm_key(*PRIMARY_ARM)
    secondary = {k: v["p"] for k, v in results.items() if k != primary_key}
    adj = holm_adjust(secondary)
    lines.append("arm 표 (순열 p · Holm 보정 p — 주 가설은 보정 없음):")
    for k, v in results.items():
        s = v["summary"]
        padj = "—(H1)" if k == primary_key else _fmt_metric(adj.get(k), ".3f")
        lines.append(f"  {k:<24} IC {_fmt_metric(s['mean_ic'], '+.4f')} "
                     f"p {_fmt_metric(v['p'], '.3f')} Holm {padj} 당일IC {_fmt_metric(v['same_ic'], '+.4f')}")
    if primary_key in results:
        lines.append(_verdict(results[primary_key]))
    else:
        lines.append("H1 arm(theme·main·h1) 이 이번 실행에 없다 — 판정 생략")

    lines.append("한계: 테마·WICS 소속표는 현재 스냅샷을 과거에 적용(미래 참조, 결과는 상한선) · "
                 "생존 편향(상장폐지 종목 없음) · 수정주가 부재(±30% 밖만 제거) · "
                 "h1/h5 는 «다음 관측행»(거래정지 결측 시 D+2/D+6) · 밤사이 갭 미측정 · "
                 "일별 IC 자기상관(t 는 참고, 판정은 순열 p) · "
                 "평균IC 는 일자 가중, 히트율·분위수는 행 가중")

    text = "\n".join(lines)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_run_leadlag_backtest.py tests/test_leadlag.py -v`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add scripts/run_leadlag_backtest.py tests/test_run_leadlag_backtest.py
git commit -m "feat(backtest): 선행-후행 실행기 — 분류×구간×horizon arm 표·Holm 보정·H1 판정 줄"
```

---

### Task 7: 소규모 실측 — 행 수·소요 시간

**Files:** 없음(실행만). 결과는 Task 8 문서의 「재현」 절에 적는다.

- [ ] **Step 1: 2 개월 구간, 순열 50 회로 돌려 시간을 잰다**

Run (PowerShell):
```powershell
Measure-Command { python scripts/run_leadlag_backtest.py --kind theme --period test=2026-08-01:2026-10-07 --permutations 50 | Tee-Object -FilePath "$env:TEMP\leadlag_smoke.txt" }
Get-Content "$env:TEMP\leadlag_smoke.txt"
```
Expected:
- 그룹표 `6,521행(종목 2,393 · 그룹 264)`, 패널 거래일 약 45, 점수 행 ≈ 2,300 × 44.
- 수익 결합 행 > 0. `0행` 이면 Global Constraints 의 date 객체 조항을 의심한다.
- h0/h1/h5 세 줄 모두 숫자(측정불가 아님). 당일 IC 는 양수로 뚜렷해야 한다(같은 테마가 같이 움직인다는 뜻. 0 근처면 그룹 병합이 잘못된 것).
- 소요 시간 기록. 순열 1 회당 시간 ≈ (총 시간 − 비순열 부분)/50/3.

- [ ] **Step 2: 전체 실행 시간 추정**

673 거래일 / 44 거래일 ≈ 15 배, 순열 500/50 = 10 배, arm 12 개. 추정 = 순열 1 회 시간 × 15 × 500 × 12 (+ WICS·aux 패널 로드). **1 시간 넘으면** Task 8 에서 `--permutations` 를 부 가설만 줄일 수 있도록 실행기에 `--permutations-secondary` 인자를 추가한다(주 가설은 500 유지, 스펙 §6). 1 시간 안이면 그대로 간다.

- [ ] **Step 3: WICS 도 같은 구간으로 한 번**

Run: `python scripts/run_leadlag_backtest.py --kind wics --period test=2026-08-01:2026-10-07 --permutations 50`
Expected: 그룹표 종목 약 2,824 · 그룹 78. 당일 IC 양수.

(커밋 없음. 실행기 수정이 필요했으면 그 수정만 `fix(backtest): …` 로 커밋.)

---

### Task 8: 본 실행과 결과 문서

**Files:**
- Create: `docs/superpowers/specs/<실행일>-sector-leadlag-result.md`
- Create: `docs/superpowers/specs/<실행일>-sector-leadlag-run.txt` (실행기 `--out` 원문)

- [ ] **Step 1: 본 실행 (백그라운드, 타임아웃 넉넉히)**

Run:
```bash
python scripts/run_leadlag_backtest.py --kind both --period main=2024-01-02:2026-10-07 --period aux=2021-01-04:2023-12-29 --permutations 500 --out docs/superpowers/specs/$(date +%F)-sector-leadlag-run.txt
```
Expected: 종료 코드 0, arm 표 12 줄, `H1 판정:` 줄.

- [ ] **Step 2: 결과 문서 작성** — 아래 뼈대를 채운다. 숫자는 전부 run.txt 에서 옮긴다. 리터럴로 추정하지 않는다.

```markdown
# 섹터 선행-후행 백테스트 — 실행 결과 (<실행일>)

설계: `2026-10-07-sector-leadlag-design.md` · 계획: `../plans/2026-10-07-sector-leadlag-backtest.md` · 원문: `<실행일>-sector-leadlag-run.txt`

재현:
```
python scripts/run_leadlag_backtest.py --kind both --period main=2024-01-02:2026-10-07 --period aux=2021-01-04:2023-12-29 --permutations 500
```
소요 <분> · 테마 스냅샷 2026-10-07 · 그룹표 테마 <행>/WICS <행> · 패널 main <거래일> / aux <거래일>

## 답 (스펙 §7 H1 판정)

**<통과/실패>** — theme·main·h1 평균 IC <값>, 순열 p <값>, 당일 IC <값>.
동조화 판별표 읽기: <한 줄>.
분류 일치: WICS·main·h1 IC <값>, Holm p <값> → <같다/다르다>.

## arm 표

| arm | 평균 IC | t | 거래일 | 횡단면 중앙값 | 순열 p | Holm p | 당일 IC |
|---|---|---|---|---|---|---|---|
| theme·main·h1 [H1] | | | | | | — | |
| … 12 줄 |

## 분위수·히트율 (h1)

| arm | Q1 | Q2 | Q3 | Q4 | Q5 | Q5−Q1 | 히트율 top10 | top50 |

## 이 결과를 어떻게 쓸 것인가

- 실패 → 끝. 봇 통합 없음. 메모리 「섹터 선행-후행 연구」를 「검정 완료·효과 없음」으로.
- 통과 → 스펙 §9: 시총 1위 리더 변형 + 분류 일치 확인(별 Task). 통합 설계는 별도 브레인스토밍.

## 한계 (실행기 푸터 그대로)
```

- [ ] **Step 3: 커밋**

```bash
git add docs/superpowers/specs/*-sector-leadlag-result.md docs/superpowers/specs/*-sector-leadlag-run.txt
git commit -m "docs(backtest): 섹터 선행-후행 백테스트 실행 결과 — H1 판정"
```

- [ ] **Step 4: 사장님께 판정 보고.** H1 통과 시 §9 의 추가 2 가지는 **이 계획 밖**이다. 새 Task 로 계획을 덧붙이기 전에 보고한다.

---

## Self-Review

**1. Spec coverage**
- §4.1 패널 필터 → Task 1. §4.2 자기 제외·min_members → Task 3. §4.3 다중 소속 평균 → Task 3. §4.4 다음 거래일·h 정의 → Task 2·4(수익은 `load_returns` 재사용). §4.5 same_excess → Task 3·4. §5 두 구간 → Task 6 `--period` 반복·Task 8. §6 지표(IC·당일 IC·분위수·히트율 10/50·순열·횡단면) → Task 6. §7 H1·Holm·판정표 → Task 6 `_verdict`·`holm_adjust`. §8 한계 푸터 → Task 6. §9 멈춤 규칙 → Task 8 Step 4. §10 테스트 1~8 → Task 1~4. §11 산출물 → Task 6·8. §12 실행 순서 → Task 7·8.
- 빠진 것: 없음. §9 의 「시총 1위 변형」은 스펙이 H1 통과 후로 미뤘고 YAGNI 로 이 계획에서 뺐다.

**2. Placeholder scan** — `<실행일>`·`<값>` 은 Task 8 문서 뼈대의 채울 칸이며 실행 결과에서만 나온다. 코드 블록에 TODO 없음.

**3. Type consistency** — `build_scores(panel, groups, kind, min_members)` / `load_groups(db, kind, theme_snap_date)` / `load_panel(db, start, end)` / `next_trading_day_map(dates)` / `holm_adjust(pvals)` / `parse_period(s)` 가 Task 간 동일. `S` 컬럼 `SCORE_COLUMNS` 와 실행기의 `score_col="score"`·`same_excess` 일치. `attach_returns` 가 요구하는 `trade_date, stock_code, window_kind` 포함.

**4. Review Focus** — 5 항목 각각 Task 1·3·3/6·1·2/4 테스트에 핀됐다.
