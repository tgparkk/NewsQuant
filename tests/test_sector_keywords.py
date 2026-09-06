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
