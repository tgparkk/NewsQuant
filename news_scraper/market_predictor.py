"""
시장 지수 예측 모듈
국내외 뉴스 감성 분석 기반 KOSPI/KOSDAQ 방향 예측

예측 방법론:
1. 글로벌 뉴스 감성 (미국 시장, 무역, 기술, 지정학)
2. 국내 뉴스 감성 (증시, 경제, 산업)
3. 시간대별 가중치 (장전/장중/장후)
4. 카테고리별 영향도 가중
"""

from datetime import datetime, timedelta, time as dt_time
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging

from .database import NewsDatabase

logger = logging.getLogger(__name__)


class MarketPredictor:
    """KOSPI/KOSDAQ 지수 방향 예측기"""

    # 글로벌 뉴스 카테고리별 한국 시장 영향 가중치
    GLOBAL_CATEGORY_WEIGHT = {
        'asia_market': 1.0,
        'trade_policy': 0.95,
        'technology': 0.9,
        'us_market': 0.85,
        'global_market': 0.8,
        'energy': 0.7,
    }

    # 국내 뉴스 카테고리별 지수 영향 가중치
    DOMESTIC_CATEGORY_WEIGHT = {
        '증시': 1.0,
        '금융시장': 1.0,
        '경제': 0.9,
        '산업': 0.7,
        '기술': 0.7,
        '국제': 0.8,
        '유통': 0.5,
    }

    # 글로벌 출처별 가중치
    GLOBAL_SOURCE_WEIGHT = {
        'cnbc': 1.0,
        'marketwatch': 0.95,
        'investing_com': 0.9,
        'google_news_finance': 0.8,
        'google_news_asia': 0.9,
        'google_news_trade': 0.85,
        'google_news_tech': 0.8,
    }

    # 국내 출처별 가중치
    DOMESTIC_SOURCE_WEIGHT = {
        'naver_finance': 0.9,
        'hankyung': 0.85,
        'mk_news': 0.85,
        'dart': 1.0,
    }

    def __init__(self, db_path: str = "news_data.db"):
        self.db = NewsDatabase(db_path)

    def _get_market_phase(self) -> str:
        """현재 시장 상태 반환"""
        import pytz
        now = datetime.now(pytz.timezone('Asia/Seoul'))

        if now.weekday() >= 5:
            return 'weekend'

        current_time = now.time()

        if current_time < dt_time(9, 0):
            return 'pre_market'     # 장전
        elif current_time <= dt_time(15, 30):
            return 'market_open'    # 장중
        else:
            return 'after_market'   # 장후

    def _get_phase_weights(self, phase: str) -> Dict[str, float]:
        """
        시간대별 국내/글로벌 뉴스 가중치

        장전: 글로벌 뉴스 비중 높음 (미국 장 마감 후, 아시아 장 개장 전)
        장중: 국내 뉴스 비중 높음
        장후: 글로벌 뉴스 비중 다시 증가
        """
        weights = {
            'pre_market':   {'global': 0.65, 'domestic': 0.35},
            'market_open':  {'global': 0.40, 'domestic': 0.60},
            'after_market': {'global': 0.55, 'domestic': 0.45},
            'weekend':      {'global': 0.50, 'domestic': 0.50},
        }
        return weights.get(phase, weights['market_open'])

    def _aggregate_news_sentiment(
        self,
        news_list: List[Dict],
        category_weights: Dict[str, float],
        source_weights: Dict[str, float],
    ) -> Dict:
        """뉴스 리스트의 가중 감성 점수 계산"""
        if not news_list:
            return {
                'weighted_sentiment': 0.0,
                'avg_sentiment': 0.0,
                'avg_overall': 0.0,
                'positive_count': 0,
                'negative_count': 0,
                'neutral_count': 0,
                'total_count': 0,
                'positive_ratio': 0.0,
                'category_breakdown': {},
            }

        total_weight = 0.0
        weighted_sentiment_sum = 0.0
        sentiment_scores = []
        overall_scores = []
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        category_sentiments = defaultdict(list)

        for news in news_list:
            sentiment = news.get('sentiment_score')
            overall = news.get('overall_score')
            category = news.get('category', '')
            source = news.get('source', '')

            if sentiment is None:
                continue

            # 가중치 계산
            cat_w = category_weights.get(category, 0.5)
            src_w = source_weights.get(source, 0.6)
            weight = cat_w * src_w

            weighted_sentiment_sum += sentiment * weight
            total_weight += weight
            sentiment_scores.append(sentiment)

            if overall is not None:
                overall_scores.append(overall)

            if sentiment > 0.05:
                positive_count += 1
            elif sentiment < -0.05:
                negative_count += 1
            else:
                neutral_count += 1

            category_sentiments[category].append(sentiment)

        total_count = len(sentiment_scores)
        weighted_sentiment = weighted_sentiment_sum / total_weight if total_weight > 0 else 0.0
        avg_sentiment = sum(sentiment_scores) / total_count if total_count > 0 else 0.0
        avg_overall = sum(overall_scores) / len(overall_scores) if overall_scores else 0.0

        # 카테고리별 평균 감성
        category_breakdown = {}
        for cat, scores in category_sentiments.items():
            category_breakdown[cat] = {
                'avg_sentiment': round(sum(scores) / len(scores), 3),
                'count': len(scores),
            }

        return {
            'weighted_sentiment': round(weighted_sentiment, 4),
            'avg_sentiment': round(avg_sentiment, 4),
            'avg_overall': round(avg_overall, 4),
            'positive_count': positive_count,
            'negative_count': negative_count,
            'neutral_count': neutral_count,
            'total_count': total_count,
            'positive_ratio': round(positive_count / total_count, 3) if total_count > 0 else 0.0,
            'category_breakdown': category_breakdown,
        }

    def _get_recent_news(self, hours: int = 24, source_filter: Optional[str] = None) -> List[Dict]:
        """최근 N시간 이내 뉴스 조회"""
        end_date = datetime.now()
        start_date = end_date - timedelta(hours=hours)

        return self.db.get_news_by_date_range(
            start_date.isoformat(),
            end_date.isoformat(),
            source=source_filter,
        )

    def _classify_news(self, news_list: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """뉴스를 글로벌/국내로 분류"""
        global_sources = set(self.GLOBAL_SOURCE_WEIGHT.keys())
        domestic_sources = set(self.DOMESTIC_SOURCE_WEIGHT.keys())

        global_news = []
        domestic_news = []

        for news in news_list:
            source = news.get('source', '')
            if source in global_sources:
                global_news.append(news)
            elif source in domestic_sources:
                domestic_news.append(news)
            else:
                # 언어로 판단
                lang = news.get('language', '')
                if lang == 'en':
                    global_news.append(news)
                else:
                    domestic_news.append(news)

        return global_news, domestic_news

    def predict_index(self, hours: int = 24) -> Dict:
        """
        KOSPI/KOSDAQ 지수 방향 예측

        Args:
            hours: 분석할 뉴스 시간 범위 (기본 24시간)

        Returns:
            예측 결과 딕셔너리
        """
        # 1. 뉴스 수집
        all_news = self._get_recent_news(hours=hours)

        if not all_news:
            return self._empty_prediction("최근 뉴스 데이터 없음")

        # 2. 글로벌/국내 분류
        global_news, domestic_news = self._classify_news(all_news)

        # 3. 각각 감성 집계
        global_sentiment = self._aggregate_news_sentiment(
            global_news,
            self.GLOBAL_CATEGORY_WEIGHT,
            self.GLOBAL_SOURCE_WEIGHT,
        )

        domestic_sentiment = self._aggregate_news_sentiment(
            domestic_news,
            self.DOMESTIC_CATEGORY_WEIGHT,
            self.DOMESTIC_SOURCE_WEIGHT,
        )

        # 4. 시간대별 가중치 적용
        phase = self._get_market_phase()
        phase_weights = self._get_phase_weights(phase)

        # 5. 종합 감성 점수
        g_weight = phase_weights['global']
        d_weight = phase_weights['domestic']

        # 글로벌 뉴스가 없으면 국내 뉴스만으로 예측
        if global_sentiment['total_count'] == 0:
            combined_sentiment = domestic_sentiment['weighted_sentiment']
            combined_overall = domestic_sentiment['avg_overall']
        elif domestic_sentiment['total_count'] == 0:
            combined_sentiment = global_sentiment['weighted_sentiment']
            combined_overall = global_sentiment['avg_overall']
        else:
            combined_sentiment = (
                global_sentiment['weighted_sentiment'] * g_weight +
                domestic_sentiment['weighted_sentiment'] * d_weight
            )
            combined_overall = (
                global_sentiment['avg_overall'] * g_weight +
                domestic_sentiment['avg_overall'] * d_weight
            )

        # 6. 방향 예측
        prediction = self._generate_prediction(
            combined_sentiment,
            combined_overall,
            global_sentiment,
            domestic_sentiment,
        )

        # 7. 신뢰도 계산
        confidence = self._calculate_confidence(
            combined_sentiment,
            global_sentiment,
            domestic_sentiment,
        )

        # 8. 핵심 요인 분석
        key_factors = self._analyze_key_factors(global_news, domestic_news)

        return {
            'prediction': prediction,
            'confidence': round(confidence, 3),
            'combined_sentiment': round(combined_sentiment, 4),
            'combined_overall': round(combined_overall, 4),
            'market_phase': phase,
            'phase_weights': phase_weights,
            'global_analysis': global_sentiment,
            'domestic_analysis': domestic_sentiment,
            'key_factors': key_factors,
            'total_news_analyzed': len(all_news),
            'analysis_hours': hours,
            'analysis_time': datetime.now().isoformat(),
        }

    def _generate_prediction(
        self,
        combined_sentiment: float,
        combined_overall: float,
        global_sent: Dict,
        domestic_sent: Dict,
    ) -> Dict:
        """방향 예측 생성"""
        # 감성 점수 기반 방향 판단
        if combined_sentiment > 0.15:
            direction = 'up'
            if combined_sentiment > 0.35:
                strength = 'strong'
                description = '강한 상승 예상'
            else:
                strength = 'moderate'
                description = '소폭 상승 예상'
        elif combined_sentiment < -0.15:
            direction = 'down'
            if combined_sentiment < -0.35:
                strength = 'strong'
                description = '강한 하락 예상'
            else:
                strength = 'moderate'
                description = '소폭 하락 예상'
        else:
            direction = 'neutral'
            strength = 'weak'
            description = '보합/혼조 예상'

        # 글로벌과 국내 방향이 다르면 혼조 표시
        g_dir = 'up' if global_sent['weighted_sentiment'] > 0.1 else ('down' if global_sent['weighted_sentiment'] < -0.1 else 'neutral')
        d_dir = 'up' if domestic_sent['weighted_sentiment'] > 0.1 else ('down' if domestic_sent['weighted_sentiment'] < -0.1 else 'neutral')

        if g_dir != d_dir and g_dir != 'neutral' and d_dir != 'neutral':
            mixed = True
            description += ' (글로벌/국내 엇갈림)'
        else:
            mixed = False

        return {
            'direction': direction,
            'strength': strength,
            'description': description,
            'mixed_signals': mixed,
            'global_direction': g_dir,
            'domestic_direction': d_dir,
        }

    def _calculate_confidence(
        self,
        combined_sentiment: float,
        global_sent: Dict,
        domestic_sent: Dict,
    ) -> float:
        """예측 신뢰도 계산 (0.0 ~ 1.0)"""
        # 기본 신뢰도: 감성 점수의 절대값
        base_confidence = min(1.0, abs(combined_sentiment) * 2)

        # 뉴스 볼륨 보너스
        total = global_sent['total_count'] + domestic_sent['total_count']
        volume_bonus = min(0.2, total / 100)  # 100개 이상이면 최대

        # 방향 일치 보너스
        g_dir = 1 if global_sent['weighted_sentiment'] > 0.05 else (-1 if global_sent['weighted_sentiment'] < -0.05 else 0)
        d_dir = 1 if domestic_sent['weighted_sentiment'] > 0.05 else (-1 if domestic_sent['weighted_sentiment'] < -0.05 else 0)

        if g_dir == d_dir and g_dir != 0:
            direction_bonus = 0.15  # 글로벌/국내 같은 방향
        elif g_dir != d_dir and g_dir != 0 and d_dir != 0:
            direction_bonus = -0.1  # 엇갈림 → 신뢰도 하락
        else:
            direction_bonus = 0.0

        # 긍정/부정 비율의 편향 보너스
        g_ratio = global_sent['positive_ratio']
        d_ratio = domestic_sent['positive_ratio']
        avg_ratio = (g_ratio + d_ratio) / 2 if (global_sent['total_count'] > 0 and domestic_sent['total_count'] > 0) else max(g_ratio, d_ratio)
        # 비율이 극단적(0.8 이상 또는 0.2 이하)이면 보너스
        ratio_bonus = 0.1 if (avg_ratio >= 0.8 or avg_ratio <= 0.2) else 0.0

        confidence = base_confidence + volume_bonus + direction_bonus + ratio_bonus
        return max(0.0, min(1.0, confidence))

    def _analyze_key_factors(
        self,
        global_news: List[Dict],
        domestic_news: List[Dict],
    ) -> List[Dict]:
        """핵심 영향 요인 분석"""
        factors = []

        # 글로벌 뉴스에서 핵심 키워드 추출
        global_themes = defaultdict(lambda: {'count': 0, 'sentiment_sum': 0.0})
        theme_keywords = {
            'US 금리/연준': ['fed', 'federal reserve', 'rate cut', 'rate hike', 'fomc', 'powell'],
            '무역/관세': ['tariff', 'trade war', 'sanctions', 'trade deal', 'export', 'import'],
            '반도체/AI': ['semiconductor', 'chip', 'nvidia', 'ai', 'dram', 'memory'],
            '미국 증시': ['wall street', 'dow', 'nasdaq', 's&p', 'rally', 'sell-off'],
            '중국 경제': ['china', 'chinese', 'beijing', 'yuan', 'pboc'],
            '원유/에너지': ['oil', 'crude', 'brent', 'opec', 'energy'],
            '환율': ['dollar', 'won', 'yen', 'forex', 'currency'],
            '지정학': ['war', 'conflict', 'military', 'geopolitical', 'missile'],
        }

        for news in global_news:
            text = f"{news.get('title', '')} {news.get('content', '')}".lower()
            sentiment = news.get('sentiment_score', 0)
            for theme, keywords in theme_keywords.items():
                if any(kw in text for kw in keywords):
                    global_themes[theme]['count'] += 1
                    global_themes[theme]['sentiment_sum'] += sentiment if sentiment else 0

        # 뉴스 건수 기준 상위 5개 테마
        sorted_themes = sorted(global_themes.items(), key=lambda x: x[1]['count'], reverse=True)[:5]
        for theme, data in sorted_themes:
            avg_sent = data['sentiment_sum'] / data['count'] if data['count'] > 0 else 0
            impact = '긍정' if avg_sent > 0.05 else ('부정' if avg_sent < -0.05 else '중립')
            factors.append({
                'factor': theme,
                'type': 'global',
                'news_count': data['count'],
                'avg_sentiment': round(avg_sent, 3),
                'impact': impact,
            })

        # 국내 뉴스 테마
        domestic_themes = defaultdict(lambda: {'count': 0, 'sentiment_sum': 0.0})
        kr_theme_keywords = {
            '증시 동향': ['코스피', '코스닥', '증시', '주가', '지수'],
            '기업 실적': ['실적', '영업이익', '매출', '순이익', '분기'],
            '금리/통화': ['금리', '한국은행', '기준금리', '원화', '환율'],
            '수출/무역': ['수출', '수입', '무역', '관세', '통상'],
            '부동산': ['부동산', '아파트', '주택', '분양'],
            '정책/규제': ['정부', '정책', '규제', '법안', '국회'],
        }

        for news in domestic_news:
            text = f"{news.get('title', '')} {news.get('content', '')}".lower()
            sentiment = news.get('sentiment_score', 0)
            for theme, keywords in kr_theme_keywords.items():
                if any(kw in text for kw in keywords):
                    domestic_themes[theme]['count'] += 1
                    domestic_themes[theme]['sentiment_sum'] += sentiment if sentiment else 0

        sorted_kr = sorted(domestic_themes.items(), key=lambda x: x[1]['count'], reverse=True)[:3]
        for theme, data in sorted_kr:
            avg_sent = data['sentiment_sum'] / data['count'] if data['count'] > 0 else 0
            impact = '긍정' if avg_sent > 0.05 else ('부정' if avg_sent < -0.05 else '중립')
            factors.append({
                'factor': theme,
                'type': 'domestic',
                'news_count': data['count'],
                'avg_sentiment': round(avg_sent, 3),
                'impact': impact,
            })

        return factors

    def _empty_prediction(self, reason: str) -> Dict:
        """빈 예측 결과"""
        return {
            'prediction': {
                'direction': 'neutral',
                'strength': 'none',
                'description': reason,
                'mixed_signals': False,
                'global_direction': 'neutral',
                'domestic_direction': 'neutral',
            },
            'confidence': 0.0,
            'combined_sentiment': 0.0,
            'combined_overall': 0.0,
            'market_phase': self._get_market_phase(),
            'phase_weights': self._get_phase_weights(self._get_market_phase()),
            'global_analysis': {'total_count': 0},
            'domestic_analysis': {'total_count': 0},
            'key_factors': [],
            'total_news_analyzed': 0,
            'analysis_hours': 0,
            'analysis_time': datetime.now().isoformat(),
        }

    def predict_with_summary(self, hours: int = 24) -> Dict:
        """
        예측 결과 + 사람이 읽기 쉬운 요약 포함

        Args:
            hours: 분석 시간 범위

        Returns:
            예측 결과 + summary 필드
        """
        result = self.predict_index(hours=hours)

        pred = result['prediction']
        conf = result['confidence']
        phase = result['market_phase']

        phase_kr = {
            'pre_market': '장전',
            'market_open': '장중',
            'after_market': '장후',
            'weekend': '주말',
        }

        # 방향 아이콘
        dir_icon = {
            'up': '▲',
            'down': '▼',
            'neutral': '━',
        }

        # 요약 텍스트 생성
        lines = []
        lines.append(f"[{phase_kr.get(phase, phase)}] KOSPI/KOSDAQ 예측: {dir_icon.get(pred['direction'], '?')} {pred['description']}")
        lines.append(f"신뢰도: {conf:.0%} | 종합 감성: {result['combined_sentiment']:+.3f}")

        # 글로벌 분석
        g = result['global_analysis']
        if g.get('total_count', 0) > 0:
            lines.append(f"글로벌 뉴스: {g['total_count']}건 (감성: {g['weighted_sentiment']:+.3f}, 긍정률: {g['positive_ratio']:.0%})")

        # 국내 분석
        d = result['domestic_analysis']
        if d.get('total_count', 0) > 0:
            lines.append(f"국내 뉴스: {d['total_count']}건 (감성: {d['weighted_sentiment']:+.3f}, 긍정률: {d['positive_ratio']:.0%})")

        # 핵심 요인
        if result['key_factors']:
            lines.append("핵심 요인:")
            for f in result['key_factors'][:5]:
                lines.append(f"  - {f['factor']}: {f['impact']} ({f['news_count']}건, 감성 {f['avg_sentiment']:+.3f})")

        result['summary'] = '\n'.join(lines)
        return result
