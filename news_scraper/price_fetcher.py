import requests
import pandas as pd
from datetime import datetime
import time
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class PriceFetcher:
    """주가 데이터 수집기 (네이버 금융 기반)"""
    
    BASE_URL = "https://finance.naver.com/item/sise_day.naver"
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    def get_daily_price(self, stock_code: str, pages: int = 1) -> pd.DataFrame:
        """
        특정 종목의 일별 시세를 가져옵니다.
        
        Args:
            stock_code: 종목 코드 (6자리)
            pages: 가져올 페이지 수 (1페이지당 10일치)
            
        Returns:
            DataFrame: 날짜, 종가, 전일비, 시가, 고가, 저가, 거래량
        """
        all_df = []
        
        for page in range(1, pages + 1):
            url = f"{self.BASE_URL}?code={stock_code}&page={page}"
            try:
                # lxml이 설치되어 있지 않을 경우를 대비해 html5lib 또는 html.parser 사용
                # 여기서는 requests로 텍스트를 먼저 가져옴
                response = requests.get(url, headers=self.HEADERS)
                if response.status_code != 200:
                    logger.error(f"주가 수집 실패: {stock_code}, HTTP {response.status_code}")
                    continue
                
                # pandas의 read_html을 사용하여 테이블 추출
                # Note: StringIO를 사용하거나 직접 문자열을 넘김
                try:
                    df_list = pd.read_html(response.text, flavor='bs4')
                except ImportError:
                    df_list = pd.read_html(response.text)
                    
                if not df_list:
                    continue
                
                # 데이터가 들어있는 테이블 찾기 (보통 첫 번째 또는 두 번째)
                # 네이버 금융 일별 시세는 보통 첫 번째 유효한 테이블이 데이터임
                df = None
                for d in df_list:
                    if '날짜' in d.columns and len(d) > 1:
                        df = d
                        break
                
                if df is None or df.empty:
                    continue
                
                df = df.dropna(subset=['날짜'])
                all_df.append(df)
                time.sleep(0.1) # 서버 부하 방지
                
            except Exception as e:
                logger.error(f"주가 수집 오류: {stock_code}, {e}")
                
        if not all_df:
            return pd.DataFrame()
            
        final_df = pd.concat(all_df).drop_duplicates()
        
        # 컬럼명 정리 및 날짜 형식 변환
        final_df.columns = ['날짜', '종가', '전일비', '시가', '고가', '저가', '거래량']
        
        # 날짜 타입 강제 변환 (이미 datetime인 경우 대비)
        if not pd.api.types.is_datetime64_any_dtype(final_df['날짜']):
            final_df['날짜'] = pd.to_datetime(final_df['날짜'].astype(str).str.replace('.', '-'))
        
        # 숫자형 변환
        cols = ['종가', '전일비', '시가', '고가', '저가', '거래량']
        for col in cols:
            final_df[col] = pd.to_numeric(final_df[col], errors='coerce')
            
        return final_df.sort_values('날짜', ascending=False)

    def get_price_at_date(self, stock_code: str, target_date: str) -> dict:
        """
        특정 날짜의 주가 정보를 가져옵니다.
        
        Args:
            stock_code: 종목 코드
            target_date: 대상 날짜 (YYYY-MM-DD)
            
        Returns:
            dict: 해당 날짜의 주가 정보
        """
        df = self.get_daily_price(stock_code, pages=2) # 최근 20일치 조회
        if df.empty:
            return {}
            
        # 시간 정보 제거하고 날짜만 비교
        target_dt = pd.to_datetime(target_date).normalize()
        df['날짜'] = df['날짜'].dt.normalize()
        
        # 해당 날짜와 일치하는 행 찾기
        match = df[df['날짜'] == target_dt]
        
        if not match.empty:
            result = match.iloc[0].to_dict()
            # Timestamp 객체를 문자열로 변환
            result['날짜'] = result['날짜'].strftime('%Y-%m-%d')
            return result
        return {}

if __name__ == "__main__":
    # 테스트 코드
    import sys
    logging.basicConfig(level=logging.INFO)
    fetcher = PriceFetcher()
    code = "005930"
    target = "2026-01-09"
    print(f"[{code}] {target} 주가 조회 중...")
    price = fetcher.get_price_at_date(code, target)
    print(f"결과: {price}")
