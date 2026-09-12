"""일상어와 겹치는 종목명은 «단독 등장»만으로 잡지 않는다.

사전을 stock_info 로 바꾸면서 `대상`(001680)·`전방`(000950)·`태양`(053620)
같은 이름이 들어왔다. 이들은 진짜 상장사지만 기사에서는 대개 회사가 아니다.
같은 코퍼스 4,000건에 구·신 사전을 돌려 실측한 결과, 추가된 매칭 583건 중
384건이 `대상` 하나였고 표본은 전부 "고객을 대상으로" 류였다.

그래서 사전에서 빼는 대신 «증거 요구 등급»을 올린다. 아래 이름들은 종목코드가
함께 있을 때만(규칙1·2·4) 인정한다 — 단독 등장(규칙3)은 물론이고 종목 키워드
(규칙5)도 방증으로 치지 않는다. 키워드가 하필 '기업'·'종목'·'주식'이라
"관리종목 지정 대상 기업" 같은 문장이 그대로 통과했기 때문이다.

명단의 각 항목은 실제 오탐 문장으로 고정한다 — 근거 없이 명단이 불어나는
것을 막는 쪽이다.
"""
import pytest

from news_scraper.base_crawler import AMBIGUOUS_NAMES, STOCK_NAME_TO_CODE, BaseCrawler


class StubCrawler(BaseCrawler):
    def crawl_news_list(self, max_pages: int = 5):
        return []

    def crawl_news_detail(self, url: str):
        return None


@pytest.fixture(scope="module")
def crawler():
    return StubCrawler("test")


# 실제 코퍼스에서 뽑은 오탐 문장 — 여기에 종목이 붙으면 안 된다
FALSE_POSITIVES = [
    ("대상", "001680", "국내주식 매수 고객을 대상으로 경품 혜택을 제공하는 이벤트"),
    ("NEW", "160550", "HD현대마린엔진은 JIANGSU NEW YANGZI SHIPBUILDING 과 계약했다"),
    ("DSR", "155660", "총부채원리금상환비율(DSR) 규제와 주택담보대출 한도 축소"),
    ("코디", "080530", "남친이 골라준 출근룩 코디 영상의 비밀"),
    ("전방", "000950", "북미 전방 산업 회복에 따른 리테일 수요 증가"),
    ("흥국", "010240", "흥국證 “롯데지주, 관계사 실적 부진”"),
    ("삼기", "122350", "해외 커머스 확대의 교두보로 삼기 위해 인수를 단행했다"),
    ("노브랜드", "145170", "정용진 회장이 노브랜드 간편식 매장에서 상품을 살피고 있다"),
    ("태양", "053620", "그룹 빅뱅 소속 가수 태양과 배우 이병헌이 출연한다"),
    ("하츠", "066130", "3개의 하트 모티브가 세팅된 헤일로 하츠 컬렉션도 선보인다"),
    ("엔케이", "085310", "세라젬이 출시한 ‘셀루닉 엔케이 액티베이터’는 면역세포 배양액을 담았다"),
    ("미래산업", "025560", "창원시와 함께 ‘미래산업 전략 심포지엄’을 열고 성과를 공유했다"),
]


@pytest.mark.parametrize("name,code,text", FALSE_POSITIVES, ids=[f[0] for f in FALSE_POSITIVES])
def test_일상어_문맥에서는_종목으로_잡지_않는다(crawler, name, code, text):
    assert STOCK_NAME_TO_CODE.get(name) == code, f"{name} 이 사전에서 빠졌거나 코드가 바뀌었다"

    assert code not in crawler.extract_stock_codes(text).split(",")


@pytest.mark.parametrize("name,code,text", FALSE_POSITIVES, ids=[f[0] for f in FALSE_POSITIVES])
def test_명단의_이름은_코드가_붙으면_잡는다(crawler, name, code, text):
    """등급을 올린 것이지 사전에서 뺀 것이 아니다."""
    assert code in crawler.extract_stock_codes(f"{name}({code}) 이 상승했다").split(",")


def test_명단의_이름은_키워드만으로는_잡지_않는다(crawler):
    """'대상 기업'·'대상 종목'은 한국어에서 너무 흔하다.

    규칙5(이름+종목키워드)의 키워드가 하필 '기업'·'종목'·'주식'이라, 일상어와
    겹치는 이름에는 방증 구실을 못 한다. 실제 코퍼스에서 '관리종목 지정 대상
    기업', '처분 대상 주식' 이 그대로 통과했다. 명단의 이름은 코드가 있을
    때만 인정한다.
    """
    assert "001680" not in crawler.extract_stock_codes("관리종목 지정 대상 기업 149개사").split(",")
    assert "001680" not in crawler.extract_stock_codes("처분 대상 주식의 가격은 주당 1만1210원").split(",")


def test_명단에_없는_이름은_단독_등장만으로_잡는다(crawler):
    """등급 상향이 멀쩡한 종목까지 삼키면 안 된다."""
    assert "222800" in crawler.extract_stock_codes("리노공업 -4.18%, 심텍 -2.02% 등이다").split(",")
    assert "028300" in crawler.extract_stock_codes("레인보우로보틱스, HLB, 주성엔지니어링 등이 내렸다").split(",")


def test_명단은_전부_사전에_있는_이름이다():
    """오타나 상장폐지로 죽은 항목이 명단에 남아 조용히 무효가 되는 것을 막는다."""
    dangling = sorted(n for n in AMBIGUOUS_NAMES if n not in STOCK_NAME_TO_CODE)

    assert not dangling, f"사전에 없는 이름이 명단에 있다: {dangling}"
