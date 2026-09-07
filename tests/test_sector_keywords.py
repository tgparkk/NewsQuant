import pytest

from news_scraper.sector_keywords import (
    SectorKeywordError, parse_sector_keywords, load_sector_keywords,
    KeywordHit, match_sectors, ROUTE_KW_TITLE, ROUTE_KW_BODY, DEFAULT_PATH,
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


def test_shipped_dictionary_loads_and_has_49_sectors():
    d = load_sector_keywords()
    assert DEFAULT_PATH.exists()
    assert d.version == "2026-09-07.1"
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
    assert "192" not in match_sectors("유가증권시장 거래대금 급증", "", d)
    assert "192" in match_sectors("국제유가 급등에 정유주 강세", "", d)
    assert "311" not in match_sectors("[조선비즈] 코스피 전망", "", d)
    assert "311" in match_sectors("조선주 일제히 상승", "", d)
    assert "252" not in match_sectors("무기한 파업 돌입", "", d)
    assert "412" not in match_sectors("Qualcomm new SoC boosts smartphone performance", "", d)
    assert "412" in match_sectors("정부 SOC 예산 20% 증액", "", d)
    assert "281" not in match_sectors("Nvidia unveils new transformer model", "", d)
