"""
뉴스 감성 분석 모듈
키워드 기반 감성 분석 및 점수 계산
"""

import re
from datetime import datetime
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """뉴스 감성 분석기"""
    
    # 긍정 키워드 (주가 상승 기대)
    POSITIVE_KEYWORDS = [
        # 성장/실적 관련
        '상승', '증가', '성장', '호재', '실적 호조', '실적 개선', '수익 증가',
        '매출 증가', '영업이익 증가', '순이익 증가', '실적 부진 탈출',
        '반등', '회복', '개선', '향상', '증대', '확대', '성공',
        
        # 투자/계약 관련
        '투자 유치', '계약 체결', '수주', '납품', '공급 계약',
        '인수', '합병', '제휴', '협력', '파트너십',
        
        # 긍정적 전망
        '긍정적', '낙관적', '기대', '전망 밝다', '유리하다',
        '강세', '상승세', '상승 전망', '목표가 상향', '투자의견 상향',
        
        # 기술/혁신
        '기술 개발', '특허', '신제품', '출시', '혁신',
        
        # 시장 반응
        '관심', '주목', '인기', '화제', '이슈',
    ]
    
    # 부정 키워드 (주가 하락 우려)
    NEGATIVE_KEYWORDS = [
        # 하락/손실 관련
        '하락', '감소', '손실', '부진', '실적 부진', '실적 악화',
        '수익 감소', '매출 감소', '영업이익 감소', '순이익 감소',
        '적자', '손해', '채무', '부채 증가',
        
        # 부정적 전망
        '부정적', '비관적', '우려', '우려 증대', '리스크',
        '약세', '하락세', '하락 전망', '목표가 하향', '투자의견 하향',
        
        # 문제/사고
        '사고', '사건', '논란', '문제', '이슈', '분쟁',
        '규제', '제재', '조사', '수사', '기소',
        
        # 경영 문제
        '경영진 교체', '사퇴', '해임', '경영 위기',
        '파업', '노조', '갈등',
        
        # 시장 부정
        '폭락', '급락', '매도', '매도세', '하락 압력',
    ]
    
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
    
    def calculate_sentiment_score(self, text: str) -> float:
        """
        감성 점수 계산 (-1.0 ~ +1.0)
        
        Args:
            text: 분석할 텍스트 (제목 + 본문)
        
        Returns:
            감성 점수 (-1.0: 매우 부정적, 0.0: 중립, +1.0: 매우 긍정적)
        """
        if not text:
            return 0.0
        
        text_lower = text.lower()
        
        # 긍정/부정 키워드 카운트
        positive_count = sum(1 for keyword in self.POSITIVE_KEYWORDS if keyword in text_lower)
        negative_count = sum(1 for keyword in self.NEGATIVE_KEYWORDS if keyword in text_lower)
        
        # 부정 키워드가 더 많으면 부정 점수
        if negative_count > positive_count:
            # 부정 점수: -1.0 ~ 0.0
            score = -min(1.0, negative_count / max(1, positive_count + 1))
        elif positive_count > negative_count:
            # 긍정 점수: 0.0 ~ +1.0
            score = min(1.0, positive_count / max(1, negative_count + 1))
        else:
            # 동일하거나 없으면 중립
            score = 0.0
        
        # 부정 키워드가 있으면 약간 감점
        if negative_count > 0 and positive_count == 0:
            score = -0.5
        
        # 긍정 키워드만 있으면 약간 가점
        if positive_count > 0 and negative_count == 0:
            score = 0.5
        
        # 점수 정규화 (-1.0 ~ +1.0)
        return max(-1.0, min(1.0, score))
    
    def calculate_importance_score(self, text: str, source: str, category: str) -> float:
        """
        중요도 점수 계산 (0.0 ~ 1.0)
        
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
        keyword_score = min(1.0, importance_count * 0.2)  # 키워드당 0.2점, 최대 1.0
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
        뉴스 전체 분석 및 점수 계산
        
        Args:
            news_data: 뉴스 데이터 딕셔너리
        
        Returns:
            점수가 추가된 뉴스 데이터
        """
        title = news_data.get('title', '')
        content = news_data.get('content', '')
        text = f"{title} {content}"
        
        source = news_data.get('source', '')
        category = news_data.get('category', '')
        related_stocks = news_data.get('related_stocks', '')
        published_at = news_data.get('published_at', '')
        
        # 각 점수 계산
        sentiment = self.calculate_sentiment_score(text)
        importance = self.calculate_importance_score(text, source, category)
        impact = self.calculate_impact_score(text, related_stocks)
        timeliness = self.calculate_timeliness_score(published_at)
        
        # 종합 점수 (가중 평균)
        # 감성 점수를 주요 점수로 사용하되, 다른 요소들도 반영
        overall_score = (
            sentiment * 0.5 +  # 감성 50%
            importance * 0.2 +  # 중요도 20%
            impact * 0.2 +      # 영향도 20%
            timeliness * 0.1    # 실시간성 10%
        )
        
        # 결과 반영
        news_data['sentiment_score'] = round(sentiment, 3)
        news_data['importance_score'] = round(importance, 3)
        news_data['impact_score'] = round(impact, 3)
        news_data['timeliness_score'] = round(timeliness, 3)
        news_data['overall_score'] = round(overall_score, 3)
        
        return news_data

