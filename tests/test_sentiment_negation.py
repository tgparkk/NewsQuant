"""한국어 부정어 판정 테스트.

배경: 부정어 판정이 어절 내부를 부분문자열로 매칭해 긍정 문장을 뒤집었다.
실측(수정 전): '안정적 성장 지속' = -1.000, '미국 수출 증가' = -1.000.
'안'·'미'·'불' 한 글자가 뒤 어절의 감성을 반전시킨 결과다.
"""
import pytest

from news_scraper.sentiment_analyzer import SentimentAnalyzer


@pytest.fixture
def analyzer():
    return SentimentAnalyzer()


def score(analyzer, text):
    return analyzer.calculate_sentiment_score(text)


# ---------------------------------------------------------------- 사전 전제
# 아래 테스트가 쓰는 키워드가 실제 사전에 있는지 먼저 못박는다.
# 사전이 바뀌면 문장이 아니라 이 테스트가 먼저 깨져야 한다.

def test_used_keywords_exist_in_dictionaries():
    for kw in ('목표가 상향', '실적 개선', '개선', '성장', '증가', '매출 증가'):
        assert kw in SentimentAnalyzer.POSITIVE_KEYWORDS, kw
    for kw in ('불확실성', '감소', '매출 감소'):
        assert kw in SentimentAnalyzer.NEGATIVE_KEYWORDS, kw


# ---------------------------------------------------------------- 회귀 (핵심)

def test_stable_growth_is_positive(analyzer):
    """'안'정적 이 '성장' 을 반전시키면 안 된다 (수정 전 -1.000)."""
    assert score(analyzer, '안정적 성장 지속') > 0


def test_us_export_increase_is_positive(analyzer):
    """'미'국 이 '증가' 를 반전시키면 안 된다 (수정 전 -1.000)."""
    assert score(analyzer, '미국 수출 증가') > 0


def test_uncertainty_does_not_swallow_increase(analyzer):
    """'불'확실성 이 '증가' 를 반전시키면 안 된다 (수정 전 -1.000).

    '불확실성' 은 그 자체로 부정 키워드라 총점이 낮아질 수는 있으나,
    '증가' 가 죽어 최대 부정으로 몰리는 것은 버그다.
    """
    positive = score(analyzer, '불확실성 속 매출 증가')
    negative = score(analyzer, '불확실성 속 매출 감소')
    assert positive > -1.0
    assert positive > negative  # '증가' 가 여전히 점수에 기여한다


# ---------------------------------------------------------------- 진짜 부정은 유지

def test_exact_negation_an_still_flips(analyzer):
    """'안' 단독 부사는 여전히 뒤 키워드를 반전시킨다."""
    assert score(analyzer, '안 목표가 상향') < score(analyzer, '목표가 상향')
    assert score(analyzer, '안 목표가 상향') < 0


def test_exact_negation_mot_still_flips(analyzer):
    """'못' 단독 부사는 여전히 뒤 키워드를 반전시킨다."""
    assert score(analyzer, '못 미친 성장') < score(analyzer, '성장')
    assert score(analyzer, '못 미친 성장') < 0


def test_partial_negation_anh_still_flips(analyzer):
    """'않' 은 활용형 어절 내부에 붙으므로 부분문자열 매칭을 유지한다."""
    assert score(analyzer, '않는 실적 개선') < score(analyzer, '실적 개선')
    assert score(analyzer, '않는 실적 개선') < 0


def test_partial_negation_eops_still_flips(analyzer):
    """'없' 도 활용형 어절 내부에 붙으므로 부분문자열 매칭을 유지한다."""
    assert score(analyzer, '차별화 없는 성장') < score(analyzer, '차별화 성장')
    assert score(analyzer, '차별화 없는 성장') < 0


# ---------------------------------------------------------------- 목록 구성

def test_single_char_prefixes_removed_from_negation_lists():
    """'불'·'미' 는 뒤 단어를 부정하는 부정어가 아니라 자기 단어의 접두사다."""
    assert '불' not in SentimentAnalyzer.NEGATION_WORDS_EXACT
    assert '미' not in SentimentAnalyzer.NEGATION_WORDS_EXACT
    assert '불' not in SentimentAnalyzer.NEGATION_WORDS_PARTIAL
    assert '미' not in SentimentAnalyzer.NEGATION_WORDS_PARTIAL


def test_exact_list_holds_only_standalone_adverbs():
    assert set(SentimentAnalyzer.NEGATION_WORDS_EXACT) == {'안', '못'}


def test_prefix_negatives_are_their_own_keywords():
    """'불'·'미' 를 빼도 부정 정보가 소실되지 않도록 자기 항목으로 존재한다."""
    for kw in ('불확실성', '불가능', '미달', '미흡'):
        assert kw in SentimentAnalyzer.NEGATIVE_KEYWORDS, kw


# ---------------------------------------------------------------- 어절 경계 단위

@pytest.mark.parametrize('text, keyword', [
    ('안정적 성장 지속', '성장'),
    ('미국 수출 증가', '증가'),
    ('불꽃 성장 기대', '성장'),
    ('미래 성장 동력', '성장'),
    ('안정 기조 상승', '상승'),
    ('불확실성 속 매출 증가', '매출 증가'),
])
def test_check_negation_respects_word_boundary(analyzer, text, keyword):
    pos = text.find(keyword)
    assert pos != -1
    assert analyzer._check_negation(text, keyword, pos) is False


@pytest.mark.parametrize('text, keyword', [
    ('안 목표가 상향', '목표가 상향'),
    ('못 미친 성장', '성장'),
    ('않는 실적 개선', '실적 개선'),
    ('차별화 없는 성장', '성장'),
])
def test_check_negation_still_detects_real_negation(analyzer, text, keyword):
    pos = text.find(keyword)
    assert pos != -1
    assert analyzer._check_negation(text, keyword, pos) is True
