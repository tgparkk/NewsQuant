"""
영문 뉴스 감성 분석 모듈
글로벌 금융 뉴스에 대한 영어 키워드 기반 감성 분석

한국 시장(KOSPI/KOSDAQ)에 미치는 영향을 중심으로 분석
"""

import re
from datetime import datetime
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class EnglishSentimentAnalyzer:
    """영문 뉴스 감성 분석기 (한국 시장 영향 기준)"""

    # ─── 긍정 키워드 (시장 상승 기대) ───────────────────────
    POSITIVE_KEYWORDS = [
        # 시장 상승
        'rally', 'surge', 'soar', 'gain', 'rise', 'climb', 'jump',
        'advance', 'rebound', 'recover', 'upturn', 'bull', 'bullish',
        'record high', 'all-time high', 'outperform', 'beat expectations',
        # 경제 호조
        'growth', 'expansion', 'boom', 'strong economy', 'robust',
        'upbeat', 'optimistic', 'confidence', 'positive outlook',
        'better than expected', 'exceed forecast', 'above estimate',
        # 통화/금리 완화
        'rate cut', 'dovish', 'easing', 'stimulus', 'quantitative easing',
        'accommodative', 'inject liquidity', 'lower rates',
        'rate reduction', 'policy support',
        # 기업 실적
        'earnings beat', 'revenue growth', 'profit increase', 'strong results',
        'guidance raised', 'upgrade', 'buy rating', 'outperform rating',
        'dividend increase', 'buyback', 'share repurchase',
        # 무역/외교
        'trade deal', 'trade agreement', 'tariff reduction', 'tariff relief',
        'trade talks progress', 'diplomatic breakthrough',
        'sanctions lifted', 'export growth',
        # 기술/산업
        'breakthrough', 'innovation', 'launch', 'partnership',
        'contract win', 'order', 'demand surge', 'supply shortage',
        'chip demand', 'ai demand', 'semiconductor boom',
    ]

    # ─── 부정 키워드 (시장 하락 우려) ───────────────────────
    NEGATIVE_KEYWORDS = [
        # 시장 하락
        'crash', 'plunge', 'plummet', 'tumble', 'drop', 'fall', 'decline',
        'sell-off', 'selloff', 'bear', 'bearish', 'correction',
        'slump', 'collapse', 'downturn', 'meltdown', 'rout',
        'worst day', 'lowest', 'underperform', 'miss expectations',
        # 경제 악화
        'recession', 'contraction', 'slowdown', 'stagnation',
        'weak economy', 'pessimistic', 'uncertainty', 'risk',
        'worse than expected', 'below estimate', 'miss forecast',
        'downgrade', 'warning', 'alarm',
        # 통화/금리 긴축
        'rate hike', 'hawkish', 'tightening', 'tapering',
        'higher rates', 'rate increase', 'restrictive',
        'inflation surge', 'inflation fear', 'stagflation',
        # 기업 부정
        'earnings miss', 'revenue decline', 'profit warning',
        'guidance lowered', 'downgrade', 'sell rating',
        'layoff', 'restructuring', 'bankruptcy', 'default',
        # 무역/외교 갈등
        'trade war', 'tariff hike', 'new tariff', 'tariff threat',
        'sanctions', 'export ban', 'import restriction',
        'trade tension', 'retaliation', 'embargo', 'blacklist',
        'protectionism', 'decoupling',
        # 지정학적 리스크
        'war', 'conflict', 'military', 'missile', 'nuclear',
        'invasion', 'attack', 'escalation', 'geopolitical risk',
        'crisis', 'emergency', 'pandemic', 'outbreak',
        # 공급망
        'supply chain disruption', 'shortage', 'bottleneck',
        'chip shortage', 'supply constraint',
    ]

    # ─── 강력한 키워드 (가중치 높음) ────────────────────────
    STRONG_POSITIVE = [
        'record high', 'massive rally', 'trade deal reached',
        'rate cut announced', 'stimulus package', 'ai boom',
        'semiconductor supercycle', 'earnings surge',
    ]

    STRONG_NEGATIVE = [
        'crash', 'collapse', 'circuit breaker', 'black monday',
        'trade war escalation', 'recession confirmed', 'default',
        'sanctions imposed', 'market meltdown', 'panic selling',
        'tariff war', 'global crisis',
    ]

    # ─── 부정어 (극성 반전) ─────────────────────────────────
    NEGATION_WORDS = [
        'not', 'no', "n't", 'never', 'neither', 'nor',
        'without', 'despite', 'fails to', 'failed to',
        'unlikely', 'avoid', 'halt', 'pause', 'delay',
    ]

    NEGATION_WINDOW = 3  # 부정어 윈도우 (어절)

    # ─── 한국 영향 카테고리별 가중치 ────────────────────────
    CATEGORY_KOREA_WEIGHT = {
        'asia_market': 1.0,       # 아시아 시장 뉴스 → 직접 영향
        'trade_policy': 0.95,     # 무역/관세 → 수출 의존 경제
        'technology': 0.9,        # 기술/반도체 → 한국 주력 산업
        'us_market': 0.85,        # 미국 시장 → KOSPI 선행지표
        'global_market': 0.8,     # 글로벌 시장
        'energy': 0.7,            # 에너지 → 간접 영향
    }

    # ─── 출처별 신뢰도 ──────────────────────────────────────
    SOURCE_CREDIBILITY = {
        'cnbc': 0.9,
        'marketwatch': 0.85,
        'investing_com': 0.8,
        'google_news_finance': 0.75,
        'google_news_asia': 0.8,
        'google_news_trade': 0.75,
        'google_news_tech': 0.75,
    }

    def _check_negation(self, words: List[str], keyword_idx: int) -> bool:
        """키워드 앞에 부정어가 있는지 확인"""
        start = max(0, keyword_idx - self.NEGATION_WINDOW)
        for i in range(start, keyword_idx):
            word = words[i].lower()
            for neg in self.NEGATION_WORDS:
                if neg in word or word.endswith("n't"):
                    return True
        return False

    def calculate_sentiment_score(self, text: str) -> float:
        """
        영문 감성 점수 계산 (-1.0 ~ +1.0)

        Args:
            text: 분석할 영문 텍스트

        Returns:
            감성 점수 (-1.0: 매우 부정, 0.0: 중립, +1.0: 매우 긍정)
        """
        if not text:
            return 0.0

        text_lower = text.lower()
        words = text_lower.split()

        # 긍정/부정 키워드 카운트 (부정어 고려)
        positive_count = 0
        negative_count = 0

        for keyword in self.POSITIVE_KEYWORDS:
            kw_words = keyword.split()
            for i in range(len(words) - len(kw_words) + 1):
                if ' '.join(words[i:i + len(kw_words)]) == keyword:
                    if self._check_negation(words, i):
                        negative_count += 1  # 부정어로 반전
                    else:
                        positive_count += 1

        for keyword in self.NEGATIVE_KEYWORDS:
            kw_words = keyword.split()
            for i in range(len(words) - len(kw_words) + 1):
                if ' '.join(words[i:i + len(kw_words)]) == keyword:
                    if self._check_negation(words, i):
                        positive_count += 1  # 부정어로 반전
                    else:
                        negative_count += 1

        # 강력한 키워드 보너스
        strong_pos = sum(1 for kw in self.STRONG_POSITIVE if kw in text_lower)
        strong_neg = sum(1 for kw in self.STRONG_NEGATIVE if kw in text_lower)
        positive_count += strong_pos * 2
        negative_count += strong_neg * 2

        # 점수 계산
        total = positive_count + negative_count
        if total == 0:
            return 0.0

        score = (positive_count - negative_count) / max(total, 1)
        return max(-1.0, min(1.0, score))

    def calculate_importance_score(self, text: str, source: str, category: str) -> float:
        """중요도 점수 계산 (0.0 ~ 1.0)"""
        if not text:
            return 0.0

        text_lower = text.lower()

        # 중요 키워드
        importance_keywords = [
            'breaking', 'urgent', 'exclusive', 'alert',
            'federal reserve', 'fed decision', 'fomc',
            'gdp', 'cpi', 'jobs report', 'nonfarm',
            'earnings', 'ipo', 'merger', 'acquisition',
            'tariff', 'sanctions', 'trade deal',
            'crisis', 'war', 'pandemic',
        ]
        keyword_count = sum(1 for kw in importance_keywords if kw in text_lower)
        keyword_score = min(1.0, keyword_count * 0.2)

        # 출처 신뢰도
        source_score = self.SOURCE_CREDIBILITY.get(source, 0.6)

        # 카테고리 한국 영향 가중치
        category_weight = self.CATEGORY_KOREA_WEIGHT.get(category, 0.6)

        importance = keyword_score * 0.4 + source_score * 0.3 + category_weight * 0.3
        return min(1.0, importance)

    def calculate_korea_impact_score(self, text: str, category: str) -> float:
        """
        한국 시장 영향도 점수 (0.0 ~ 1.0)
        해당 뉴스가 KOSPI/KOSDAQ에 얼마나 직접적인 영향을 주는지 평가
        """
        if not text:
            return 0.0

        text_lower = text.lower()

        # 직접적 한국 관련 키워드
        direct_keywords = [
            'korea', 'kospi', 'kosdaq', 'samsung', 'hyundai', 'sk hynix',
            'lg', 'kia', 'posco', 'korean won', 'bank of korea',
        ]
        direct_count = sum(1 for kw in direct_keywords if kw in text_lower)

        # 간접적 한국 영향 키워드
        indirect_keywords = [
            'semiconductor', 'chip', 'memory', 'dram', 'nand',
            'asia market', 'asian stocks', 'emerging market',
            'trade war', 'tariff', 'china trade',
            'oil price', 'dollar', 'treasury yield',
            'fed', 'rate cut', 'rate hike',
        ]
        indirect_count = sum(1 for kw in indirect_keywords if kw in text_lower)

        # 카테고리 가중치
        cat_weight = self.CATEGORY_KOREA_WEIGHT.get(category, 0.5)

        direct_score = min(1.0, direct_count * 0.3)
        indirect_score = min(1.0, indirect_count * 0.15)

        impact = direct_score * 0.5 + indirect_score * 0.3 + cat_weight * 0.2
        return min(1.0, impact)

    def analyze_news(self, news_data: Dict) -> Dict:
        """
        영문 뉴스 분석 및 점수 계산

        Args:
            news_data: 뉴스 데이터

        Returns:
            분석 점수가 추가된 뉴스 데이터
        """
        title = news_data.get('title', '')
        content = news_data.get('content', '')
        source = news_data.get('source', '')
        category = news_data.get('category', '')

        # 제목 70% + 본문 30% 감성 분석
        title_sentiment = self.calculate_sentiment_score(title)
        content_sentiment = self.calculate_sentiment_score(content)
        sentiment = title_sentiment * 0.7 + content_sentiment * 0.3

        # 강력한 키워드 보너스
        text = f"{title} {content}".lower()
        if any(kw in text for kw in self.STRONG_POSITIVE):
            sentiment = min(1.0, sentiment + 0.2)
        if any(kw in text for kw in self.STRONG_NEGATIVE):
            sentiment = max(-1.0, sentiment - 0.2)

        # 중요도
        importance = self.calculate_importance_score(f"{title} {content}", source, category)

        # 한국 영향도
        korea_impact = self.calculate_korea_impact_score(f"{title} {content}", category)

        # 실시간성
        timeliness = self._calculate_timeliness(news_data.get('published_at', ''))

        # 종합 점수 (한국 영향도 가중)
        # 한국 영향도가 높을수록 감성 점수 비중 증가
        overall_score = (
            sentiment * (0.3 + korea_impact * 0.2) +
            importance * 0.25 +
            korea_impact * 0.15 +
            timeliness * 0.1
        )

        news_data['sentiment_score'] = round(sentiment, 3)
        news_data['importance_score'] = round(importance, 3)
        news_data['impact_score'] = round(korea_impact, 3)
        news_data['timeliness_score'] = round(timeliness, 3)
        news_data['overall_score'] = round(overall_score, 3)

        return news_data

    def _calculate_timeliness(self, published_at: str) -> float:
        """실시간성 점수 계산"""
        try:
            if not published_at:
                return 0.5

            if 'T' in published_at:
                pub_time = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            else:
                return 0.5

            now = datetime.now(pub_time.tzinfo) if pub_time.tzinfo else datetime.now()
            hours_diff = abs((now - pub_time).total_seconds() / 3600)

            if hours_diff <= 6:
                return 1.0  # 6시간 이내
            elif hours_diff <= 24:
                return 0.8
            elif hours_diff <= 48:
                return 0.5
            else:
                return 0.2
        except Exception:
            return 0.5
