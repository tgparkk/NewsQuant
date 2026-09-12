"""extract_stock_codes 의 회귀 방지 + 정밀도 불변식 + 성능 상한.

골든 픽스처(실제 기사 440건)는 원래 «성능 최적화가 결과를 바꾸지 않았음»을
증명하려고 만들었다. 그런데 그렇게 고정한 결과 자체가 틀려 있었다 - 추출
상위 5개 코드가 전부 오탐이었고, 그래서 한 번은 의도적으로 다시 떴다.

    제거 44건 (전부 오탐) / 추가 68건 (조사·가운뎃점·괄호 때문에 놓치던 양성)
    종목이 붙은 기사 85 -> 62건

그래서 픽스처만으로는 부족하다. 아래 «정밀도» 절의 개별 오탐 테스트와
«사전 불변식» 절이 픽스처가 다시 틀린 값으로 굳는 것을 막는 쪽이다.
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
# 회귀 방지 - 실제 기사로 출력 전체를 고정한다
# --------------------------------------------------------------------------

def test_실제_기사_440건의_추출_결과가_픽스처와_같다(crawler, golden):
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


def test_조사가_붙은_종목명도_잡는다(crawler):
    """한국어는 단어 경계가 안 먹어 종목명 뒤에 공백/문장부호를 요구했고, 그래서
    '삼성전자와' 를 놓쳤다. with_keyword 가 공백 0개를 허용해 '미래에셋'+'증권' 을
    붙여 읽으면서 «우연히» 가려주던 구멍이다."""
    codes = crawler.extract_stock_codes("삼성전자와 SK하이닉스 동반 상승").split(",")

    assert {"005930", "000660"} <= set(codes)


def test_조사가_붙은_증권사명도_잡는다(crawler):
    codes = crawler.extract_stock_codes("10일 미래에셋증권에 따르면 순매수 상위 종목은").split(",")

    assert "006800" in codes


def test_조사가_붙은_은행명도_잡는다(crawler):
    """"우리은행은 금리를 올렸다" 는 사진 캡션이 아니라 진짜 은행 기사다."""
    codes = crawler.extract_stock_codes("우리은행은 10일 대표 정기예금 금리를 인상했다").split(",")

    assert "316140" in codes


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


# --------------------------------------------------------------------------
# 정밀도 - 실측된 오탐 (골든 440건 상위 5개 코드가 전부 오탐이었다)
# --------------------------------------------------------------------------

def test_조사_대상_은_대상홀딩스가_아니다(crawler):
    """'대상홀딩스'에서 접미사를 잘라 만든 별칭 '대상'이 일상어와 충돌했다."""
    codes = crawler.extract_stock_codes(
        "DAXA는 조사 대상 정보의 범위와 기준시점, 회신 항목을 안내했다"
    ).split(",")

    assert "084690" not in codes


def test_매일_반복을_뜻하는_매일은_매일홀딩스가_아니다(crawler):
    codes = crawler.extract_stock_codes(
        "선물세트를 최대 70% 할인 판매한다. 매일 '100% 당첨 룰렛' 행사를 연다"
    ).split(",")

    assert "005990" not in codes


def test_하나증권은_하나제약으로_오인하지_않는다(crawler):
    """with_keyword 가 공백 0개를 허용해 '하나'+'증권'이 붙어서 매칭됐다."""
    codes = crawler.extract_stock_codes("박승진 하나증권 연구원은 양면성을 짚었다").split(",")

    assert "293480" not in codes


def test_영문_SK_Hynix_는_SK주식회사가_아니다(crawler):
    codes = crawler.extract_stock_codes(
        "Samsung, SK Hynix rally as chip demand rebounds"
    ).split(",")

    assert "034730" not in codes


def test_사진_캡션의_하나은행_딜링룸은_종목_귀속에서_제외한다(crawler):
    """시황 기사마다 붙는 사진 캡션 탓에 코스피 기사가 하나금융지주 기사가 됐다."""
    codes = crawler.extract_stock_codes(
        "코스피 7000선 턱걸이 마감 서울 중구 하나은행 본점 딜링룸 전광판에 "
        "증시 종가가 표시되고 있다. [연합뉴스]"
    ).split(",")

    assert "086790" not in codes


def test_우리은행_딜링룸_캡션도_마찬가지다(crawler):
    codes = crawler.extract_stock_codes(
        "박정호 기자 = 12일 오후 서울 중구 우리은행 본점 딜링룸 전광판에 코스피지수 종가가 표시됐다"
    ).split(",")

    assert "316140" not in codes


# --------------------------------------------------------------------------
# 사전 불변식 - 손으로 적은 매핑에 날조가 섞여 있었다
# --------------------------------------------------------------------------

def test_모든_종목코드는_6자리_숫자다():
    """'쿠팡': 'CPNG' 처럼 국내 코드가 아닌 값이 섞여 있었다."""
    from news_scraper.base_crawler import STOCK_NAME_TO_CODE

    bad = {n: c for n, c in STOCK_NAME_TO_CODE.items() if not (len(c) == 6 and c.isdigit())}

    assert not bad, f"6자리 숫자가 아닌 코드: {list(bad.items())[:10]}"


def test_비상장_회사는_사전에_없다():
    """삼성디스플레이→034730(SK주식회사), 배달의민족→035720(카카오) 는 날조였다."""
    from news_scraper.base_crawler import STOCK_NAME_TO_CODE

    unlisted = ["삼성디스플레이", "배달의민족", "우아한형제들", "카카오모빌리티", "쿠팡"]

    assert not [n for n in unlisted if n in STOCK_NAME_TO_CODE]


def test_존재하지_않는_코드가_사전에_없다():
    """'카카오모빌리티'와 '한화에너지'가 둘 다 162025 로 적혀 있었다.
    162025 는 어느 시장에도 없는 코드다."""
    from news_scraper.base_crawler import STOCK_NAME_TO_CODE

    phantom = {n: c for n, c in STOCK_NAME_TO_CODE.items() if c == "162025"}

    assert not phantom, f"날조된 코드가 남아 있다: {phantom}"


def test_한화솔루션케미칼은_효성화학_코드를_쓰지_않는다():
    """비상장 자회사인데 298000(효성화학) 으로 적혀 있었다."""
    from news_scraper.base_crawler import STOCK_NAME_TO_CODE

    assert "한화솔루션케미칼" not in STOCK_NAME_TO_CODE
    assert STOCK_NAME_TO_CODE.get("효성화학") == "298000"


def test_접미사를_잘라_만든_별칭은_사전에_없다():
    """'대상홀딩스'→'대상', '매일홀딩스'→'매일', '하나제약'→'하나'."""
    from news_scraper.base_crawler import STOCK_NAME_TO_CODE

    leftovers = [
        n for n in ("대상", "매일", "하나", "광동", "경동", "가온")
        if n in STOCK_NAME_TO_CODE and STOCK_NAME_TO_CODE[n] in (
            "084690", "005990", "293480", "009290", "011040", "078890"
        )
    ]

    assert not leftovers, f"절단 별칭이 남아 있다: {leftovers}"


def test_ETF는_사전에_없다():
    """ETF 는 개별 종목 신호의 대상이 아니다."""
    from news_scraper.base_crawler import STOCK_NAME_TO_CODE

    etfs = [n for n in STOCK_NAME_TO_CODE if n.startswith(("KODEX", "TIGER", "ACE ", "1Q "))]

    assert not etfs, f"ETF {len(etfs)}개가 남아 있다: {etfs[:5]}"


@pytest.mark.db
def test_대웅_셀트리온제약_등은_stock_info_코드와_같다(db):
    """P1: '대웅'이 069620(대웅제약, «다른 회사»)으로, '셀트리온제약'이
    068270(셀트리온, «다른 회사»)으로 잘못 적혀 있었다 — 둘 다 실거래
    코드였기 때문에 조용히 다른 회사에 기사를 붙였다. stock_info 를
    권위 있는 소스로 보고 직접 대조한다."""
    from news_scraper.base_crawler import STOCK_NAME_TO_CODE_BASE

    names = ["대웅", "대웅제약", "셀트리온", "셀트리온제약"]
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT stock_name, stock_code FROM stock_info WHERE stock_name = ANY(%s)",
                (names,),
            )
            official = dict(cur.fetchall())
    finally:
        conn.rollback()
        db._put_connection(conn)

    assert official, "stock_info 조회 결과가 비었다 — 종목명 표기가 바뀌었을 수 있다"
    mismatches = {
        n: {"사전": STOCK_NAME_TO_CODE_BASE.get(n), "stock_info": official[n]}
        for n in names
        if n in official and STOCK_NAME_TO_CODE_BASE.get(n) != official[n]
    }
    assert not mismatches, f"stock_info 와 불일치: {mismatches}"


# --------------------------------------------------------------------------
# 정밀도를 높이면서 놓치면 안 되는 것들
# --------------------------------------------------------------------------

def test_정식명_대상홀딩스는_그대로_잡는다(crawler):
    assert "084690" in crawler.extract_stock_codes("대상홀딩스 3분기 실적 발표").split(",")


def test_하나금융지주는_그대로_잡는다(crawler):
    assert "086790" in crawler.extract_stock_codes("하나금융지주 배당 확대 검토").split(",")


def test_캡션이_아닌_본문의_하나은행은_그대로_잡는다(crawler):
    codes = crawler.extract_stock_codes("하나은행 3분기 순이익 1조원 기록").split(",")

    assert "086790" in codes


def test_종목명_뒤에_공백을_두고_붙은_키워드는_그대로_잡는다(crawler):
    assert "005930" in crawler.extract_stock_codes("삼성전자 주가 상승").split(",")


def test_골든_픽스처에_알려진_오탐_코드가_없다(golden):
    """픽스처는 한 번 «틀린 값으로» 굳은 적이 있다. 재생성할 때 실측된 오탐이
    슬그머니 돌아오지 않도록 코드 단위로 못 박는다.

    034730 SK(주)   - 영문 기사의 'SK Hynix'
    084690 대상홀딩스 - "조사 대상 정보"
    005990 매일홀딩스 - "매일 룰렛 행사"
    293480 하나제약   - "하나증권 연구원"
    """
    known_false_positives = {"034730", "084690", "005990", "293480"}

    hit = sorted({
        code
        for case in golden
        for code in case["expected"].split(",")
        if code in known_false_positives
    })

    assert not hit, f"오탐 코드가 픽스처에 돌아왔다: {hit}"


# --------------------------------------------------------------------------
# 경계 규칙 - 문장부호를 나열하다 빠뜨린 것들
# --------------------------------------------------------------------------

def test_가운뎃점으로_나열된_증권사를_모두_잡는다(crawler):
    """경계 문자를 손으로 나열하다 가운뎃점을 빠뜨려 나열을 통째로 놓쳤다."""
    codes = set(crawler.extract_stock_codes(
        "발행어음 시장은 미래에셋증권·한국투자증권·NH투자증권·KB증권으로 늘었다"
    ).split(","))

    assert {"006800", "006200", "005940"} <= codes


def test_괄호_안_등락률이_붙어도_잡는다(crawler):
    codes = set(crawler.extract_stock_codes(
        "시가총액 상위 종목 중 삼성물산(3.72%), SK스퀘어(2.89%)가 올랐다"
    ).split(","))

    assert {"028260", "402340"} <= codes


def test_더_긴_종목명이_짧은_종목명을_가린다(crawler):
    """'에코프로비엠'(247540) 기사가 '에코프로'(086520) 기사가 되면 안 된다."""
    codes = crawler.extract_stock_codes("에코프로비엠은 3.88% 하락했다").split(",")

    assert codes == ["247540"]


def test_조사처럼_보이는_단어의_첫머리는_조사가_아니다(crawler):
    """'아스트라'(오픈AI 모델) 를 '아스트'(067390)+'라는' 으로 쪼개면 안 된다."""
    codes = crawler.extract_stock_codes("GPT-6 아스트라는 초기 AGI 단계다").split(",")

    assert "067390" not in codes


def test_진짜_아스트는_잡는다(crawler):
    assert "067390" in crawler.extract_stock_codes("아스트는 항공부품을 납품했다").split(",")


def test_네이버_뉴스_페이지_상용구는_종목_귀속에서_제외한다(crawler):
    """크롤러가 페이지 장식을 함께 담아 와 기사 102건이 NAVER 기사가 됐다."""
    codes = crawler.extract_stock_codes(
        "댓글 운영 방식 및 운영규정에 따른 삭제나 이용제한 조치는 네이버가 직접 수행합니다"
    ).split(",")

    assert "035420" not in codes


def test_본문에_등장하는_네이버는_그대로_잡는다(crawler):
    assert "035420" in crawler.extract_stock_codes("네이버가 신규 AI 서비스를 출시했다").split(",")
