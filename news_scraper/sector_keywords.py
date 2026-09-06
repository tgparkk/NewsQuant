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
