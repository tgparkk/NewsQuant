"""stock_info → 종목 사전 생성기.

기존 생성기(`scripts/fetch_stock_list_naver.py`)는 네이버 금융을 긁으면서
접미사를 잘라 별칭을 만들었다. 그 별칭이 다른 회사를 덮어써서 골프존(215000)·
F&F(383220)·컴투스(078340)·대상(001680) 이 사전에서 통째로 사라졌다.

새 생성기는 DB 의 `stock_info`(권위 표)를 그대로 옮기기만 한다 — 별칭을
«만들지 않는 것» 이 이 모듈의 존재 이유다.
"""
import pytest

from scripts.build_stock_dict import build_dict


def test_이름과_코드를_그대로_옮긴다():
    rows = [("삼성전자", "005930"), ("F&F", "383220")]

    assert build_dict(rows) == {"삼성전자": "005930", "F&F": "383220"}


def test_접미사를_잘라_별칭을_만들지_않는다():
    """구 생성기가 '삼성전자'에서 '삼성'을 파생시켜 사고를 냈다."""
    result = build_dict([("삼성전자", "005930"), ("대웅제약", "069620")])

    assert "삼성" not in result
    assert "대웅" not in result


def test_여섯자리가_아닌_코드는_버린다():
    rows = [("정상", "005930"), ("다섯자리", "01234"), ("문자섞임", "00593A")]

    assert build_dict(rows) == {"정상": "005930"}


def test_한_글자_이름은_버린다():
    """추출기가 두 글자 미만을 어차피 건너뛴다. 사전에 남겨 둘 이유가 없다."""
    assert build_dict([("A", "005930"), ("정상", "000660")]) == {"정상": "000660"}


def test_앞뒤_공백을_제거한다():
    assert build_dict([("  효성  ", " 004800 ")]) == {"효성": "004800"}


def test_같은_이름이_두_번_오면_먼저_온_쪽을_남긴다():
    """stock_info 에 중복 이름은 없지만, 생기면 조용히 덮어쓰지 않는다."""
    result = build_dict([("중복", "005930"), ("중복", "000660")])

    assert result == {"중복": "005930"}


# --------------------------------------------------------------------------
# 파일 렌더링 — 산출물은 커밋되는 정적 모듈이다
# --------------------------------------------------------------------------

from scripts.build_stock_dict import render_module


def test_렌더링한_모듈을_실행하면_같은_사전이_나온다():
    mapping = {"삼성전자": "005930", "F&F": "383220"}

    namespace = {}
    exec(render_module(mapping, source="stock_info@2026-02-10"), namespace)

    assert namespace["EXTENDED_STOCK_CODES"] == mapping


def test_따옴표가_든_이름도_깨지지_않는다():
    """'CJ4우(전환)' 같은 이름이 실제로 있다. 이스케이프가 필요하다."""
    mapping = {"AB'C": "005930", 'X"Y': "000660"}

    namespace = {}
    exec(render_module(mapping, source="t"), namespace)

    assert namespace["EXTENDED_STOCK_CODES"] == mapping


def test_출처를_파일에_남긴다():
    """이 파일이 어디서 왔는지 모르면 다음 사람이 또 네이버를 긁는다."""
    text = render_module({"삼성전자": "005930"}, source="stock_info@2026-02-10")

    assert "stock_info@2026-02-10" in text


def test_이름순으로_정렬해_diff_가_읽히게_한다():
    text = render_module({"나": "000660", "가": "005930"}, source="t")

    assert text.index("'가'") < text.index("'나'")


# --------------------------------------------------------------------------
# 실 DB 왕복 — stock_info 를 실제로 읽는다
# --------------------------------------------------------------------------

from scripts.build_stock_dict import load_stock_info_rows


@pytest.mark.db
def test_stock_info_에서_상장종목을_읽어온다(db):
    rows = load_stock_info_rows(db)

    mapping = build_dict(rows)
    assert len(mapping) > 2000, f"stock_info 가 비었거나 표가 바뀌었다: {len(mapping)}개"
    # 절단 별칭이 덮어써서 사라졌던 종목들 — 권위 표에는 정확히 있다
    assert mapping["F&F"] == "383220"
    assert mapping["컴투스"] == "078340"
    assert mapping["대상"] == "001680"
    assert mapping["골프존"] == "215000"
