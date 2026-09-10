"""extract_stock_codes 의 동작 고정 + 성능 상한.

기사 1건당 수백 ms 가 걸리면 사이클당 수백 건을 처리하는 크롤러의
시간 예산이 네트워크가 아니라 CPU 로 소진된다. 최적화하되 «추출 결과는
한 글자도 달라지지 않아야» 하므로, 실제 기사 440건으로 출력을 고정한다.
"""
import json
import time
from pathlib import Path

import pytest

from news_scraper.base_crawler import BaseCrawler

GOLDEN = Path(__file__).parent / "fixtures" / "stock_extraction_golden.json"


class StubCrawler(BaseCrawler):
    def crawl_news_list(self, max_pages: int = 5):
        return []

    def crawl_news_detail(self, url: str):
        return None


@pytest.fixture(scope="module")
def crawler():
    return StubCrawler("test")


@pytest.fixture(scope="module")
def golden():
    cases = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert cases, "골든 픽스처가 비었다"
    return cases


# --------------------------------------------------------------------------
# 동작 고정 - 최적화가 결과를 바꾸지 않았음을 실제 기사로 증명한다
# --------------------------------------------------------------------------

def test_실제_기사_440건의_추출_결과가_이전과_같다(crawler, golden):
    mismatches = []
    for case in golden:
        actual = crawler.extract_stock_codes(case["text"])
        if actual != case["expected"]:
            mismatches.append((case["text"][:70], case["expected"], actual))

    assert not mismatches, f"{len(mismatches)}건 불일치: {mismatches[:3]}"


def test_골든_픽스처에_종목이_추출된_사례가_충분히_들어있다(golden):
    """전부 빈 문자열이면 위 테스트가 아무것도 지키지 못한다."""
    nonempty = [c for c in golden if c["expected"]]

    assert len(nonempty) >= 50


# --------------------------------------------------------------------------
# 개별 동작
# --------------------------------------------------------------------------

def test_괄호_안_종목코드를_뽑는다(crawler):
    assert "005930" in crawler.extract_stock_codes("삼성전자(005930) 실적 발표")


def test_종목명만_있어도_뽑는다(crawler):
    assert "000660" in crawler.extract_stock_codes("SK하이닉스 반도체 업황 개선")


def test_여러_종목을_모두_뽑는다(crawler):
    codes = crawler.extract_stock_codes("삼성전자, SK하이닉스 동반 상승")

    assert {"005930", "000660"} <= set(codes.split(","))


def test_조사가_붙은_종목명은_현재_놓친다(crawler):
    """기존 동작을 고정한다. 섹션3 패턴이 종목명 뒤에 공백/문장부호를 요구해
    '삼성전자와' 처럼 조사가 붙으면 매칭되지 않는다. 별도 과제."""
    codes = crawler.extract_stock_codes("삼성전자와 SK하이닉스 동반 상승")

    assert "005930" not in codes.split(",")


def test_빈_텍스트는_빈_문자열을_돌려준다(crawler):
    assert crawler.extract_stock_codes("") == ""


def test_종목이_없으면_빈_문자열을_돌려준다(crawler):
    assert crawler.extract_stock_codes("오늘 날씨가 매우 맑습니다") == ""


def test_결과는_쉼표로_이어진_문자열이다(crawler):
    result = crawler.extract_stock_codes("삼성전자(005930) 실적")

    assert isinstance(result, str)
    assert " " not in result


# --------------------------------------------------------------------------
# 성능 상한 - 사이클당 수백 건을 예산 안에 처리해야 한다
# --------------------------------------------------------------------------

PERF_TEXT = (
    "삼성전자 4분기 실적 전망, SK하이닉스(000660) 반도체 업황 개선 기대. "
    "현대차와 기아는 미국 관세 영향으로 하락했고 LG에너지솔루션은 반등했다. "
) * 5


def test_기사_한_건_추출이_20ms_미만이다(crawler):
    """574ms 였다. 300건이면 172초 - 240초 예산의 72% 를 CPU 로 태운다."""
    crawler.extract_stock_codes(PERF_TEXT)  # 워밍업 (최초 컴파일 제외)

    started = time.perf_counter()
    for _ in range(10):
        crawler.extract_stock_codes(PERF_TEXT)
    per_call = (time.perf_counter() - started) / 10

    assert per_call < 0.020, f"1건당 {per_call * 1000:.0f}ms"


def test_기사_300건_추출이_10초_미만이다(crawler, golden):
    texts = [c["text"] for c in golden][:300]
    crawler.extract_stock_codes(texts[0])  # 워밍업

    started = time.perf_counter()
    for text in texts:
        crawler.extract_stock_codes(text)
    elapsed = time.perf_counter() - started

    assert elapsed < 10.0, f"{len(texts)}건에 {elapsed:.1f}초"
