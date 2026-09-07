# 섹터 뉴스 부스트 (스펙 B) — NewsQuant 측 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 뉴스를 KSIC 3자리 섹터에 귀속(키워드 사전 + `related_stocks` 종목매핑)해 섹터별 점수 `score_signed ∈ [−1, +1]` 를 10분마다 공유 DB 표 `sector_news_score` 에 쓴다. 봇(kis-trading-template)은 이 표를 읽기만 한다.

**Architecture:** 순수 모듈 둘(`sector_keywords.py` 사전 로드·검증·매칭 / `sector_news_aggregator.py` 창·기여도·집계 — 둘 다 DB 를 모른다) + 오케스트레이션 하나(`sector_news_job.py` — `db` 를 인자로 받아 읽기→집계→쓰기, 예외를 밖으로 내지 않는다) + `database.py` 에 DDL·읽기·쓰기(기존 관례대로 **DB 쓰기는 이 파일뿐**) + 스케줄러 잡 1개 + 점검용 API 1개. 스펙 §2.1 의 `sector_news_aggregator.py` 를 이 계획에서 **두 순수 모듈로 나눈다**(파일당 책임 하나).

**Tech Stack:** Python 3.9 (VS 번들 `python`, NewsQuant 는 venv 없음) · `pyyaml` 6 · `psycopg2`(`extras.execute_values`) · `apscheduler` · FastAPI · pytest 8 · PostgreSQL 16 `kis_template` @ localhost:5433 (NewsQuant 접속 롤 `postgres`)

**Spec:** `D:\GIT\kis-trading-template\RoboTrader_template\docs\superpowers\specs\2026-09-06-sector-news-boost-design.md` (v1 · 사장님 승인 2026-09-06) — 이 계획은 그 문서의 §2.1 · §3.1 · §3.2 · §3.4 · §4 · §7.1 을 구현한다.

---

## Global Constraints

스펙에서 그대로 옮긴다 — 매 태스크에서 다시 읽을 것:

- **봇은 HTTP 를 쓰지 않는다** — 두 리포 사이 계약은 표 두 개(`fn_sector_map_as_of` 읽기 · `sector_news_score` 읽기)뿐
- **DB 쓰기는 `news_scraper/database.py` 한 곳** (기존 관례)
- **새 표는 `ALTER TABLE ... OWNER TO robotrader`** (DB 관례: 67표 전부 robotrader 소유 · 봇이 읽어야 함). 실패는 WARNING, 치명 아님
- **`fn_sector_map_as_of` 부재·실패 → 경로 B 만 끄고 계속** (WARNING 1줄 · `n_stock=0`). 경로 A 는 스펙 A 에 의존하지 않는다
- **스펙 A 표 4개는 읽기만** (`stock_sector_map`·`sector_daily_stats`·`ksic_code_name`·`sector_ksic_nodata`) · `news_stock`(orphan) 건드리지 않음
- **집계 상수는 모듈 상수** (`config.yaml` 에 넣지 않는다): `MIN_N=3` `K_SCALE=2.0` `W_KW_TITLE=1.0` `W_KW_BODY=0.5` `W_STOCK=0.7` `MAX_CODES_PER_NEWS=5` `BODY_CHARS=2000` `DIR_EPS=0.1` `TOP_NEWS=5` `DEFAULT_W_SRC=0.9`
- **창 = 직전 평일 15:30 ~ now** · `trade_date` = 평일 ∧ now < 15:30 이면 오늘, 아니면 다음 평일. 공휴일 달력 없음(무시)
- **🆕 동결(스펙 정정 v1.1)**: 평일 **09:05 ≤ now < 15:30** 은 쓰지 않는다. 봇이 09:00 에 읽은 값이 그날 행으로 남아야 §8-① 평가가 가능하다(UPSERT 가 덮어쓰므로)
- **무징후 절단 금지** — `related_stocks` 5개 초과로 경로 B 를 건너뛴 건수는 summary + WARNING
- **예외는 잡 안에서 잡는다** — 스케줄러를 죽이지 않는다(기존 `_handle_crawler_result` 관례)
- **파싱 실패는 `None`/0.0 이 아니라 명시적으로** — `sentiment_score` 가 None 이면 0.0 으로 «간주»하되 기여도만 0, 행은 남긴다
- **워크트리에서 작업** · 라이브 디렉터리(`D:\GIT\NewsQuant`, 07:40 자동 기동)에서 테스트 금지
- **테스트 인코딩**: 모든 pytest 실행은 `PYTHONUTF8=1` 접두

---

## File Structure

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `news_scraper/sector_keywords.py` | YAML 로드·검증(`SectorKeywordError`) · `match_sectors()` (ko 부분문자열 · en 단어경계 · exclude · 제목/본문) | 신규 |
| `news_scraper/data/sector_keywords.yaml` | 49섹터 한/영 키워드 사전 · `version` | 신규 |
| `news_scraper/sector_news_aggregator.py` | `compute_window()` `is_frozen()` `split_related_stocks()` `attribute_news()` `aggregate()` · 모듈 상수 | 신규 |
| `news_scraper/sector_news_job.py` | `run_sector_news_job(db, now=None, kw_path=None) -> Dict` 오케스트레이션 · `now_kst_naive()` | 신규 |
| `news_scraper/database.py` | `SECTOR_NEWS_DDL` · `init_sector_news_tables()` · `get_news_in_window()` · `get_sector_map_as_of()` · `write_sector_news_result()` · `get_sector_news_scores()` | 수정 |
| `news_scraper/scheduler.py` | `run_sector_news_aggregation()` · `setup_schedule()` 잡 1개 · `start()` 첫 수집 뒤 1회 | 수정 |
| `news_scraper/api/server.py` | `GET /api/sector/news-score` | 수정 |
| `pyproject.toml` (루트, 신규) · `requirements.txt` · `tests/conftest.py` | pytest 인프라 · `pyyaml`·`pytest` | 신규/수정 |
| `tests/test_sector_keywords.py` · `tests/test_sector_news_aggregator.py` · `tests/test_sector_news_job.py` · `tests/test_sector_news_db.py` · `tests/test_sector_news_api.py` | §7.1 | 신규 |
| `docs/API_사용가이드.md` | 엔드포인트 1개 추가 | 수정 |

**경계**: `sector_keywords`·`sector_news_aggregator` 는 DB·로거를 모른다(입력은 dict/리스트). `sector_news_job` 만 `db` 객체를 만진다(메서드 4개: `get_news_in_window` `get_sector_map_as_of` `write_sector_news_result` — 그리고 테스트에선 MagicMock 으로 대체된다).

---

## 실행 환경 — 명령 원형

🔴 **모든 명령 블록은 Bash 도구(Git Bash)로 실행한다.** PowerShell 에서는 히어독·`VAR=x cmd` 접두가 파서 오류다.

**워크트리** (라이브 디렉터리는 07:40 마다 자동 기동되므로 거기서 편집·테스트하지 않는다):

```
cd D:/GIT/NewsQuant
git worktree add -b feat/sector-news-score D:/tmp/nq-wt-sector-news main
```

**테스트** (cwd = 워크트리 · `python` = PATH 의 VS 번들 Python 3.9 · pytest 8.4 · pyyaml 6 이미 설치됨):

```
cd D:/tmp/nq-wt-sector-news
PYTHONUTF8=1 python -m pytest tests/test_sector_keywords.py -v
```

한 테스트만: `... -m pytest tests/test_sector_keywords.py::test_이름 -v`. 전체: `PYTHONUTF8=1 python -m pytest -q`. DB 없는 환경에서는 `-m "not db"`.

**DB 테스트**는 실 DB(`localhost:5433/kis_template`, `config.yaml` 이 워크트리에 있다)가 없으면 **skip** 한다(`tests/conftest.py` 의 `db` 픽스처).

**커밋** (메시지는 파일로 — 셸 따옴표 문제 회피):

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
<제목 줄>

<본문>

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/tmp/nq-wt-sector-news && git add <파일들> && git commit -F D:/tmp/nq_commit_msg.txt
```

**모든 커밋 메시지는 위 두 트레일러 줄로 끝나야 한다.**

---

### Task 0: 미커밋 diff 정리 · 워크트리 · pytest 인프라

**Files:**
- Modify (main, 커밋만): `news_scraper/scheduler.py` — 이미 워킹트리에 있는 254줄 diff(타임아웃 후 수확물 회수 리팩터 `_handle_crawler_result`/`_recover_pending_results`)
- Create: `pyproject.toml` (리포 루트)
- Modify: `requirements.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Produces: `tests/conftest.py` 의 `db` 픽스처(`NewsDatabase` 인스턴스, 실 DB 없으면 `pytest.skip`) — Task 6·8 이 쓴다.

- [ ] **Step 1: 미커밋 diff 의 정체 확인**

```
cd D:/GIT/NewsQuant && git status --short && git diff --stat news_scraper/scheduler.py
```

Expected: `M news_scraper/scheduler.py` · `1 file changed, 186 insertions(+), 68 deletions(-)`. `git diff news_scraper/scheduler.py | grep '^+.*def '` 에 `_handle_crawler_result` · `_recover_pending_results` 가 보이면 「타임아웃 후 수확물 회수」 리팩터다(감사 2026-08-23 문서가 「패치됨」이라 적은 그 변경).

- [ ] **Step 2: 사장님 확인 후 그 diff 를 «별도 커밋»으로 남긴다** (AskUserQuestion: 「커밋」/「stash」 중 택일. 스펙 §11 에 「사장님 확인」으로 예약된 항목)

커밋을 택했으면:

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
fix(scheduler): 병렬 크롤링 전체 타임아웃 후 수확물 회수 — 결과 처리를 _handle_crawler_result 로 단일화, 소스당 collection_log 정확히 1줄

as_completed 전체 타임아웃이 for 루프를 이탈시켜 완주한 크롤러의 result() 를 아무도 읽지 않던 결함.
shutdown(wait=True) 뒤 _recover_pending_results 가 회수해 정상 경로로 저장한다.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/GIT/NewsQuant && git add news_scraper/scheduler.py && git commit -F D:/tmp/nq_commit_msg.txt && git status --short
```

stash 를 택했으면: `cd D:/GIT/NewsQuant && git stash push -m "scheduler timeout-recovery WIP" news_scraper/scheduler.py`.

Expected: `git status --short` 에 `M news_scraper/scheduler.py` 가 **없다**(untracked `??` 만 남는다).

- [ ] **Step 3: 워크트리 생성**

```
cd D:/GIT/NewsQuant && git worktree add -b feat/sector-news-score D:/tmp/nq-wt-sector-news main && ls D:/tmp/nq-wt-sector-news/config.yaml
```

Expected: 워크트리 생성 · `config.yaml` 존재(추적 파일이라 따라온다 → DB 테스트가 붙는다).

- [ ] **Step 4: pytest 인프라 파일 작성**

`D:/tmp/nq-wt-sector-news/pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = [
    "db: 실 PostgreSQL(kis_template @ localhost:5433) 필요 — 없으면 skip",
]
```

`requirements.txt` 끝에 두 줄 추가:

```
pyyaml>=6.0
pytest>=8.0
```

`tests/conftest.py`:

```python
"""NewsQuant 테스트 공통 픽스처."""
import pytest


@pytest.fixture(scope="session")
def db():
    """실 DB(kis_template) 연결. 없으면 이 픽스처를 쓰는 테스트를 skip 한다."""
    try:
        import psycopg2
        from news_scraper.database import NewsDatabase
        instance = NewsDatabase()
    except Exception as e:  # OperationalError 포함 — DB 없는 환경
        pytest.skip(f"실 DB 없음: {type(e).__name__}: {e}")
    return instance
```

`tests/test_smoke.py`:

```python
def test_package_imports():
    import news_scraper  # noqa: F401
    from news_scraper.sentiment_analyzer import SentimentAnalyzer
    assert "naver_finance" in SentimentAnalyzer.SOURCE_CREDIBILITY
```

- [ ] **Step 5: 수집 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_smoke.py -v
```

Expected: `1 passed`.

- [ ] **Step 6: 커밋**

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
chore(test): pytest 인프라 — pyproject(testpaths·db 마커)·conftest(db 픽스처)·smoke, requirements 에 pyyaml·pytest

스펙 B(섹터 뉴스 부스트) 구현 준비. pyyaml 은 config.py 가 이미 import 하는데 requirements 에 없던 것.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/tmp/nq-wt-sector-news && git add pyproject.toml requirements.txt tests/conftest.py tests/test_smoke.py && git commit -F D:/tmp/nq_commit_msg.txt
```

---

### Task 1: 키워드 사전 로더·검증

**Files:**
- Create: `news_scraper/sector_keywords.py`
- Test: `tests/test_sector_keywords.py`

**Interfaces:**
- Produces:
  - `class SectorKeywordError(ValueError)`
  - `@dataclass(frozen=True) SectorEntry(key: str, name: str, ko: Tuple[str,...], en: Tuple[str,...], exclude: Tuple[str,...], en_patterns: Tuple[Pattern,...])`
  - `@dataclass(frozen=True) SectorKeywordDict(version: str, sectors: Dict[str, SectorEntry])`
  - `parse_sector_keywords(data) -> SectorKeywordDict` · `load_sector_keywords(path: Optional[Path]=None) -> SectorKeywordDict`
  - `DEFAULT_PATH = news_scraper/data/sector_keywords.yaml`
- 검증 규칙(스펙 §4.2): 키 `^\d{3}$` · `name` 필수 · `ko`/`en` 중 하나 이상 · 한 섹터 안에서 ko∪en∪exclude 중복 금지(**섹터 사이 공유는 허용** — 「임상」이 211·212·701 에 다 있어도 된다. 스펙 「한 뉴스가 여러 섹터에 걸리면 전부 귀속」과 정합)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sector_keywords.py`:

```python
import pytest

from news_scraper.sector_keywords import (
    SectorKeywordError, parse_sector_keywords, load_sector_keywords,
)


def _ok():
    return {
        "version": "test.1",
        "sectors": {
            "261": {"name": "반도체 제조업", "ko": ["반도체", "HBM"], "en": ["semiconductor", "chip"]},
            "641": {"name": "은행 및 저축기관", "ko": ["은행"]},
        },
    }


def test_parse_ok_builds_entries():
    d = parse_sector_keywords(_ok())
    assert d.version == "test.1"
    assert set(d.sectors) == {"261", "641"}
    e = d.sectors["261"]
    assert e.name == "반도체 제조업" and e.ko == ("반도체", "HBM") and e.en == ("semiconductor", "chip")
    assert e.exclude == () and len(e.en_patterns) == 2


def test_key_must_be_three_digits():
    data = _ok(); data["sectors"]["26"] = {"name": "x", "ko": ["a"]}
    with pytest.raises(SectorKeywordError, match="3자리"):
        parse_sector_keywords(data)


def test_int_key_is_normalized_to_str():
    data = _ok(); data["sectors"][212] = {"name": "의약품", "ko": ["제약"]}
    assert "212" in parse_sector_keywords(data).sectors


def test_name_required():
    data = _ok(); del data["sectors"]["641"]["name"]
    with pytest.raises(SectorKeywordError, match="name"):
        parse_sector_keywords(data)


def test_ko_or_en_required():
    data = _ok(); data["sectors"]["641"] = {"name": "은행"}
    with pytest.raises(SectorKeywordError, match="ko 또는 en"):
        parse_sector_keywords(data)


def test_duplicate_keyword_within_sector_rejected():
    data = _ok(); data["sectors"]["261"]["en"] = ["chip", "Chip"]
    with pytest.raises(SectorKeywordError, match="중복"):
        parse_sector_keywords(data)


def test_same_keyword_in_two_sectors_allowed():
    data = _ok(); data["sectors"]["641"]["ko"] = ["은행", "반도체"]
    assert parse_sector_keywords(data).sectors["641"].ko == ("은행", "반도체")


def test_version_required():
    data = _ok(); data["version"] = ""
    with pytest.raises(SectorKeywordError, match="version"):
        parse_sector_keywords(data)


def test_non_string_list_rejected():
    data = _ok(); data["sectors"]["641"]["ko"] = ["은행", 3]
    with pytest.raises(SectorKeywordError, match="문자열 리스트"):
        parse_sector_keywords(data)


def test_load_from_yaml(tmp_path):
    p = tmp_path / "kw.yaml"
    p.write_text('version: "v"\nsectors:\n  "261":\n    name: 반도체 제조업\n    ko: [반도체]\n', encoding="utf-8")
    d = load_sector_keywords(p)
    assert d.sectors["261"].ko == ("반도체",)
```

- [ ] **Step 2: 실패 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_keywords.py -v
```

Expected: 전부 FAIL/ERROR — `ModuleNotFoundError: No module named 'news_scraper.sector_keywords'`.

- [ ] **Step 3: 구현**

`news_scraper/sector_keywords.py`:

```python
"""섹터 키워드 사전 — 로드·검증·매칭 (스펙 B 경로 A). DB·로거를 모른다.

사전 파일: news_scraper/data/sector_keywords.yaml
  version: "2026-09-06.1"
  sectors:
    "261":                      # 🔴 키는 반드시 따옴표 — 3자리 숫자 문자열
      name: 반도체 제조업
      ko: [반도체, HBM]          # 부분문자열 매칭(소문자화)
      en: [semiconductor, chip] # 단어경계 매칭(소문자화)
      exclude: [반도체 ETF]      # 선택 — 걸리면 이 섹터 귀속 취소
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Tuple

import yaml

DEFAULT_PATH = Path(__file__).parent / "data" / "sector_keywords.yaml"
_KEY_RE = re.compile(r"^\d{3}$")

ROUTE_KW_TITLE = "kw_title"
ROUTE_KW_BODY = "kw_body"


class SectorKeywordError(ValueError):
    """사전 파일이 계약을 어겼다 — 집계 잡 중단 사유(기동은 계속)."""


@dataclass(frozen=True)
class SectorEntry:
    key: str
    name: str
    ko: Tuple[str, ...]
    en: Tuple[str, ...]
    exclude: Tuple[str, ...]
    en_patterns: Tuple[Pattern, ...]  # en 과 같은 순서


@dataclass(frozen=True)
class SectorKeywordDict:
    version: str
    sectors: Dict[str, SectorEntry]


@dataclass(frozen=True)
class KeywordHit:
    route: str    # ROUTE_KW_TITLE | ROUTE_KW_BODY
    matched: str  # 걸린 키워드 원문


def _en_pattern(kw: str) -> Pattern:
    # 영어는 단어경계: 'chip' 이 'chipotle' 에 걸리지 않는다. 한국어엔 \b 가 없어 ko 는 부분문자열.
    return re.compile(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])")


def _as_str_list(raw, field: str, key: str) -> List[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(x, str) or not x.strip() for x in raw):
        raise SectorKeywordError(f"[{key}] {field} 는 비어 있지 않은 문자열 리스트여야 한다: {raw!r}")
    return [x.strip() for x in raw]


def parse_sector_keywords(data) -> SectorKeywordDict:
    """YAML 로 읽은 객체를 검증하고 SectorKeywordDict 로 만든다."""
    if not isinstance(data, dict):
        raise SectorKeywordError("최상위는 매핑이어야 한다")
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise SectorKeywordError("version 은 비어 있지 않은 문자열이어야 한다")
    raw_sectors = data.get("sectors")
    if not isinstance(raw_sectors, dict) or not raw_sectors:
        raise SectorKeywordError("sectors 는 비어 있지 않은 매핑이어야 한다")

    sectors: Dict[str, SectorEntry] = {}
    for raw_key, raw_entry in raw_sectors.items():
        key = str(raw_key)
        if not _KEY_RE.match(key):
            raise SectorKeywordError(f"섹터 키는 3자리 숫자 문자열이어야 한다: {raw_key!r}")
        if not isinstance(raw_entry, dict):
            raise SectorKeywordError(f"[{key}] 항목은 매핑이어야 한다")
        name = raw_entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SectorKeywordError(f"[{key}] name 은 필수다")
        ko = _as_str_list(raw_entry.get("ko"), "ko", key)
        en = _as_str_list(raw_entry.get("en"), "en", key)
        exclude = _as_str_list(raw_entry.get("exclude"), "exclude", key)
        if not ko and not en:
            raise SectorKeywordError(f"[{key}] ko 또는 en 중 하나는 비어 있지 않아야 한다")
        seen = set()
        for kw in ko + en + exclude:
            low = kw.lower()
            if low in seen:
                raise SectorKeywordError(f"[{key}] 중복 키워드: {kw!r}")
            seen.add(low)
        sectors[key] = SectorEntry(
            key=key, name=name.strip(), ko=tuple(ko), en=tuple(en), exclude=tuple(exclude),
            en_patterns=tuple(_en_pattern(k) for k in en),
        )
    return SectorKeywordDict(version=version.strip(), sectors=sectors)


def load_sector_keywords(path: Optional[Path] = None) -> SectorKeywordDict:
    p = Path(path) if path is not None else DEFAULT_PATH
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return parse_sector_keywords(data)
```

- [ ] **Step 4: 통과 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_keywords.py -v
```

Expected: `10 passed`.

- [ ] **Step 5: 커밋**

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
feat(sector): 섹터 키워드 사전 로더·검증 — 3자리 키·name 필수·ko/en 택일·섹터 내 중복 금지 (스펙 B §4.2)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/tmp/nq-wt-sector-news && git add news_scraper/sector_keywords.py tests/test_sector_keywords.py && git commit -F D:/tmp/nq_commit_msg.txt
```

---

### Task 2: 키워드 매칭 `match_sectors`

**Files:**
- Modify: `news_scraper/sector_keywords.py` (끝에 함수 4개 추가)
- Test: `tests/test_sector_keywords.py` (테스트 추가)

**Interfaces:**
- Produces: `match_sectors(title: Optional[str], content: Optional[str], kwdict: SectorKeywordDict, body_chars: int = 2000) -> Dict[str, KeywordHit]` — 섹터키 → `KeywordHit(route, matched)`. 제목 히트가 본문 히트보다 우선(한 섹터에 하나). `exclude` 가 제목·본문 어디든 걸리면 그 섹터는 결과에서 빠진다.

- [ ] **Step 1: 실패하는 테스트 추가** (`tests/test_sector_keywords.py` 끝에)

```python
from news_scraper.sector_keywords import match_sectors, ROUTE_KW_TITLE, ROUTE_KW_BODY


def _kw():
    return parse_sector_keywords({
        "version": "t",
        "sectors": {
            "261": {"name": "반도체", "ko": ["반도체", "HBM"], "en": ["chip", "semiconductor"], "exclude": ["반도체 ETF"]},
            "641": {"name": "은행", "ko": ["은행"], "en": ["bank"]},
            "212": {"name": "의약품", "ko": ["임상"]},
            "701": {"name": "연구개발", "ko": ["임상"]},
        },
    })


def test_ko_substring_in_title():
    hits = match_sectors("삼성전자 반도체 수출 급증", "", _kw())
    assert hits["261"] == KeywordHit(ROUTE_KW_TITLE, "반도체")
    assert "641" not in hits


def test_body_only_hit_is_kw_body():
    hits = match_sectors("실적 발표", "이번 분기 HBM 매출이 두 배", _kw())
    assert hits["261"].route == ROUTE_KW_BODY and hits["261"].matched == "HBM"


def test_title_beats_body():
    hits = match_sectors("반도체 호황", "HBM 이야기", _kw())
    assert hits["261"].route == ROUTE_KW_TITLE


def test_en_word_boundary():
    assert "261" not in match_sectors("Chipotle earnings beat", "", _kw())
    assert match_sectors("Nvidia chip demand soars", "", _kw())["261"].matched == "chip"
    assert match_sectors("CHIPS Act update", "", _kw()).get("261") is None  # 'chips' ≠ 'chip' (경계)


def test_case_insensitive():
    assert "641" in match_sectors("BANK of Korea holds rates", "", _kw())
    assert "261" in match_sectors("hbm 공급 확대", "", _kw())


def test_exclude_cancels_sector():
    assert "261" not in match_sectors("반도체 ETF 순자산 급증", "", _kw())
    assert "261" not in match_sectors("반도체 뉴스", "이 상품은 반도체 ETF 입니다", _kw())


def test_body_truncated_to_body_chars():
    body = ("x" * 2000) + " HBM"
    assert "261" not in match_sectors("제목", body, _kw(), body_chars=2000)
    assert "261" in match_sectors("제목", body, _kw(), body_chars=2100)


def test_multi_sector_attribution():
    hits = match_sectors("신약 임상 3상 성공", "", _kw())
    assert set(hits) == {"212", "701"}


def test_none_inputs_are_safe():
    assert match_sectors(None, None, _kw()) == {}
```

`from news_scraper.sector_keywords import KeywordHit` 를 파일 상단 import 에 추가한다.

- [ ] **Step 2: 실패 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_keywords.py -v -k "match or boundary or exclude or truncated or multi or none or beats or case"
```

Expected: `ImportError: cannot import name 'match_sectors'`.

- [ ] **Step 3: 구현** (`news_scraper/sector_keywords.py` 끝에 추가)

```python
def _find_ko(text: str, kws: Tuple[str, ...]) -> Optional[str]:
    for kw in kws:
        if kw.lower() in text:
            return kw
    return None


def _find_en(text: str, entry: SectorEntry) -> Optional[str]:
    for kw, pat in zip(entry.en, entry.en_patterns):
        if pat.search(text):
            return kw
    return None


def _excluded(entry: SectorEntry, title: str, body: str) -> bool:
    for x in entry.exclude:
        low = x.lower()
        if low in title or low in body:
            return True
    return False


def match_sectors(title: Optional[str], content: Optional[str], kwdict: SectorKeywordDict,
                  body_chars: int = 2000) -> Dict[str, KeywordHit]:
    """제목·본문(앞 body_chars 자)을 사전에 대고 섹터별 히트를 돌려준다.

    - ko: 부분문자열(소문자화) · en: 단어경계(소문자화)
    - 제목 히트(ROUTE_KW_TITLE) > 본문 히트(ROUTE_KW_BODY) — 섹터당 하나
    - exclude 가 제목·본문 어디든 걸리면 그 섹터 귀속 취소
    - 한 뉴스가 여러 섹터에 걸리면 전부 돌려준다
    """
    t = (title or "").lower()
    b = (content or "")[:body_chars].lower()
    hits: Dict[str, KeywordHit] = {}
    for key, entry in kwdict.sectors.items():
        if _excluded(entry, t, b):
            continue
        kw = _find_ko(t, entry.ko) or _find_en(t, entry)
        if kw is not None:
            hits[key] = KeywordHit(ROUTE_KW_TITLE, kw)
            continue
        kw = _find_ko(b, entry.ko) or _find_en(b, entry)
        if kw is not None:
            hits[key] = KeywordHit(ROUTE_KW_BODY, kw)
    return hits
```

- [ ] **Step 4: 통과 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_keywords.py -v
```

Expected: `19 passed`.

- [ ] **Step 5: 커밋**

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
feat(sector): match_sectors — ko 부분문자열·en 단어경계·exclude·제목>본문·다중 섹터 귀속 (스펙 B §4.2)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/tmp/nq-wt-sector-news && git add news_scraper/sector_keywords.py tests/test_sector_keywords.py && git commit -F D:/tmp/nq_commit_msg.txt
```

---

### Task 3: 실제 사전 파일 (49섹터)

**Files:**
- Create: `news_scraper/data/sector_keywords.yaml`
- Create: `news_scraper/data/__init__.py` (빈 파일 — 패키지 데이터 경로 안정화)
- Test: `tests/test_sector_keywords.py` (테스트 2개 추가)

**Interfaces:**
- Produces: `load_sector_keywords()` 기본 경로가 이 파일을 읽는다. `version = "2026-09-06.1"`, 49 키.

- [ ] **Step 1: 실패하는 테스트 추가**

```python
from news_scraper.sector_keywords import DEFAULT_PATH


def test_shipped_dictionary_loads_and_has_49_sectors():
    d = load_sector_keywords()
    assert DEFAULT_PATH.exists()
    assert d.version == "2026-09-06.1"
    assert len(d.sectors) == 49
    for key in ("261", "212", "641", "311", "282", "582"):
        assert key in d.sectors


def test_shipped_dictionary_smoke_matches():
    d = load_sector_keywords()
    assert "261" in match_sectors("SK하이닉스 HBM 증설", "", d)
    assert match_sectors("SK하이닉스 HBM3E 양산 본격화", "", d)["261"].matched == "HBM"
    assert "612" not in match_sectors("KT&G 담배 판매 호조", "", d)          # exclude
    assert "311" in match_sectors("HD현대중공업 LNG선 3척 수주", "", d)
    assert "641" in match_sectors("Bank of Korea signals rate cut path", "", d)
    assert "641" not in match_sectors("Minimum wage debate continues", "", d)     # 'nim' 부분문자열 오탐 방지
    assert "412" in match_sectors("정부 SOC 예산 20% 증액", "", d)                   # 한글 앞뒤도 단어경계
```

- [ ] **Step 2: 실패 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_keywords.py -v -k shipped
```

Expected: `FileNotFoundError` (사전 파일 없음).

- [ ] **Step 3: 사전 파일 작성** — `news_scraper/data/sector_keywords.yaml` (키는 전부 따옴표. 이름은 2026-09-04 캐시 CSV `Industry` 열 기준. 코드는 `ksic_code_name` 이 채워진 뒤 §7 의 WARNING 으로 재확인)

(2026-09-07 구현 중 정정: 섹터 내 중복 금지 규칙과 라틴 약어 배치 룰링에 따라 아래 블록은 실제 배포 파일과 동일하게 동기화됨 — 라틴 약어는 en(단어경계), HBM 만 ko(숫자 접미 대응).)

```yaml
# 섹터 키워드 사전 (스펙 B §4.2) — KSIC 3자리 → 한/영 키워드
# 규칙: 키는 따옴표 3자리 · ko 는 부분문자열 · en 은 단어경계 · exclude 걸리면 귀속 취소
# 변경은 커밋으로만. version 을 올려라 (sector_news_score.dict_version 에 기록된다).
version: "2026-09-06.1"
sectors:
  # ── 전자·반도체 ──────────────────────────────────────────
  "261":
    name: 반도체 제조업
    ko: [반도체, 메모리 반도체, D램, 디램, 낸드, HBM, 파운드리, 웨이퍼, 시스템반도체]
    en: [semiconductor, semiconductors, chip, chipmaker, chipmakers, DRAM, NAND, foundry, wafer]
    exclude: [반도체 ETF]
  "262":
    name: 전자부품 제조업
    ko: [전자부품, 기판, 디스플레이, 카메라모듈, 적층세라믹]
    en: [display, OLED, PCB, electronic components, MLCC, LCD]
  "263":
    name: 컴퓨터 및 주변장치 제조업
    ko: [서버, 데이터센터, 스토리지, 노트북]
    en: [server, servers, data center, datacenter, SSD, storage device]
  "264":
    name: 통신 및 방송 장비 제조업
    ko: [통신장비, 5G 장비, 네트워크 장비, 스마트폰, 갤럭시, 아이폰, 위성통신, 무선통신 장비]
    en: [smartphone, smartphones, iPhone, Galaxy, telecom equipment, network equipment]
  "265":
    name: 영상 및 음향기기 제조업
    ko: [OLED TV, TV 시장, TV 판매, 음향기기, 스피커, 이어폰, 프로젝터]
    en: [television, TV maker, audio equipment]
  "292":
    name: 특수 목적용 기계 제조업
    ko: [반도체 장비, 반도체장비, 디스플레이 장비, 노광, 식각, 증착, 전공정, 후공정, 공작기계, 로봇]
    en: [chip equipment, semiconductor equipment, lithography, etching, robotics]
  "291":
    name: 일반 목적용 기계 제조업
    ko: [기계, 건설기계, 굴착기, 펌프, 밸브, 공조기, 냉동공조, 터빈]
    en: [machinery, construction equipment, excavator, turbine]
  # ── 바이오·의료 ──────────────────────────────────────────
  "211":
    name: 기초 의약물질 제조업
    ko: [바이오시밀러, 원료의약품, 항체, 백신, 세포치료제, 유전자치료제, 바이오의약품]
    en: [biosimilar, vaccine, antibody, cell therapy, gene therapy, biologics]
  "212":
    name: 의약품 제조업
    ko: [제약, 신약, 임상, 임상시험, 품목허가, FDA 승인, 복제약, 제네릭, 의약품]
    en: [pharma, pharmaceutical, drug approval, clinical trial, FDA approval, generic drug]
  "213":
    name: 의료용품 및 기타 의약 관련제품 제조업
    ko: [의료용품, 콘택트렌즈, 주사기, 진단키트, 체외진단, 진단시약]
    en: [diagnostic kit, contact lens, in vitro diagnostic]
  "271":
    name: 의료용 기기 제조업
    ko: [의료기기, 임플란트, 미용 의료기기, 피부미용기기, 초음파 진단, 인공관절, 레이저 의료]
    en: [medical device, medical devices, implant, aesthetic device]
  "701":
    name: 자연과학 및 공학 연구개발업
    ko: [바이오벤처, 신약개발, 기술이전, 라이선스 아웃, 라이선스아웃, 임상 1상, 임상 2상, 임상 3상, 임상]
    en: [biotech, licensing deal, out-licensing, phase 3, phase 2]
  # ── 자동차·운송장비·방산 ─────────────────────────────────
  "301":
    name: 자동차용 엔진 및 자동차 제조업
    ko: [완성차, 현대차, 기아, 전기차, 자동차 판매, 자동차 수출, 하이브리드차]
    en: [automaker, automakers, electric vehicle, EV sales, Hyundai Motor, Kia]
  "303":
    name: 자동차 신품 부품 제조업
    ko: [자동차 부품, 차부품, 부품사, 모비스, 전장, 자율주행 부품]
    en: [auto parts, auto supplier, auto suppliers]
  "311":
    name: 선박 및 보트 건조업
    ko: [조선, 조선사, 선박 수주, LNG선, 컨테이너선, 조선업, 도크, 상선]
    en: [shipbuilder, shipbuilders, shipbuilding, LNG carrier, vessel order]
  "313":
    name: 항공기,우주선 및 부품 제조업
    ko: [항공기, 항공우주, 우주발사체, 위성, 항공 부품, KF-21, 우주항공]
    en: [aerospace, aircraft, satellite launch]
  "252":
    name: 무기 및 총포탄 제조업
    ko: [방산, 방위산업, 무기, 미사일, 자주포, 전차, 천무, 탄약, 국방예산]
    en: [defense contractor, defense exports, missile, munitions, arms deal, K9]
  # ── 소재·에너지 ──────────────────────────────────────────
  "241":
    name: 1차 철강 제조업
    ko: [철강, 포스코, 현대제철, 열연, 냉연, 후판, 철근, 철강 가격]
    en: [steel, steelmaker, steelmakers]
  "242":
    name: 1차 비철금속 제조업
    ko: [비철금속, 구리, 동가격, 알루미늄, 아연, 니켈, 금값, 금 가격]
    en: [copper, aluminum, aluminium, nickel, zinc, gold price]
  "282":
    name: 일차전지 및 이차전지 제조업
    ko: [2차전지, 이차전지, 배터리, 양극재, 음극재, 전해질, 분리막, 전고체]
    en: [battery, batteries, cathode, anode, electrolyte, separator, ESS, solid-state]
  "281":
    name: 전동기, 발전기 및 전기 변환 · 공급 · 제어 장치 제조업
    ko: [변압기, 전력기기, 전력설비, 송전, 배전, 초고압, 발전기]
    en: [transformer, transformers, power equipment, grid equipment, switchgear]
  "283":
    name: 절연선 및 케이블 제조업
    ko: [전선, 케이블, 해저케이블, 광케이블]
    en: [cable, cables, subsea cable]
  "201":
    name: 기초 화학물질 제조업
    ko: [석유화학, 에틸렌, 나프타, NCC, 폴리에틸렌, PVC, 화학 업황, 화학주]
    en: [petrochemical, petrochemicals, ethylene, naphtha]
  "204":
    name: 기타 화학제품 제조업
    ko: [화장품, 뷰티, K뷰티, 코스메틱, 페인트, 도료, 접착제]
    en: [cosmetics, beauty, K-beauty]
  "192":
    name: 석유 정제품 제조업
    ko: [정유, 정제마진, 휘발유, 경유 가격, 유가]
    en: [refiner, refiners, refining margin, crude oil, oil price, oil prices]
  "351":
    name: 전기업
    ko: [한전, 한국전력, 전기요금, 전력요금, 발전소, 원전, 원자력, 발전 사업]
    en: [nuclear power, power plant, utility, utilities]
  "352":
    name: 연료용 가스 제조 및 배관공급업
    ko: [도시가스, 가스공사, LNG 가격, 가스요금, 천연가스]
    en: [natural gas, LNG price, LNG prices]
  # ── IT·미디어·통신 ───────────────────────────────────────
  "582":
    name: 소프트웨어 개발 및 공급업
    ko: [게임, 게임사, 신작, 소프트웨어]
    en: [game, games, video game, software, SaaS]
  "620":
    name: 컴퓨터 프로그래밍, 시스템 통합 및 관리업
    ko: [시스템통합, SI 업체, IT서비스, 클라우드 전환, 디지털 전환]
    en: [IT services, system integrator, cloud migration]
  "631":
    name: 자료처리, 호스팅, 포털 및 기타 인터넷 정보매개 서비스업
    ko: [네이버, 카카오, 포털, 플랫폼, 검색광고, 클라우드 서비스, 데이터센터]
    en: [platform, portal, cloud service, cloud services, hosting]
  "612":
    name: 전기 통신업
    ko: [통신사, 케이티, SK텔레콤, LG유플러스, 통신 3사, 이통사, 통신요금, 알뜰폰]
    en: [telecom, telecoms, carrier, carriers, 5G, SKT]
    exclude: [KT&G, KTX]
  "602":
    name: 텔레비전 방송업
    ko: [방송사, 지상파, 종편, 홈쇼핑, 케이블TV]
    en: [broadcaster, broadcasters]
  "591":
    name: 영화, 비디오물, 방송프로그램 제작 및 배급업
    ko: [드라마, 영화, 콘텐츠 제작, 제작사, 엔터, 엔터테인먼트, 넷플릭스, 박스오피스]
    en: [drama, film, content, OTT, Netflix, box office]
  "592":
    name: 오디오물 출판 및 원판 녹음업
    ko: [음반, 음원, K팝, 케이팝, 아이돌, 콘서트, 하이브, JYP, SM엔터, YG엔터]
    en: [K-pop, kpop, album, concert, concerts]
  "713":
    name: 광고업
    ko: [광고 시장, 광고대행, 광고업, 디지털 광고]
    en: [advertising, ad spending, ad market]
  # ── 금융 ─────────────────────────────────────────────────
  "641":
    name: 은행 및 저축기관
    ko: [은행, 은행주, 금융지주, 예대마진, 순이자마진, 대출 금리, 가계대출, 기준금리]
    en: [bank, banks, lender, lenders, net interest margin, rate cut, rate hike, NIM]
  "651":
    name: 보험업
    ko: [보험, 보험사, 생보, 손보, 보험료, IFRS17, 킥스, K-ICS]
    en: [insurer, insurers, insurance]
  "649":
    name: 기타 금융업
    ko: [카드사, 캐피탈, 여신전문, 할부금융, 저축은행, 대부업]
    en: [credit card, consumer finance, card issuer]
  "661":
    name: 금융 지원 서비스업
    ko: [증권사, 증권주, 브로커리지, 거래대금, IB 수수료, 토큰증권, 거래소]
    en: [brokerage, brokerages, securities firm, exchange operator]
  "664":
    name: 신탁업 및 집합투자업
    ko: [자산운용, 운용사, ETF 시장, 신탁, 펀드 시장, 사모펀드]
    en: [asset manager, asset managers, asset management, fund inflows]
  # ── 건설·부동산 ──────────────────────────────────────────
  "411":
    name: 건물 건설업
    ko: [건설사, 건설주, 주택, 분양, 재건축, 재개발, 아파트 분양, 미분양, 도시정비]
    en: [homebuilder, homebuilders, construction, housing]
  "412":
    name: 토목 건설업
    ko: [토목, 인프라 투자, 플랜트, 해외 건설, 항만 공사, 도로 공사, 철도 공사]
    en: [infrastructure, plant construction, SOC]
  "681":
    name: 부동산 임대 및 공급업
    ko: [부동산, 리츠, 임대, 오피스 공실, 부동산 PF, 상업용 부동산]
    en: [real estate, REIT, REITs, property]
  # ── 소비·유통·운송 ───────────────────────────────────────
  "107":
    name: 기타 식품 제조업
    ko: [식품, 식품주, 라면, 과자, 가공식품, K푸드, 즉석식품, 식료품]
    en: [food maker, packaged food, K-food]
  "111":
    name: 알코올음료 제조업
    ko: [소주, 맥주, 위스키, 주류, 하이볼]
    en: [liquor, beer, soju, spirits]
  "471":
    name: 종합 소매업
    ko: [백화점, 대형마트, 이마트, 롯데쇼핑, 유통주, 유통업, 편의점, 소매판매]
    en: [retailer, retailers, department store, retail sales]
  "501":
    name: 해상 운송업
    ko: [해운, 해운사, 컨테이너 운임, SCFI, 벌크선 운임, BDI]
    en: [shipping, container rates, freight rates, HMM]
  "511":
    name: 항공 여객 운송업
    ko: [항공사, 항공주, 여객 수요, 국제선, 항공권, 대한항공, 아시아나, 저비용항공]
    en: [airline, airlines, passenger demand, air travel, LCC]
  "752":
    name: 여행사 및 기타 여행보조 서비스업
    ko: [여행사, 해외여행, 패키지여행, 여행 수요, 하나투어, 모두투어]
    en: [travel agency, tourism, outbound travel]
```

`news_scraper/data/__init__.py` 는 빈 파일로 만든다.

- [ ] **Step 4: 통과 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_keywords.py -v
```

Expected: `21 passed`. (49 개가 아니면 `python -c "from news_scraper.sector_keywords import load_sector_keywords as l; print(len(l().sectors))"` 로 센다.)

- [ ] **Step 5: 커밋**

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
feat(sector): 섹터 키워드 사전 v2026-09-06.1 — KSIC3 49섹터 한/영 (스펙 B §4.2 초기 대상)

나머지 109섹터는 경로 B(종목매핑)로만. 사전 변경은 커밋 + version 증가.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/tmp/nq-wt-sector-news && git add news_scraper/data/__init__.py news_scraper/data/sector_keywords.yaml tests/test_sector_keywords.py && git commit -F D:/tmp/nq_commit_msg.txt
```

---

### Task 4: 창·거래일·동결 계산

**Files:**
- Create: `news_scraper/sector_news_aggregator.py` (상수 + 시간 함수)
- Test: `tests/test_sector_news_aggregator.py`

**Interfaces:**
- Produces:
  - 모듈 상수 `MIN_N K_SCALE W_KW_TITLE W_KW_BODY W_STOCK MAX_CODES_PER_NEWS BODY_CHARS DIR_EPS TOP_NEWS DEFAULT_W_SRC MARKET_CLOSE=time(15,30) FREEZE_FROM=time(9,5) ROUTE_STOCK="stock"`
  - `next_weekday(d: date) -> date` · `prev_weekday(d: date) -> date`
  - `compute_trade_date(now: datetime) -> date`
  - `compute_window(now: datetime) -> Tuple[date, datetime, datetime]` — `(trade_date, window_start, window_end=now)`
  - `is_frozen(now: datetime) -> bool` — 평일 09:05 ≤ t < 15:30
  - `split_related_stocks(raw) -> List[str]` — 6자리 코드, 순서 유지·중복 제거
- `now` 는 **naive KST** (`datetime`, tzinfo 없음)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_sector_news_aggregator.py`:

```python
from datetime import date, datetime, time

from news_scraper.sector_news_aggregator import (
    compute_trade_date, compute_window, is_frozen, next_weekday, prev_weekday,
    split_related_stocks, MARKET_CLOSE, FREEZE_FROM,
)


def test_constants():
    assert MARKET_CLOSE == time(15, 30) and FREEZE_FROM == time(9, 5)


def test_weekday_helpers():
    assert next_weekday(date(2026, 9, 4)) == date(2026, 9, 7)   # 금 → 월
    assert next_weekday(date(2026, 9, 5)) == date(2026, 9, 7)   # 토 → 월
    assert prev_weekday(date(2026, 9, 7)) == date(2026, 9, 4)   # 월 → 금
    assert prev_weekday(date(2026, 9, 8)) == date(2026, 9, 7)   # 화 → 월


def test_trade_date_weekday_before_close_is_today():
    assert compute_trade_date(datetime(2026, 9, 8, 9, 0)) == date(2026, 9, 8)
    assert compute_trade_date(datetime(2026, 9, 8, 15, 29, 59)) == date(2026, 9, 8)


def test_trade_date_after_close_is_next_weekday():
    assert compute_trade_date(datetime(2026, 9, 8, 15, 30)) == date(2026, 9, 9)
    assert compute_trade_date(datetime(2026, 9, 4, 16, 0)) == date(2026, 9, 7)    # 금 저녁 → 월


def test_trade_date_weekend_is_next_monday():
    assert compute_trade_date(datetime(2026, 9, 5, 12, 0)) == date(2026, 9, 7)
    assert compute_trade_date(datetime(2026, 9, 6, 3, 0)) == date(2026, 9, 7)


def test_window_monday_morning_starts_friday_close():
    td, ws, we = compute_window(datetime(2026, 9, 7, 8, 50))
    assert td == date(2026, 9, 7)
    assert ws == datetime(2026, 9, 4, 15, 30) and we == datetime(2026, 9, 7, 8, 50)


def test_window_friday_evening_targets_monday_from_friday_close():
    td, ws, we = compute_window(datetime(2026, 9, 4, 20, 0))
    assert td == date(2026, 9, 7) and ws == datetime(2026, 9, 4, 15, 30)


def test_window_tuesday_starts_monday_close():
    td, ws, _ = compute_window(datetime(2026, 9, 8, 7, 45))
    assert td == date(2026, 9, 8) and ws == datetime(2026, 9, 7, 15, 30)


def test_frozen_window():
    assert not is_frozen(datetime(2026, 9, 8, 9, 4, 59))
    assert is_frozen(datetime(2026, 9, 8, 9, 5))
    assert is_frozen(datetime(2026, 9, 8, 12, 0))
    assert not is_frozen(datetime(2026, 9, 8, 15, 30))
    assert not is_frozen(datetime(2026, 9, 5, 12, 0))   # 주말은 동결 없음


def test_split_related_stocks():
    assert split_related_stocks("005930,000660, 005930 ,12345,ABCDEFG") == ["005930", "000660"]
    assert split_related_stocks("") == [] and split_related_stocks(None) == []
```

- [ ] **Step 2: 실패 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_aggregator.py -v
```

Expected: `ModuleNotFoundError: news_scraper.sector_news_aggregator`.

- [ ] **Step 3: 구현** — `news_scraper/sector_news_aggregator.py`

```python
"""섹터 뉴스 집계 — 창 계산 · 뉴스→섹터 귀속(경로 A+B) · 기여도 · 집계 (스펙 B §4). DB·로거를 모른다."""
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple

from .sector_keywords import SectorKeywordDict, match_sectors, ROUTE_KW_TITLE, ROUTE_KW_BODY
from .sentiment_analyzer import SentimentAnalyzer
from .english_sentiment_analyzer import EnglishSentimentAnalyzer

# ── 스펙 §4.4 상수 (config.yaml 로 빼지 않는다 — 관례) ──────────────────────
MIN_N = 3                 # 방향 있는 뉴스가 이보다 적으면 score_signed = 0
K_SCALE = 2.0             # score_signed = clip(score_norm / K_SCALE)
W_KW_TITLE = 1.0
W_KW_BODY = 0.5
W_STOCK = 0.7             # related_stocks 노이즈 → 낮춤
MAX_CODES_PER_NEWS = 5    # 초과 = 인사·시황 나열 기사 → 경로 B 건너뜀(건수 보고)
BODY_CHARS = 2000
DIR_EPS = 0.1             # |sentiment| >= 0.1 이면 「방향 있는」 뉴스
TOP_NEWS = 5
DEFAULT_W_SRC = 0.9
MARKET_CLOSE = time(15, 30)
FREEZE_FROM = time(9, 5)  # 평일 09:05~15:30 은 오늘 거래일 점수 동결(봇이 09:00 에 읽은 값 보존)
ROUTE_STOCK = "stock"
_ROUTE_WEIGHT = {ROUTE_KW_TITLE: W_KW_TITLE, ROUTE_KW_BODY: W_KW_BODY, ROUTE_STOCK: W_STOCK}

# 한/영 분석기의 출처 신뢰도를 합친다(한글 쪽이 우선). 없는 출처는 DEFAULT_W_SRC.
SOURCE_CREDIBILITY: Dict[str, float] = {
    **EnglishSentimentAnalyzer.SOURCE_CREDIBILITY,
    **SentimentAnalyzer.SOURCE_CREDIBILITY,
}


# ── 시간 ───────────────────────────────────────────────────────────────────
def next_weekday(d: date) -> date:
    d = d + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def prev_weekday(d: date) -> date:
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def compute_trade_date(now: datetime) -> date:
    """평일 ∧ now < 15:30 → 오늘, 아니면 다음 평일. 공휴일 달력 없음(무시)."""
    if now.weekday() < 5 and now.time() < MARKET_CLOSE:
        return now.date()
    return next_weekday(now.date())


def compute_window(now: datetime) -> Tuple[date, datetime, datetime]:
    """(trade_date, window_start=직전 평일 15:30, window_end=now). D-1 장중 뉴스는 D-1 종가에 반영됐다고 보고 뺀다."""
    trade_date = compute_trade_date(now)
    start = datetime.combine(prev_weekday(trade_date), MARKET_CLOSE)
    return trade_date, start, now


def is_frozen(now: datetime) -> bool:
    """평일 09:05 ≤ t < 15:30 — 쓰지 않는다. UPSERT 가 덮어쓰므로 봇이 09:00 에 읽은 행을 보존해야 §8-① 평가가 된다."""
    return now.weekday() < 5 and FREEZE_FROM <= now.time() < MARKET_CLOSE


def split_related_stocks(raw) -> List[str]:
    """'005930,000660' → ['005930','000660']. 6자리만, 순서 유지, 중복 제거."""
    if not raw:
        return []
    out: List[str] = []
    for part in str(raw).split(","):
        c = part.strip()
        if len(c) == 6 and c not in out:
            out.append(c)
    return out
```

- [ ] **Step 4: 통과 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_aggregator.py -v
```

Expected: `10 passed`.

- [ ] **Step 5: 커밋**

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
feat(sector): 집계 창·거래일·동결(09:05~15:30)·related_stocks 분리 + 스펙 §4.4 상수 (스펙 B §4.1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/tmp/nq-wt-sector-news && git add news_scraper/sector_news_aggregator.py tests/test_sector_news_aggregator.py && git commit -F D:/tmp/nq_commit_msg.txt
```

---

### Task 5: 귀속·기여도·집계 `attribute_news` · `aggregate`

**Files:**
- Modify: `news_scraper/sector_news_aggregator.py` (끝에 추가)
- Test: `tests/test_sector_news_aggregator.py` (테스트 추가)

**Interfaces:**
- Produces:
  - `@dataclass SectorHit(route: str, routes: List[str], matched: str, w_match: float)`
  - `attribute_news(news: Dict, kwdict, code_to_sector: Dict[str,str], *, stock_route_enabled: bool, summary: Dict) -> Dict[str, SectorHit]`
  - `@dataclass AggregationResult(trade_date: date, window_start: datetime, window_end: datetime, scores: List[Dict], hits: List[Dict], summary: Dict)`
  - `aggregate(news_rows: List[Dict], kwdict, code_to_sector: Dict[str,str], sector_names: Dict[str,str], now: datetime, *, stock_route_enabled: bool = True) -> AggregationResult`
  - `scores[i]` 키: `trade_date sector_key sector_name window_start window_end n_news n_dir n_kw n_stock n_pos n_neg score_raw score_norm score_signed top_news` (**`dict_version` 은 Task 7 의 잡이 채운다**)
  - `hits[i]` 키: `trade_date news_id sector_key route routes matched w_match contribution`
- 뉴스 dict 는 `database.get_news_in_window` 가 주는 모양: `news_id title content source sentiment_score related_stocks`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
import math
from news_scraper.sector_keywords import parse_sector_keywords
from news_scraper.sector_news_aggregator import (
    attribute_news, aggregate, SectorHit, ROUTE_STOCK, W_KW_TITLE, W_KW_BODY, W_STOCK,
    MIN_N, K_SCALE, DEFAULT_W_SRC, MAX_CODES_PER_NEWS,
)
from news_scraper.sector_keywords import ROUTE_KW_TITLE, ROUTE_KW_BODY


def _kw():
    return parse_sector_keywords({"version": "t", "sectors": {
        "261": {"name": "반도체", "ko": ["반도체"], "en": ["chip"]},
        "641": {"name": "은행", "ko": ["은행"]},
    }})


def _news(**kw):
    base = {"news_id": "n1", "title": "", "content": "", "source": "naver_finance",
            "sentiment_score": 0.5, "related_stocks": ""}
    base.update(kw)
    return base


NOW = datetime(2026, 9, 8, 8, 50)
MAP = {"005930": "261", "000660": "261", "105560": "641"}


def test_attribute_title_kw():
    s = {}
    hits = attribute_news(_news(title="반도체 호황"), _kw(), MAP, stock_route_enabled=True, summary=s)
    assert hits["261"] == SectorHit(ROUTE_KW_TITLE, [ROUTE_KW_TITLE], "반도체", W_KW_TITLE)


def test_attribute_stock_route_only():
    hits = attribute_news(_news(title="실적", related_stocks="105560"), _kw(), MAP, stock_route_enabled=True, summary={})
    assert hits == {"641": SectorHit(ROUTE_STOCK, [ROUTE_STOCK], "105560", W_STOCK)}


def test_attribute_both_routes_take_max_weight_once():
    h = attribute_news(_news(title="반도체", related_stocks="005930"), _kw(), MAP, stock_route_enabled=True, summary={})["261"]
    assert h.w_match == W_KW_TITLE and h.route == ROUTE_KW_TITLE and h.routes == [ROUTE_KW_TITLE, ROUTE_STOCK]
    h2 = attribute_news(_news(content="반도체", related_stocks="005930"), _kw(), MAP, stock_route_enabled=True, summary={})["261"]
    assert h2.w_match == W_STOCK and h2.route == ROUTE_STOCK and h2.routes == [ROUTE_KW_BODY, ROUTE_STOCK]


def test_attribute_stock_route_disabled():
    hits = attribute_news(_news(related_stocks="105560"), _kw(), MAP, stock_route_enabled=False, summary={})
    assert hits == {}


def test_attribute_too_many_codes_skips_stock_route_and_counts():
    s = {}
    many = ",".join(["005930", "000660", "105560", "111111", "222222", "333333"])
    hits = attribute_news(_news(title="[인사] 국토교통부", related_stocks=many), _kw(), MAP, stock_route_enabled=True, summary=s)
    assert hits == {} and s["stock_route_skipped"] == 1


def test_aggregate_formula_and_min_n():
    rows = [
        _news(news_id="a", title="반도체 훈풍", sentiment_score=0.5),           # c = 0.5*1.0*0.9 = 0.45
        _news(news_id="b", content="chip demand", sentiment_score=0.8),        # c = 0.8*0.5*0.9 = 0.36
        _news(news_id="c", related_stocks="000660", sentiment_score=-0.2),     # c = -0.2*0.7*0.9 = -0.126
        _news(news_id="d", related_stocks="005930", sentiment_score=0.0),      # 중립: n_news 에만
        _news(news_id="e", title="은행 실적", sentiment_score=1.0),             # 641: n_dir 1 < MIN_N → 0
    ]
    r = aggregate(rows, _kw(), MAP, {"641": "은행 및 저축기관"}, NOW)
    by = {s["sector_key"]: s for s in r.scores}
    s261 = by["261"]
    assert (s261["n_news"], s261["n_dir"], s261["n_kw"], s261["n_stock"], s261["n_pos"], s261["n_neg"]) == (4, 3, 2, 2, 2, 1)
    raw = 0.45 + 0.36 - 0.126
    assert math.isclose(s261["score_raw"], raw, rel_tol=1e-9)
    assert math.isclose(s261["score_norm"], raw / math.sqrt(3), rel_tol=1e-9)
    assert math.isclose(s261["score_signed"], raw / math.sqrt(3) / K_SCALE, rel_tol=1e-9)
    assert by["641"]["n_dir"] == 1 and by["641"]["score_signed"] == 0.0
    assert by["641"]["sector_name"] == "은행"          # 사전 name 우선
    assert s261["trade_date"] == date(2026, 9, 8) and s261["window_start"] == datetime(2026, 9, 7, 15, 30)
    assert len(r.hits) == 5 and r.summary["n_input"] == 5


def test_aggregate_clips_to_plus_minus_one():
    rows = [_news(news_id=str(i), title="반도체", sentiment_score=1.0, source="krx_disclosure") for i in range(20)]
    r = aggregate(rows, _kw(), {}, {}, NOW)
    assert r.scores[0]["score_signed"] == 1.0
    rows = [_news(news_id=str(i), title="반도체", sentiment_score=-1.0) for i in range(20)]
    assert aggregate(rows, _kw(), {}, {}, NOW).scores[0]["score_signed"] == -1.0


def test_aggregate_unknown_source_uses_default_weight():
    rows = [_news(news_id=str(i), title="반도체", sentiment_score=0.5, source="unknown_src") for i in range(3)]
    s = aggregate(rows, _kw(), {}, {}, NOW).scores[0]
    assert math.isclose(s["score_raw"], 3 * 0.5 * DEFAULT_W_SRC)


def test_aggregate_top_news_sorted_by_abs_c_and_capped():
    rows = [_news(news_id=str(i), title="반도체", sentiment_score=(i - 3) / 3) for i in range(7)]
    top = aggregate(rows, _kw(), {}, {}, NOW).scores[0]["top_news"]
    assert len(top) == 5 and [abs(t["c"]) for t in top] == sorted([abs(t["c"]) for t in top], reverse=True)
    assert set(top[0]) == {"news_id", "title", "c", "route"}


def test_aggregate_name_falls_back_to_sector_names_then_none():
    rows = [_news(news_id="x", related_stocks="105560", sentiment_score=0.3)]
    kw = parse_sector_keywords({"version": "t", "sectors": {"261": {"name": "반도체", "ko": ["반도체"]}}})
    assert aggregate(rows, kw, MAP, {"641": "은행 및 저축기관"}, NOW).scores[0]["sector_name"] == "은행 및 저축기관"
    assert aggregate(rows, kw, MAP, {}, NOW).scores[0]["sector_name"] is None


def test_aggregate_none_sentiment_counts_as_neutral():
    rows = [_news(news_id="x", title="반도체", sentiment_score=None)]
    s = aggregate(rows, _kw(), {}, {}, NOW).scores[0]
    assert s["n_news"] == 1 and s["n_dir"] == 0 and s["score_raw"] == 0.0


def test_aggregate_is_deterministic():
    rows = [_news(news_id=str(i), title="반도체", sentiment_score=0.3 * (i % 3 - 1)) for i in range(9)]
    a = aggregate(rows, _kw(), {}, {}, NOW)
    b = aggregate(rows, _kw(), {}, {}, NOW)
    assert a.scores == b.scores and a.hits == b.hits
```

- [ ] **Step 2: 실패 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_aggregator.py -v -k "attribute or aggregate"
```

Expected: `ImportError: cannot import name 'attribute_news'`.

- [ ] **Step 3: 구현** (`sector_news_aggregator.py` 끝에 추가)

```python
# ── 귀속 ───────────────────────────────────────────────────────────────────
@dataclass
class SectorHit:
    route: str            # 가중치 최대 경로
    routes: List[str]     # 걸린 경로 전부
    matched: str          # 키워드 / 종목코드
    w_match: float


def attribute_news(news: Dict, kwdict: SectorKeywordDict, code_to_sector: Dict[str, str], *,
                   stock_route_enabled: bool, summary: Dict) -> Dict[str, SectorHit]:
    """뉴스 1건 → {섹터: SectorHit}. 경로 A(키워드) + 경로 B(related_stocks→KSIC3). 경로 중복 시 max 가중 하나."""
    result: Dict[str, SectorHit] = {}
    for key, kh in match_sectors(news.get("title"), news.get("content"), kwdict, BODY_CHARS).items():
        result[key] = SectorHit(kh.route, [kh.route], kh.matched, _ROUTE_WEIGHT[kh.route])

    if stock_route_enabled:
        codes = split_related_stocks(news.get("related_stocks"))
        if len(codes) > MAX_CODES_PER_NEWS:
            summary["stock_route_skipped"] = summary.get("stock_route_skipped", 0) + 1
        else:
            for code in codes:
                sec = code_to_sector.get(code)
                if sec is None:
                    continue
                if sec in result:
                    h = result[sec]
                    if ROUTE_STOCK not in h.routes:
                        h.routes.append(ROUTE_STOCK)
                        h.matched = f"{h.matched},{code}"
                    else:
                        h.matched = f"{h.matched},{code}"
                    if W_STOCK > h.w_match:
                        h.w_match = W_STOCK
                        h.route = ROUTE_STOCK
                else:
                    result[sec] = SectorHit(ROUTE_STOCK, [ROUTE_STOCK], code, W_STOCK)
    return result


# ── 집계 ───────────────────────────────────────────────────────────────────
@dataclass
class AggregationResult:
    trade_date: date
    window_start: datetime
    window_end: datetime
    scores: List[Dict] = field(default_factory=list)
    hits: List[Dict] = field(default_factory=list)
    summary: Dict = field(default_factory=dict)


def _to_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def aggregate(news_rows: List[Dict], kwdict: SectorKeywordDict, code_to_sector: Dict[str, str],
              sector_names: Dict[str, str], now: datetime, *, stock_route_enabled: bool = True) -> AggregationResult:
    """스펙 §4.4:
        c(i,s)       = sentiment × w_match × w_src
        n_dir        = |sentiment| >= DIR_EPS 인 뉴스 수 (중립 DART 정형공시는 분모에 안 넣는다)
        score_norm   = Σc / sqrt(max(n_dir,1))
        score_signed = 0 (n_dir < MIN_N) | clip(score_norm / K_SCALE, -1, +1)
    """
    trade_date, ws, we = compute_window(now)
    summary: Dict = {"n_input": len(news_rows), "stock_route_enabled": stock_route_enabled, "stock_route_skipped": 0}
    acc: Dict[str, Dict] = {}
    hits: List[Dict] = []

    for n in news_rows:
        sent = _to_float(n.get("sentiment_score"))
        w_src = SOURCE_CREDIBILITY.get(n.get("source"), DEFAULT_W_SRC)
        per_sector = attribute_news(n, kwdict, code_to_sector, stock_route_enabled=stock_route_enabled, summary=summary)
        for key, h in per_sector.items():
            c = sent * h.w_match * w_src
            a = acc.setdefault(key, {"n_news": 0, "n_dir": 0, "n_kw": 0, "n_stock": 0,
                                     "n_pos": 0, "n_neg": 0, "score_raw": 0.0, "top": []})
            a["n_news"] += 1
            if abs(sent) >= DIR_EPS:
                a["n_dir"] += 1
            if ROUTE_KW_TITLE in h.routes or ROUTE_KW_BODY in h.routes:
                a["n_kw"] += 1
            if ROUTE_STOCK in h.routes:
                a["n_stock"] += 1
            if sent >= DIR_EPS:
                a["n_pos"] += 1
            elif sent <= -DIR_EPS:
                a["n_neg"] += 1
            a["score_raw"] += c
            a["top"].append({"news_id": n.get("news_id"), "title": (n.get("title") or "")[:120],
                             "c": round(c, 4), "route": h.route})
            hits.append({"trade_date": trade_date, "news_id": n.get("news_id"), "sector_key": key,
                         "route": h.route, "routes": ",".join(h.routes), "matched": h.matched[:200],
                         "w_match": h.w_match, "contribution": c})

    scores: List[Dict] = []
    for key, a in acc.items():
        score_norm = a["score_raw"] / math.sqrt(max(a["n_dir"], 1))
        score_signed = 0.0 if a["n_dir"] < MIN_N else _clip(score_norm / K_SCALE)
        top = sorted(a["top"], key=lambda x: abs(x["c"]), reverse=True)[:TOP_NEWS]
        name = kwdict.sectors[key].name if key in kwdict.sectors else sector_names.get(key)
        scores.append({
            "trade_date": trade_date, "sector_key": key, "sector_name": name,
            "window_start": ws, "window_end": we,
            "n_news": a["n_news"], "n_dir": a["n_dir"], "n_kw": a["n_kw"], "n_stock": a["n_stock"],
            "n_pos": a["n_pos"], "n_neg": a["n_neg"],
            "score_raw": a["score_raw"], "score_norm": score_norm, "score_signed": score_signed,
            "top_news": top,
        })
    summary.update({"n_hits": len(hits), "n_sectors": len(scores)})
    return AggregationResult(trade_date, ws, we, scores, hits, summary)
```

- [ ] **Step 4: 통과 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_aggregator.py -v
```

Expected: `22 passed`.

- [ ] **Step 5: 커밋**

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
feat(sector): 뉴스→섹터 귀속(경로 A+B, max 가중 하나)·기여도·집계 — n_dir 분모·sqrt-n·clip·MIN_N (스펙 B §4.3-4.4)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/tmp/nq-wt-sector-news && git add news_scraper/sector_news_aggregator.py tests/test_sector_news_aggregator.py && git commit -F D:/tmp/nq_commit_msg.txt
```

---

### Task 6: `database.py` — DDL·OWNER·읽기·쓰기

**Files:**
- Modify: `news_scraper/database.py` (`import json` 추가 · `init_database()` 끝에 호출 1줄 · 클래스 끝에 메서드 5개)
- Test: `tests/test_sector_news_db.py` (`@pytest.mark.db`)

**Interfaces:**
- Produces (`NewsDatabase` 메서드):
  - `init_sector_news_tables() -> None` — DDL 2표 + 인덱스, 커밋, 그 뒤 OWNER 변경(각각 try · WARNING)
  - `get_news_in_window(start: datetime, end: datetime) -> List[Dict]` — `published_at > start AND <= end`, 키 `news_id title content source category sentiment_score related_stocks published_at`
  - `get_sector_map_as_of(as_of: date, codes: List[str]) -> Tuple[Dict[str,str], Dict[str,str]]` — `({code: ksic3}, {ksic3: name})`. **함수 부재는 예외를 그대로 올린다**
  - `write_sector_news_result(trade_date: date, scores: List[Dict], hits: List[Dict]) -> Tuple[int,int]` — 한 트랜잭션(hit DELETE+INSERT, score UPSERT)
  - `get_sector_news_scores(trade_date: date) -> List[Dict]` — JSON 직렬화 가능한 dict(날짜는 isoformat, Decimal→float), `score_signed DESC, n_dir DESC`
- Consumes: Task 5 의 `scores`/`hits` dict 모양 + `dict_version`(Task 7 이 채움)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_sector_news_db.py`

```python
"""실 DB(kis_template) 왕복. DB 없으면 conftest.db 픽스처가 skip 한다."""
from datetime import date, datetime

import pytest

pytestmark = pytest.mark.db

TD = date(1999, 1, 4)   # 실데이터와 겹치지 않는 센티널 거래일


@pytest.fixture
def clean(db):
    yield
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news_sector_hit WHERE trade_date = %s", (TD,))
            cur.execute("DELETE FROM sector_news_score WHERE trade_date = %s", (TD,))
        conn.commit()
    finally:
        db._put_connection(conn)


def _score(key="261", signed=0.4):
    return {"trade_date": TD, "sector_key": key, "sector_name": "반도체 제조업",
            "window_start": datetime(1999, 1, 1, 15, 30), "window_end": datetime(1999, 1, 4, 8, 50),
            "n_news": 4, "n_dir": 3, "n_kw": 2, "n_stock": 2, "n_pos": 2, "n_neg": 1,
            "score_raw": 0.684, "score_norm": 0.395, "score_signed": signed,
            "top_news": [{"news_id": "t1", "title": "x", "c": 0.45, "route": "kw_title"}],
            "dict_version": "test"}


def _hit(news_id="t1", key="261"):
    return {"trade_date": TD, "news_id": news_id, "sector_key": key, "route": "kw_title",
            "routes": "kw_title,stock", "matched": "반도체,005930", "w_match": 1.0, "contribution": 0.45}


def test_tables_exist_and_owned_by_robotrader(db):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tablename, tableowner FROM pg_tables WHERE tablename IN ('sector_news_score','news_sector_hit')")
            rows = dict(cur.fetchall())
    finally:
        db._put_connection(conn)
    assert set(rows) == {"sector_news_score", "news_sector_hit"}
    assert set(rows.values()) == {"robotrader"}


def test_init_is_idempotent(db):
    db.init_sector_news_tables()
    db.init_sector_news_tables()


def test_write_then_read_roundtrip_and_upsert(db, clean):
    assert db.write_sector_news_result(TD, [_score()], [_hit()]) == (1, 1)
    rows = db.get_sector_news_scores(TD)
    assert len(rows) == 1 and rows[0]["sector_key"] == "261" and rows[0]["score_signed"] == 0.4
    assert rows[0]["trade_date"] == "1999-01-04" and isinstance(rows[0]["computed_at"], str)
    assert rows[0]["top_news"][0]["news_id"] == "t1"
    first_computed = rows[0]["computed_at"]

    # 같은 키 재쓰기 → 1행 유지 · 값 갱신 · computed_at 갱신 · hit 는 교체
    assert db.write_sector_news_result(TD, [_score(signed=-0.2)], [_hit("t2")]) == (1, 1)
    rows = db.get_sector_news_scores(TD)
    assert len(rows) == 1 and rows[0]["score_signed"] == -0.2 and rows[0]["computed_at"] >= first_computed
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT news_id FROM news_sector_hit WHERE trade_date = %s", (TD,))
            assert [r[0] for r in cur.fetchall()] == ["t2"]
    finally:
        db._put_connection(conn)


def test_read_empty_day_returns_empty_list(db):
    assert db.get_sector_news_scores(date(1998, 1, 1)) == []


def test_get_news_in_window_shape(db):
    rows = db.get_news_in_window(datetime(2026, 9, 3, 15, 30), datetime(2026, 9, 4, 9, 0))
    assert isinstance(rows, list)
    if rows:
        assert {"news_id", "title", "content", "source", "sentiment_score", "related_stocks", "published_at"} <= set(rows[0])


def test_get_sector_map_as_of_roundtrip(db):
    """스펙 A 함수가 있으면 dict 두 개(0행이어도 OK). 없으면 예외가 그대로 올라온다(잡이 경로 B 를 끈다)."""
    try:
        code_map, names = db.get_sector_map_as_of(date(2026, 9, 4), ["005930", "000660"])
    except Exception as e:
        assert type(e).__name__ == "UndefinedFunction"
        return
    assert isinstance(code_map, dict) and isinstance(names, dict)
    for k, v in code_map.items():
        assert len(k) == 6 and len(v) == 3
    assert db.get_sector_map_as_of(date(2026, 9, 4), []) == ({}, {})
```

- [ ] **Step 2: 실패 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_db.py -v
```

Expected: DB 있으면 `AttributeError: 'NewsDatabase' object has no attribute 'init_sector_news_tables'` 등 FAIL. DB 없으면 전부 SKIP(그 경우 이 태스크는 DB 가 있는 환경에서 완료해야 한다).

- [ ] **Step 3: 구현** — `news_scraper/database.py`

상단 import 에 `import json` 추가. `init_database()` 의 `finally` 앞(모든 기존 DDL 실행·commit 뒤)에:

```python
        # 스펙 B: 섹터 뉴스 점수 표 (실패해도 뉴스 수집은 계속 — 집계 잡이 나중에 다시 실패를 보고한다)
        try:
            self.init_sector_news_tables()
        except Exception as e:
            logger.error(f"[섹터뉴스] 표 초기화 실패(수집은 계속): {e}")
```

⚠️ 기존 `init_database()` 는 자기 커넥션을 `finally` 에서 반환한다. 위 호출은 그 `try` 블록 «안», 기존 DDL 커밋 «뒤»에 둔다 — `init_sector_news_tables` 는 자기 커넥션을 따로 얻는다.

클래스 끝에 추가:

```python
    # ------------------------------------------------------------------
    # 섹터 뉴스 점수 (스펙 B, 2026-09-06) — 봇(kis-trading-template)이 읽는다
    # ------------------------------------------------------------------
    SECTOR_NEWS_DDL = (
        """
        CREATE TABLE IF NOT EXISTS sector_news_score (
            trade_date    date        NOT NULL,
            taxonomy      text        NOT NULL DEFAULT 'ksic3',
            sector_key    text        NOT NULL,
            sector_name   text,
            window_start  timestamp   NOT NULL,
            window_end    timestamp   NOT NULL,
            n_news        integer     NOT NULL,
            n_dir         integer     NOT NULL,
            n_kw          integer     NOT NULL,
            n_stock       integer     NOT NULL,
            n_pos         integer     NOT NULL,
            n_neg         integer     NOT NULL,
            score_raw     double precision NOT NULL,
            score_norm    double precision NOT NULL,
            score_signed  double precision NOT NULL,
            top_news      jsonb,
            dict_version  text,
            computed_at   timestamp   NOT NULL DEFAULT now(),
            PRIMARY KEY (trade_date, taxonomy, sector_key)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_sns_date ON sector_news_score (trade_date, computed_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS news_sector_hit (
            trade_date    date    NOT NULL,
            news_id       text    NOT NULL,
            sector_key    text    NOT NULL,
            route         text    NOT NULL,
            routes        text    NOT NULL,
            matched       text,
            w_match       double precision NOT NULL,
            contribution  double precision NOT NULL,
            computed_at   timestamp NOT NULL DEFAULT now(),
            PRIMARY KEY (trade_date, news_id, sector_key)
        )
        """,
    )
    # DB 관례: 67표 전부 robotrader 소유. NewsQuant 는 postgres 로 붙으므로 만든 뒤 넘긴다.
    SECTOR_NEWS_OWNER_SQL = (
        "ALTER TABLE sector_news_score OWNER TO robotrader",
        "ALTER TABLE news_sector_hit OWNER TO robotrader",
    )

    def init_sector_news_tables(self) -> None:
        """DDL(멱등) + OWNER 변경. OWNER 실패는 WARNING(권한 없는 롤일 때)."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for sql in self.SECTOR_NEWS_DDL:
                    cur.execute(sql)
            conn.commit()
            for sql in self.SECTOR_NEWS_OWNER_SQL:
                try:
                    with conn.cursor() as cur:
                        cur.execute(sql)
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logger.warning(f"[섹터뉴스] OWNER 변경 실패(무시): {sql} → {e}")
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_connection(conn)

    def get_news_in_window(self, start: datetime, end: datetime) -> List[Dict]:
        """창 (start, end] 안의 뉴스. 집계에 필요한 열만."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT news_id, title, content, source, category,
                           sentiment_score, related_stocks, published_at
                    FROM news
                    WHERE published_at > %s AND published_at <= %s
                    ORDER BY published_at
                """, (start, end))
                return self._rows_to_dicts(cur)
        finally:
            conn.rollback()
            self._put_connection(conn)

    def get_sector_map_as_of(self, as_of, codes: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
        """스펙 A `fn_sector_map_as_of(as_of)` → ({code: ksic3}, {ksic3: name}).
        함수가 없으면 psycopg2.errors.UndefinedFunction 이 그대로 올라간다 — 호출자(잡)가 경로 B 를 끈다."""
        if not codes:
            return {}, {}
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT stock_code, left(ksic_code, 3) AS ksic3, ksic3_name
                    FROM fn_sector_map_as_of(%s)
                    WHERE stock_code = ANY(%s) AND ksic_code IS NOT NULL AND length(ksic_code) >= 3
                """, (as_of, list(codes)))
                code_map: Dict[str, str] = {}
                names: Dict[str, str] = {}
                for stock_code, ksic3, name in cur.fetchall():
                    code_map[stock_code] = ksic3
                    if name and ksic3 not in names:
                        names[ksic3] = name
                return code_map, names
        finally:
            conn.rollback()   # 실패한 트랜잭션을 풀에 돌려보내지 않는다
            self._put_connection(conn)

    def write_sector_news_result(self, trade_date, scores: List[Dict], hits: List[Dict]) -> Tuple[int, int]:
        """한 트랜잭션: news_sector_hit 그 날짜 DELETE+INSERT · sector_news_score UPSERT. (저장 섹터 수, 저장 hit 수)"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM news_sector_hit WHERE trade_date = %s", (trade_date,))
                if hits:
                    extras.execute_values(cur, """
                        INSERT INTO news_sector_hit
                            (trade_date, news_id, sector_key, route, routes, matched, w_match, contribution)
                        VALUES %s
                        ON CONFLICT (trade_date, news_id, sector_key) DO UPDATE SET
                            route = EXCLUDED.route, routes = EXCLUDED.routes, matched = EXCLUDED.matched,
                            w_match = EXCLUDED.w_match, contribution = EXCLUDED.contribution, computed_at = now()
                    """, [(h["trade_date"], h["news_id"], h["sector_key"], h["route"], h["routes"],
                           h["matched"], h["w_match"], h["contribution"]) for h in hits])
                if scores:
                    extras.execute_values(cur, """
                        INSERT INTO sector_news_score
                            (trade_date, taxonomy, sector_key, sector_name, window_start, window_end,
                             n_news, n_dir, n_kw, n_stock, n_pos, n_neg,
                             score_raw, score_norm, score_signed, top_news, dict_version, computed_at)
                        VALUES %s
                        ON CONFLICT (trade_date, taxonomy, sector_key) DO UPDATE SET
                            sector_name = EXCLUDED.sector_name,
                            window_start = EXCLUDED.window_start, window_end = EXCLUDED.window_end,
                            n_news = EXCLUDED.n_news, n_dir = EXCLUDED.n_dir, n_kw = EXCLUDED.n_kw,
                            n_stock = EXCLUDED.n_stock, n_pos = EXCLUDED.n_pos, n_neg = EXCLUDED.n_neg,
                            score_raw = EXCLUDED.score_raw, score_norm = EXCLUDED.score_norm,
                            score_signed = EXCLUDED.score_signed, top_news = EXCLUDED.top_news,
                            dict_version = EXCLUDED.dict_version, computed_at = now()
                    """, [(s["trade_date"], "ksic3", s["sector_key"], s.get("sector_name"),
                           s["window_start"], s["window_end"],
                           s["n_news"], s["n_dir"], s["n_kw"], s["n_stock"], s["n_pos"], s["n_neg"],
                           s["score_raw"], s["score_norm"], s["score_signed"],
                           json.dumps(s.get("top_news") or [], ensure_ascii=False), s.get("dict_version"))
                          for s in scores],
                        template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, now())")
            conn.commit()
            return len(scores), len(hits)
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_connection(conn)

    @staticmethod
    def _jsonable(value):
        if isinstance(value, (datetime, )):
            return value.isoformat()
        if hasattr(value, "isoformat"):      # date
            return value.isoformat()
        try:
            from decimal import Decimal
            if isinstance(value, Decimal):
                return float(value)
        except ImportError:
            pass
        return value

    def get_sector_news_scores(self, trade_date) -> List[Dict]:
        """그 거래일의 섹터 점수(JSON 직렬화 가능한 dict). score_signed DESC, n_dir DESC."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT trade_date, taxonomy, sector_key, sector_name, window_start, window_end,
                           n_news, n_dir, n_kw, n_stock, n_pos, n_neg,
                           score_raw, score_norm, score_signed, top_news, dict_version, computed_at
                    FROM sector_news_score
                    WHERE trade_date = %s AND taxonomy = 'ksic3'
                    ORDER BY score_signed DESC, n_dir DESC, sector_key
                """, (trade_date,))
                cols = [d[0] for d in cur.description]
                return [{c: self._jsonable(v) for c, v in zip(cols, row)} for row in cur.fetchall()]
        finally:
            conn.rollback()
            self._put_connection(conn)
```

- [ ] **Step 4: 통과 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_db.py -v
```

Expected: `6 passed`. `test_tables_exist_and_owned_by_robotrader` 가 실패하면 `postgres` 롤로 붙었는지(`config.yaml`) 확인.

- [ ] **Step 5: 기존 테스트 전체 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest -q
```

Expected: 전부 passed.

- [ ] **Step 6: 커밋**

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
feat(db): sector_news_score·news_sector_hit DDL(OWNER robotrader)·창 조회·fn_sector_map_as_of 조회·한 트랜잭션 쓰기·점수 조회 (스펙 B §3.1-3.4)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/tmp/nq-wt-sector-news && git add news_scraper/database.py tests/test_sector_news_db.py && git commit -F D:/tmp/nq_commit_msg.txt
```

---

### Task 7: 집계 잡 `run_sector_news_job` + 스케줄러 등록

**Files:**
- Create: `news_scraper/sector_news_job.py`
- Modify: `news_scraper/scheduler.py` — `run_sector_news_aggregation()` 메서드 · `setup_schedule()` 잡 · `start()` 1회 호출
- Test: `tests/test_sector_news_job.py`

**Interfaces:**
- Produces: `run_sector_news_job(db, now: Optional[datetime] = None, kw_path=None) -> Dict` — 항상 dict 를 돌려주고 예외를 내지 않는다. 키: `ok frozen trade_date window n_news n_hits n_sectors stock_route stock_route_skipped mapped_codes ms` / 실패 시 `ok=False, error=...`
- Produces: `now_kst_naive() -> datetime`
- Consumes: `db.get_news_in_window` · `db.get_sector_map_as_of` · `db.write_sector_news_result` (Task 6) · `load_sector_keywords`(Task 1) · `aggregate/compute_window/is_frozen/split_related_stocks/prev_weekday`(Task 4·5)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_sector_news_job.py`

```python
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
    assert all(x["dict_version"] == "2026-09-06.1" for x in scores)
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
```

- [ ] **Step 2: 실패 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_job.py -v
```

Expected: `ModuleNotFoundError: news_scraper.sector_news_job`.

- [ ] **Step 3: 구현** — `news_scraper/sector_news_job.py`

```python
"""섹터 뉴스 집계 잡 — 오케스트레이션(DB 읽기 → 순수 집계 → DB 쓰기). 스펙 B §4.5.

🔑 예외를 밖으로 내지 않는다(스케줄러를 죽이지 않는다 — _handle_crawler_result 관례).
   항상 summary dict 를 돌려준다.
"""
import logging
import time as _time
from datetime import datetime
from typing import Dict, Optional

import pytz

from .sector_keywords import load_sector_keywords, SectorKeywordError
from .sector_news_aggregator import (
    aggregate, compute_window, is_frozen, prev_weekday, split_related_stocks, MAX_CODES_PER_NEWS,
)

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")


def now_kst_naive() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def run_sector_news_job(db, now: Optional[datetime] = None, kw_path=None) -> Dict:
    """1회 실행. db 는 NewsDatabase(또는 같은 메서드를 가진 대역)."""
    t0 = _time.monotonic()
    now = now or now_kst_naive()
    summary: Dict = {"ok": False, "now": now.isoformat()}
    try:
        trade_date, ws, we = compute_window(now)
        if is_frozen(now):
            summary.update({"ok": True, "frozen": True, "trade_date": trade_date.isoformat()})
            logger.info(f"[섹터뉴스] 동결 구간(09:05~15:30) — trade_date={trade_date} 갱신 생략")
            return summary

        try:
            kwdict = load_sector_keywords(kw_path)
        except (SectorKeywordError, OSError) as e:
            logger.error(f"[섹터뉴스] 사전 로드 실패 — 집계 중단: {e}")
            summary["error"] = f"dict:{e}"
            return summary

        news_rows = db.get_news_in_window(ws, we)

        codes = set()
        for n in news_rows:
            codes.update(split_related_stocks(n.get("related_stocks")))
        code_to_sector: Dict[str, str] = {}
        sector_names: Dict[str, str] = {}
        stock_route_enabled = True
        try:
            code_to_sector, sector_names = db.get_sector_map_as_of(prev_weekday(trade_date), sorted(codes))
        except Exception as e:
            stock_route_enabled = False
            logger.warning(f"[섹터뉴스] 경로 B 비활성 — fn_sector_map_as_of 조회 실패: {type(e).__name__}: {e}")

        result = aggregate(news_rows, kwdict, code_to_sector, sector_names, now,
                           stock_route_enabled=stock_route_enabled)
        for s in result.scores:
            s["dict_version"] = kwdict.version
        n_scores, n_hits = db.write_sector_news_result(trade_date, result.scores, result.hits)

        skipped = result.summary.get("stock_route_skipped", 0)
        ms = int((_time.monotonic() - t0) * 1000)
        summary.update({
            "ok": True, "frozen": False, "trade_date": trade_date.isoformat(),
            "window": [ws.isoformat(), we.isoformat()],
            "n_news": len(news_rows), "n_hits": n_hits, "n_sectors": n_scores,
            "stock_route": stock_route_enabled, "stock_route_skipped": skipped,
            "mapped_codes": len(code_to_sector), "ms": ms,
        })
        logger.info(
            f"[섹터뉴스] trade_date={trade_date} 창={ws:%m-%d %H:%M}~{we:%m-%d %H:%M} "
            f"뉴스 {len(news_rows)} · 귀속 {n_hits} · 섹터 {n_scores} · "
            f"경로B {'on' if stock_route_enabled else 'off'}(매핑 {len(code_to_sector)}/{len(codes)}) · "
            f"절단 {skipped} · {ms}ms"
        )
        if skipped:
            logger.warning(f"[섹터뉴스] related_stocks > {MAX_CODES_PER_NEWS} 로 경로 B 건너뛴 뉴스 {skipped}건")
        return summary
    except Exception as e:
        logger.error(f"[섹터뉴스] 집계 실패: {e}", exc_info=True)
        summary["error"] = f"{type(e).__name__}: {e}"
        return summary
```

- [ ] **Step 4: 통과 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_job.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: 스케줄러 등록** — `news_scraper/scheduler.py`

`setup_schedule()` 의 기존 `add_job(...)` 바로 뒤에:

```python
        # 스펙 B: 섹터 뉴스 점수 집계 (10분) — sector_news_score UPSERT. 봇이 09:00 에 읽는다.
        self.scheduler.add_job(
            func=self.run_sector_news_aggregation,
            trigger=IntervalTrigger(minutes=10),
            id='sector_news_aggregation',
            max_instances=1,
            misfire_grace_time=300
        )
        logger.info("- 섹터 뉴스 집계: 10분마다 (평일 09:05~15:30 동결)")
```

`start()` 의 `self.collect_all_news()` 바로 뒤에:

```python
            # 첫 수집 직후 섹터 점수 1회 (07:40 기동 → 09:00 전에 8회 더 돈다)
            self.run_sector_news_aggregation()
```

클래스에 메서드 추가(`stop()` 앞):

```python
    def run_sector_news_aggregation(self):
        """섹터 뉴스 점수 집계 1회 (스펙 B). 예외는 잡 안에서 처리된다."""
        from .sector_news_job import run_sector_news_job
        return run_sector_news_job(self.db)
```

- [ ] **Step 6: 스케줄러 배선 테스트 추가** (`tests/test_sector_news_job.py` 끝에)

```python
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
```

- [ ] **Step 7: 통과 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_job.py -v
```

Expected: `7 passed`. (`setup_schedule()` 는 `start()` 안에서 한 번만 불린다 — 테스트에서 따로 부르면 `ConflictingIdError` 가 난다.)

- [ ] **Step 8: 커밋**

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
feat(sector): 집계 잡 run_sector_news_job(동결·사전 실패 중단·경로 B fail-soft·예외 삼킴) + 스케줄러 10분 잡·기동 시 1회 (스펙 B §4.5)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/tmp/nq-wt-sector-news && git add news_scraper/sector_news_job.py news_scraper/scheduler.py tests/test_sector_news_job.py && git commit -F D:/tmp/nq_commit_msg.txt
```

---

### Task 8: 점검용 API + 문서

**Files:**
- Modify: `news_scraper/api/server.py` (`/api/market/global-sentiment` 뒤, `start_api_server` 앞에 엔드포인트 추가)
- Modify: `docs/API_사용가이드.md` (엔드포인트 1개 추가)
- Test: `tests/test_sector_news_api.py`

**Interfaces:**
- Produces: `GET /api/sector/news-score?trade_date=YYYY-MM-DD` → `{success, trade_date, count, computed_at_max, data:[행…]}`. 잘못된 날짜 400. 봇은 쓰지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_sector_news_api.py`

```python
import pytest

pytestmark = pytest.mark.db   # server 모듈 import 가 NewsDatabase() 를 만든다 → 실 DB 필요


@pytest.fixture(scope="module")
def client(db):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from news_scraper.api.server import app
    return TestClient(app)


def test_sector_news_score_default_today(client):
    r = client.get("/api/sector/news-score")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and "trade_date" in body and body["count"] == len(body["data"])


def test_sector_news_score_explicit_empty_day(client):
    r = client.get("/api/sector/news-score", params={"trade_date": "1998-01-01"})
    assert r.status_code == 200
    assert r.json() == {"success": True, "trade_date": "1998-01-01", "count": 0, "computed_at_max": None, "data": []}


def test_sector_news_score_bad_date_400(client):
    r = client.get("/api/sector/news-score", params={"trade_date": "2026/09/08"})
    assert r.status_code == 400
```

- [ ] **Step 2: 실패 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_api.py -v
```

Expected: 404 → FAIL (DB 없거나 httpx 없으면 SKIP — httpx 가 없으면 `python -m pip install httpx` 후 진행).

- [ ] **Step 3: 구현** — `news_scraper/api/server.py`

```python
@app.get("/api/sector/news-score")
async def get_sector_news_score(
    trade_date: Optional[str] = Query(None, description="YYYY-MM-DD (기본: 현재 시각 기준 거래일)"),
):
    """섹터 뉴스 점수 조회 (스펙 B 점검용).

    봇(kis-trading-template)은 이 엔드포인트를 쓰지 않는다 — DB 표 sector_news_score 를 직접 읽는다.
    """
    from ..sector_news_aggregator import compute_trade_date
    from ..sector_news_job import now_kst_naive

    if trade_date is None:
        td = compute_trade_date(now_kst_naive())
    else:
        try:
            td = datetime.strptime(trade_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="trade_date 형식은 YYYY-MM-DD")
    try:
        rows = db.get_sector_news_scores(td)
        computed = [r["computed_at"] for r in rows if r.get("computed_at")]
        return JSONResponse({
            "success": True,
            "trade_date": td.isoformat(),
            "count": len(rows),
            "computed_at_max": max(computed) if computed else None,
            "data": rows,
        })
    except Exception as e:
        logger.error(f"Error getting sector news score: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: 통과 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest tests/test_sector_news_api.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: 문서** — `docs/API_사용가이드.md` 끝에 섹션 추가

```markdown
## 섹터 뉴스 점수 (스펙 B, 2026-09)

`GET /api/sector/news-score?trade_date=YYYY-MM-DD` — 거래일별 KSIC 3자리 섹터 뉴스 점수(`score_signed` −1~+1). `trade_date` 생략 시 현재 시각 기준 거래일.
점검용이다. 봇은 DB 표 `sector_news_score` 를 직접 읽는다. 설계: `D:\GIT\kis-trading-template\RoboTrader_template\docs\superpowers\specs\2026-09-06-sector-news-boost-design.md`.
```

- [ ] **Step 6: 커밋**

```
cat > D:/tmp/nq_commit_msg.txt <<'MSG'
feat(api): GET /api/sector/news-score 점검용 엔드포인트 + API 가이드 (스펙 B §4.6)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016jwWaZvM9aCiFTpLVurMpq
MSG
cd D:/tmp/nq-wt-sector-news && git add news_scraper/api/server.py docs/API_사용가이드.md tests/test_sector_news_api.py && git commit -F D:/tmp/nq_commit_msg.txt
```

---

### Task 9: 실 DB 1회 실행 검증 · 전체 테스트 · 머지

**Files:**
- 없음(검증·머지)

- [ ] **Step 1: 실 DB 로 잡 1회 수동 실행** (워크트리 · 쓰기 발생 — 현재 시각 기준 `trade_date`)

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -c "
from news_scraper.database import NewsDatabase
from news_scraper.sector_news_job import run_sector_news_job
import json; print(json.dumps(run_sector_news_job(NewsDatabase()), ensure_ascii=False, indent=1))"
```

Expected: `"ok": true`. 평일 09:05~15:30 이면 `"frozen": true`(그 경우 `now=` 를 넘겨 재실행: `run_sector_news_job(NewsDatabase(), now=datetime(…, 8, 50))`). 경로 B 는 스펙 A 명부가 0행이면 `"stock_route": true, "mapped_codes": 0`, 함수가 없으면 `false` — 둘 다 정상.

- [ ] **Step 2: 결과 눈으로 확인**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -c "
from news_scraper.database import NewsDatabase
from news_scraper.sector_news_aggregator import compute_trade_date
from news_scraper.sector_news_job import now_kst_naive
db = NewsDatabase()
for r in db.get_sector_news_scores(compute_trade_date(now_kst_naive()))[:10]:
    print(r['sector_key'], r['sector_name'], r['n_news'], r['n_dir'], round(r['score_signed'],3), [t['title'][:30] for t in r['top_news'][:2]])"
```

Expected: 섹터 행 여러 개. `score_signed` 가 전부 0 이면 창 안 뉴스가 적은 것(주말·야간 프로세스 부재) — 스펙 §11 에 적힌 정상 상황.

- [ ] **Step 3: 전체 테스트**

```
cd D:/tmp/nq-wt-sector-news && PYTHONUTF8=1 python -m pytest -q
```

Expected: 전부 passed(DB 있으면 skip 0).

- [ ] **Step 4: 머지** (라이브 디렉터리는 07:40 기동 — **장 마감 후 또는 주말**에 머지하고, 라이브 프로세스는 다음 07:40 기동 때 새 코드를 탄다)

```
cd D:/GIT/NewsQuant && git status --short && git merge --no-ff feat/sector-news-score -m "merge(sector): 스펙 B NewsQuant 측 — 키워드 사전·집계·sector_news_score·10분 잡·API" && git log --oneline -3
```

Expected: fast-forward 아닌 merge 커밋. `git status --short` 에 tracked 변경 없음.

- [ ] **Step 5: 워크트리 정리 · 포인터 문서 갱신**

```
cd D:/GIT/NewsQuant && git worktree remove D:/tmp/nq-wt-sector-news && git branch -d feat/sector-news-score
```

`docs/섹터뉴스부스트_스펙B_포인터_2026-09-06.md` 의 「NewsQuant 쪽에서 바뀌는 것」 표 아래에 한 줄 추가 후 커밋:

```markdown
구현 완료: <머지 커밋 sha> (<날짜>). 계획: `docs/superpowers/plans/2026-09-07-sector-news-boost-newsquant.md`.
```

---

## Self-Review (작성 후 점검)

- **스펙 커버리지**: §2.1 파일 전부(사전 T3 · 순수 로직 T1·2·4·5 · database T6 · scheduler T7 · API T8 · requirements/pyproject/tests T0 · 포인터 T9) · §3.1·3.2·3.4 T6 · §4.1 T4 · §4.2 T1-3 · §4.3 T5·T7 · §4.4 T5 · §4.5 T7 · §4.6 T8 · §7.1 T1-8. 스펙 정정(동결 09:05~15:30 · 두 모듈 분할 · 섹터 간 키워드 공유 허용 · 한/영 신뢰도 합침)은 스펙 v1.1 에 반영한다.
- **타입 일관성**: `aggregate(...) -> AggregationResult(scores: List[Dict], hits: List[Dict])` → `write_sector_news_result(trade_date, scores, hits)` → `get_sector_news_scores(trade_date) -> List[Dict]` → API `data`. `get_sector_map_as_of -> (Dict, Dict)` 를 T7 이 언팩. `run_sector_news_job(db, now, kw_path)` 시그니처 T7·T9 동일.
- **플레이스홀더**: 없음.
