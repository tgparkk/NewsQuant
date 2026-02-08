"""
뉴스 감성 분석 모듈
키워드 기반 감성 분석 및 점수 계산

개선사항 (2026-02-08):
- 부정어(negation) 처리 추가: 감성 키워드 근처의 부정어로 극성 반전
- 복합 표현 사전 추가: "상승세 꺾여" → 부정, "하락 우려 해소" → 긍정
- 감성 점수 덮어쓰기 버그 수정: ratio 계산 결과가 0일 때만 fallback 적용
- overall_score 가중치 공식 문서화
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """뉴스 감성 분석기"""
    
    # 긍정 키워드 (주가 상승 기대)
    POSITIVE_KEYWORDS = [
        # 성장/실적 관련
        '상승', '증가', '성장', '호재', '실적 호조', '실적 개선', '수익 증가',
        '매출 증가', '영업이익 증가', '순이익 증가', '실적 부진 탈출',
        '반등', '회복', '개선', '향상', '증대', '확대', '성공', '최고치', '사상 최대',
        
        # 투자/계약 관련 (인수/합병은 맥락에 따라 다르므로 제거, 복합표현으로 대체)
        '투자 유치', '계약 체결', '수주', '납품', '공급 계약', '독점',
        '제휴', '협력', '파트너십', '업무협약',
        
        # 긍정적 전망
        '긍정적', '낙관적', '기대', '전망 밝다', '유리하다', '재평가',
        '강세', '상승세', '상승 전망', '목표가 상향', '투자의견 상향', '매수 추천',
        
        # 기술/혁신 (출시는 중립적이므로 제거)
        '기술 개발', '특허', '신제품', '혁신', '세계 최초', '국내 최초',
        
        # 시장 반응 (모호한 키워드 제거: 관심/주목/인기/화제/이슈 — 방향성 없음)
        '러브콜', '잭팟',
        
        # 선행 지표성 긍정
        '수주 잔고 증가', '신규 수주', '공급 부족', '품절', '대기 수요',
        '가이던스 상향', '컨센서스 상회', '어닝 서프라이즈',
        '자사주 매입', '배당 확대', '배당 증가',
    ]
    
    # 부정 키워드 (주가 하락 우려)
    NEGATIVE_KEYWORDS = [
        # 하락/손실 관련
        '하락', '감소', '손실', '부진', '실적 부진', '실적 악화',
        '수익 감소', '매출 감소', '영업이익 감소', '순이익 감소',
        '적자', '손해', '채무', '부채 증가', '자본잠식',
        
        # 부정적 전망
        '부정적', '비관적', '우려', '우려 증대', '리스크', '불확실성',
        '약세', '하락세', '하락 전망', '목표가 하향', '투자의견 하향', '매도 의견',
        
        # 문제/사고 (모호 키워드 제거: 문제/이슈 — 너무 일반적)
        '사고', '사건', '논란', '분쟁', '법적 대응',
        '제재', '조사', '수사', '기소', '압수수색', '벌금', '과징금',
        
        # 선행 지표성 부정
        '수주 감소', '재고 증가', '가동률 하락',
        '가이던스 하향', '컨센서스 하회', '어닝 쇼크',
        '유상증자', 'CB 발행', '대주주 매도', '지분 매각',
        
        # 경영 문제
        '경영진 교체', '사퇴', '해임', '경영 위기', '횡령', '배임',
        '파업', '노조', '갈등', '내분',
        
        # 시장 부정
        '폭락', '급락', '매도', '매도세', '하락 압력', '공매도', '반대매매',
    ]

    # 강력한 호재 (가중치 높음)
    STRONG_POSITIVE = ['공급계약', '수주 성공', '영업이익 폭증', '인수 합병', '임상 성공', '상한가']
    
    # 강력한 악재 (가중치 높음)
    STRONG_NEGATIVE = ['상장폐지', '횡령', '배임', '영업이익 급감', '임상 실패', '부도', '하한가']
    
    # 복합 표현 사전: (표현, 감성) - 개별 키워드보다 우선 적용
    COMPOUND_EXPRESSIONS = [
        # 긍정 복합 표현 (부정적 키워드가 포함되지만 전체적으로 긍정)
        ('하락 우려 해소', 1),
        ('우려 해소', 1),
        ('우려 불식', 1),
        ('부진 탈출', 1),
        ('적자 탈출', 1),
        ('하락세 반등', 1),
        ('하락세에서 반등', 1),
        ('약세 탈피', 1),
        ('손실 만회', 1),
        ('위기 극복', 1),
        ('리스크 해소', 1),
        ('불확실성 해소', 1),
        ('매도세 진정', 1),
        ('하락 제한적', 1),
        # 부정 복합 표현 (긍정적 키워드가 포함되지만 전체적으로 부정)
        ('상승세 꺾여', -1),
        ('상승세 꺾이', -1),
        ('상승 기대 꺾', -1),
        ('성장 둔화', -1),
        ('성장세 둔화', -1),
        ('회복 지연', -1),
        ('반등 실패', -1),
        ('기대 이하', -1),
        ('기대에 못 미치', -1),
        ('기대 못 미치', -1),
        ('호재 소진', -1),
        ('강세 꺾여', -1),
        ('강세 꺾이', -1),
        ('상승 제한적', -1),
        ('개선 더뎌', -1),
        ('회복 더뎌', -1),
        ('수주 감소', -1),
    ]
    
    # 부정어 리스트 (감성 극성을 반전시키는 단어들)
    NEGATION_WORDS = [
        '안', '못', '없', '아닌', '않', '꺾', '불', '미',
        '무산', '철회', '취소', '중단', '포기', '실패',
    ]
    
    # 부정어 감지 윈도우 (키워드 앞 N 어절 이내에 부정어가 있으면 반전)
    NEGATION_WINDOW = 2
    
    # 중요 키워드 (뉴스 중요도 상승)
    IMPORTANCE_KEYWORDS = [
        '실적 발표', '분기 실적', '연간 실적', '공시', '공시사항',
        '인수합병', 'M&A', '합병', '인수', '매각',
        '신규 사업', '사업 확장', '투자 결정', '대규모 투자',
        'CEO', '경영진', '주주총회', '배당',
        '상장', '상장폐지', '관리종목', '거래정지',
        '규제', '정부 정책', '법안', '세법',
    ]
    
    # 영향도 키워드 (주가 영향력 상승)
    IMPACT_KEYWORDS = [
        '대형', '메가', '조 단위', '억 단위',
        '최초', '최대', '최고', '역대',
        '급등', '급락', '폭등', '폭락',
        '상한가', '하한가', '서킷브레이커',
        '외국인 매수', '외국인 매도', '기관 매수', '기관 매도',
    ]
    
    # 출처별 신뢰도 점수
    SOURCE_CREDIBILITY = {
        'hankyung': 0.8,
        'mk_news': 0.8,
        'naver_finance': 0.9,
        'krx_disclosure': 1.0,  # 공시는 최고 신뢰도
        'yonhap_infomax': 0.8,
    }
    
    # 카테고리별 중요도 가중치
    CATEGORY_WEIGHT = {
        '증시': 1.0,
        '금융시장': 1.0,
        '경제': 0.9,
        '산업': 0.8,
        '기술': 0.8,
        '국제': 0.7,
        '유통': 0.7,
    }
    
    def _check_negation(self, text: str, keyword: str, keyword_pos: int) -> bool:
        """
        키워드 근처에 부정어가 있는지 확인
        
        Args:
            text: 전체 텍스트
            keyword: 감성 키워드
            keyword_pos: 키워드의 시작 위치 (text 내 인덱스)
        
        Returns:
            부정어가 근처에 있으면 True
        """
        # 키워드 앞쪽 텍스트에서 어절 단위로 부정어 탐색
        prefix = text[:keyword_pos]
        # 앞쪽 어절들 추출 (최대 NEGATION_WINDOW개)
        words_before = prefix.split()
        words_to_check = words_before[-self.NEGATION_WINDOW:] if words_before else []
        
        for word in words_to_check:
            for neg in self.NEGATION_WORDS:
                if neg in word:
                    return True
        return False
    
    def _count_with_negation(self, text: str, keywords: List[str]) -> Tuple[int, int]:
        """
        부정어를 고려하여 키워드 카운트
        
        Args:
            text: 분석할 텍스트
            keywords: 감성 키워드 리스트
        
        Returns:
            (정상 카운트, 부정어에 의해 반전된 카운트) 튜플
        """
        normal_count = 0
        negated_count = 0
        
        for keyword in keywords:
            # 키워드의 모든 출현 위치 찾기
            start = 0
            while True:
                pos = text.find(keyword, start)
                if pos == -1:
                    break
                if self._check_negation(text, keyword, pos):
                    negated_count += 1
                else:
                    normal_count += 1
                start = pos + len(keyword)
        
        return normal_count, negated_count
    
    def calculate_sentiment_score(self, text: str) -> float:
        """
        감성 점수 계산 (-1.0 ~ +1.0)
        
        알고리즘:
        1. 복합 표현 먼저 매칭 (개별 키워드보다 우선)
        2. 부정어를 고려한 긍정/부정 키워드 카운트
        3. 비율 기반 점수 계산
        4. ratio 계산이 0일 때만 fallback 적용
        
        Args:
            text: 분석할 텍스트 (제목 + 본문)
        
        Returns:
            감성 점수 (-1.0: 매우 부정적, 0.0: 중립, +1.0: 매우 긍정적)
        """
        if not text:
            return 0.0
        
        text_lower = text.lower()
        
        # 1단계: 복합 표현 매칭 (우선순위 높음)
        compound_score = 0
        compound_matched = set()  # 매칭된 복합 표현에 포함된 키워드 추적
        for expr, sentiment in self.COMPOUND_EXPRESSIONS:
            if expr in text_lower:
                compound_score += sentiment
                compound_matched.add(expr)
        
        # 2단계: 부정어를 고려한 키워드 카운트
        # 복합 표현에 매칭된 부분은 개별 키워드 카운트에서 제외하기 위해
        # 텍스트에서 복합 표현을 제거한 버전 사용
        text_for_keywords = text_lower
        for expr, _ in self.COMPOUND_EXPRESSIONS:
            if expr in text_for_keywords:
                text_for_keywords = text_for_keywords.replace(expr, ' ')
        
        # 긍정 키워드: 정상 매칭 = 긍정, 부정어+긍정 = 부정
        pos_normal, pos_negated = self._count_with_negation(text_for_keywords, self.POSITIVE_KEYWORDS)
        # 부정 키워드: 정상 매칭 = 부정, 부정어+부정 = 긍정
        neg_normal, neg_negated = self._count_with_negation(text_for_keywords, self.NEGATIVE_KEYWORDS)
        
        # 실질적 긍정/부정 카운트 (부정어 반전 적용)
        positive_count = pos_normal + neg_negated  # 긍정키워드 + 부정어로 반전된 부정키워드
        negative_count = neg_normal + pos_negated  # 부정키워드 + 부정어로 반전된 긍정키워드
        
        # 복합 표현 점수 반영
        if compound_score > 0:
            positive_count += abs(compound_score)
        elif compound_score < 0:
            negative_count += abs(compound_score)
        
        # 3단계: 비율 기반 점수 계산
        if negative_count > positive_count:
            score = -min(1.0, negative_count / max(1, positive_count + 1))
        elif positive_count > negative_count:
            score = min(1.0, positive_count / max(1, negative_count + 1))
        else:
            score = 0.0
        
        # 4단계: fallback — ratio 계산이 0인 경우에만 적용
        # (긍정/부정 키워드가 동수이지만 한쪽만 있는 경우)
        if score == 0.0:
            if negative_count > 0 and positive_count == 0:
                score = -0.5
            elif positive_count > 0 and negative_count == 0:
                score = 0.5
        
        # 점수 정규화 (-1.0 ~ +1.0)
        return max(-1.0, min(1.0, score))
    
    def calculate_importance_score(self, text: str, source: str, category: str) -> float:
        """
        중요도 점수 계산 (0.0 ~ 1.0)
        
        공식: keyword_score * 0.4 + source_score * 0.3 + category_weight * 0.3
        - keyword_score: 중요 키워드 개수 × 0.2 (최대 1.0, 즉 5개 이상이면 만점)
        - source_score: 출처별 신뢰도 (0.5~1.0)
        - category_weight: 카테고리별 가중치 (0.5~1.0)
        
        Args:
            text: 분석할 텍스트
            source: 출처
            category: 카테고리
        
        Returns:
            중요도 점수 (0.0: 낮음, 1.0: 매우 높음)
        """
        if not text:
            return 0.0
        
        text_lower = text.lower()
        
        # 중요 키워드 카운트
        importance_count = sum(1 for keyword in self.IMPORTANCE_KEYWORDS if keyword in text_lower)
        
        # 출처 신뢰도
        source_score = self.SOURCE_CREDIBILITY.get(source, 0.5)
        
        # 카테고리 가중치
        category_weight = self.CATEGORY_WEIGHT.get(category, 0.5)
        
        # 중요도 계산
        keyword_score = min(1.0, importance_count * 0.2)  # 키워드당 0.2점, 최대 1.0 (5개 이상)
        importance = (keyword_score * 0.4 + source_score * 0.3 + category_weight * 0.3)
        
        return min(1.0, importance)
    
    def calculate_impact_score(self, text: str, related_stocks: str) -> float:
        """
        영향도 점수 계산 (0.0 ~ 1.0)
        
        Args:
            text: 분석할 텍스트
            related_stocks: 관련 종목 코드 (콤마 구분)
        
        Returns:
            영향도 점수 (0.0: 낮음, 1.0: 매우 높음)
        """
        if not text:
            return 0.0
        
        text_lower = text.lower()
        
        # 영향도 키워드 카운트
        impact_count = sum(1 for keyword in self.IMPACT_KEYWORDS if keyword in text_lower)
        
        # 관련 종목 개수 (종목이 많을수록 영향도 높음)
        stock_count = len([s for s in related_stocks.split(',') if s.strip()]) if related_stocks else 0
        stock_score = min(1.0, stock_count * 0.2)  # 종목당 0.2점, 최대 1.0
        
        # 텍스트 길이 (본문이 길수록 상세한 정보)
        text_length_score = min(1.0, len(text) / 1000)  # 1000자 기준
        
        # 영향도 계산
        keyword_score = min(1.0, impact_count * 0.3)  # 키워드당 0.3점
        impact = (keyword_score * 0.4 + stock_score * 0.3 + text_length_score * 0.3)
        
        return min(1.0, impact)
    
    def calculate_timeliness_score(self, published_at: str) -> float:
        """
        실시간성 점수 계산 (0.0 ~ 1.0)
        
        Args:
            published_at: 발행일시 (ISO 형식)
        
        Returns:
            실시간성 점수 (0.0: 오래됨, 1.0: 최신)
        """
        try:
            if not published_at:
                return 0.5
            
            # ISO 형식 파싱
            if 'T' in published_at:
                pub_time = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            else:
                return 0.5
            
            # 현재 시간과의 차이 (시간 단위)
            now = datetime.now(pub_time.tzinfo if pub_time.tzinfo else None)
            if pub_time.tzinfo:
                now = datetime.now(pub_time.tzinfo)
            else:
                now = datetime.now()
            
            hours_diff = abs((now - pub_time).total_seconds() / 3600)
            
            # 24시간 이내: 1.0, 48시간: 0.5, 그 이상: 0.0
            if hours_diff <= 24:
                return 1.0
            elif hours_diff <= 48:
                return 0.5
            elif hours_diff <= 168:  # 1주일
                return 0.2
            else:
                return 0.1
                
        except Exception as e:
            logger.debug(f"실시간성 점수 계산 오류: {e}")
            return 0.5
    
    def analyze_news(self, news_data: Dict) -> Dict:
        """
        뉴스 전체 분석 및 점수 계산 (고도화 버전)
        
        종합 점수(overall_score) 공식:
            overall_score = sentiment * 0.4 + importance * 0.3 + impact * 0.2 + timeliness * 0.1
        
        - sentiment (-1.0~1.0): 감성 점수. 제목 70% + 본문 30% 가중 평균.
          강력 호재/악재 키워드 발견 시 ±0.3 보너스.
        - importance (0.0~1.0): 중요도. 키워드 40% + 출처 신뢰도 30% + 카테고리 30%.
          제목에 종목명 포함 시 +0.2 보너스.
        - impact (0.0~1.0): 영향도. 키워드 40% + 관련종목수 30% + 텍스트길이 30%.
        - timeliness (0.0~1.0): 실시간성. 24h 이내=1.0, 48h=0.5, 1주=0.2, 이상=0.1.
        
        참고: overall_score 범위는 sentiment이 음수일 수 있으므로 -0.4 ~ 1.0 범위.
        양수일수록 긍정적+중요한 뉴스, 음수면 부정적 뉴스.
        """
        title = news_data.get('title', '')
        content = news_data.get('content', '')
        
        # 1. 감성 점수 계산 (제목 가중치 부여)
        # 제목은 본문보다 더 중요하게 처리 (70:30)
        title_sentiment = self.calculate_sentiment_score(title)
        content_sentiment = self.calculate_sentiment_score(content)
        
        # 강력한 키워드 체크 (제목 우선)
        strong_pos = any(kw in title for kw in self.STRONG_POSITIVE)
        strong_neg = any(kw in title for kw in self.STRONG_NEGATIVE)
        
        sentiment = (title_sentiment * 0.7 + content_sentiment * 0.3)
        if strong_pos: sentiment = min(1.0, sentiment + 0.3)
        if strong_neg: sentiment = max(-1.0, sentiment - 0.3)
        
        # 2. 중요도 및 영향도 점수
        source = news_data.get('source', '')
        category = news_data.get('category', '')
        related_stocks = news_data.get('related_stocks', '')
        published_at = news_data.get('published_at', '')
        
        importance = self.calculate_importance_score(f"{title} {content}", source, category)
        
        # 제목에 종목명이 명시적으로 포함되어 있으면 중요도 상승
        if any(stock.strip() in title for stock in related_stocks.split(',') if len(stock.strip()) >= 2):
            importance = min(1.0, importance + 0.2)
            
        impact = self.calculate_impact_score(f"{title} {content}", related_stocks)
        timeliness = self.calculate_timeliness_score(published_at)
        
        # 3. 종합 점수 (가중 평균)
        # 감성 40%, 중요도 30%, 영향도 20%, 실시간성 10%
        overall_score = (
            sentiment * 0.4 +
            importance * 0.3 +
            impact * 0.2 +
            timeliness * 0.1
        )
        
        # 결과 반영
        news_data['sentiment_score'] = round(sentiment, 3)
        news_data['importance_score'] = round(importance, 3)
        news_data['impact_score'] = round(impact, 3)
        news_data['timeliness_score'] = round(timeliness, 3)
        news_data['overall_score'] = round(overall_score, 3)
        
        return news_data
