"""
네이버 금융에서 전체 상장 종목 리스트를 가져와서
종목명→종목코드 매핑 파일을 생성합니다.
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import time

def fetch_naver_stock_list():
    """네이버 금융에서 KOSPI/KOSDAQ 종목 리스트 가져오기"""
    
    print("=" * 80)
    print("네이버 금융 전체 상장 종목 리스트 수집")
    print("=" * 80)
    print(f"수집 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    stock_dict = {}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    # KOSPI와 KOSDAQ 종목 가져오기
    markets = {
        '0': 'KOSPI',
        '1': 'KOSDAQ'
    }
    
    for market_code, market_name in markets.items():
        print(f"[{market_name}] 종목 정보 수집 중...")
        
        try:
            # 네이버 금융 시가총액 순위 페이지 (전체 종목 포함)
            base_url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={market_code}"
            
            # 여러 페이지 수집 (1-20페이지 = 약 400개 종목)
            for page in range(1, 21):
                url = f"{base_url}&page={page}"
                
                try:
                    response = requests.get(url, headers=headers, timeout=10)
                    response.raise_for_status()
                    
                    soup = BeautifulSoup(response.content, 'lxml')
                    
                    # 종목 테이블 찾기
                    table = soup.find('table', class_='type_2')
                    if not table:
                        break
                    
                    rows = table.find_all('tr')
                    
                    for row in rows:
                        # 종목명과 코드 추출
                        name_cell = row.find('a', href=True)
                        if not name_cell:
                            continue
                        
                        stock_name = name_cell.text.strip()
                        href = name_cell['href']
                        
                        # href에서 종목 코드 추출: /item/main.naver?code=005930
                        if 'code=' in href:
                            stock_code = href.split('code=')[1].split('&')[0]
                            
                            if stock_code and stock_name:
                                stock_dict[stock_name] = stock_code
                                
                                # 흔한 변형 추가
                                # "삼성전자" → "삼성"
                                for suffix in ['전자', '제약', '화학', '홀딩스', '그룹', '주식회사', '㈜']:
                                    if suffix in stock_name:
                                        base_name = stock_name.replace(suffix, '').strip()
                                        if base_name and len(base_name) >= 2:
                                            stock_dict[base_name] = stock_code
                    
                    time.sleep(0.3)  # 요청 간 딜레이
                    
                except Exception as e:
                    print(f"  페이지 {page} 오류: {e}")
                    break
            
            print(f"  수집 완료: {len([v for v in stock_dict.values() if v])}개 종목")
            
        except Exception as e:
            print(f"  [오류] {market_name} 수집 실패: {e}")
    
    print()
    print(f"총 수집된 종목명: {len(stock_dict)}개")
    print(f"고유 종목 코드: {len(set(stock_dict.values()))}개")
    print()
    
    # 파일로 저장
    output_file = "stock_codes_mapping.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(stock_dict, f, ensure_ascii=False, indent=2)
    
    print(f"종목 매핑 파일 저장 완료: {output_file}")
    print()
    
    # Python 딕셔너리 코드로도 저장
    py_file = "stock_codes_extended.py"
    with open(py_file, 'w', encoding='utf-8') as f:
        f.write("# 네이버 금융 전체 상장 종목 코드 매핑\n")
        f.write(f"# 생성 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# 총 {len(stock_dict)}개 종목명, {len(set(stock_dict.values()))}개 고유 종목\n\n")
        f.write("EXTENDED_STOCK_CODES = {\n")
        
        items = sorted(stock_dict.items())
        for i, (name, code) in enumerate(items):
            comma = "," if i < len(items) - 1 else ""
            # 종목명에 작은따옴표가 있으면 이스케이프
            safe_name = name.replace("'", "\\'")
            f.write(f"    '{safe_name}': '{code}'{comma}\n")
        
        f.write("}\n")
    
    print(f"Python 딕셔너리 파일 저장 완료: {py_file}")
    print()
    
    # 샘플 출력
    print("=" * 80)
    print("샘플 종목 (30개)")
    print("=" * 80)
    for i, (name, code) in enumerate(list(stock_dict.items())[:30]):
        print(f"{code}: {name}")
    
    print()
    print("=" * 80)
    print("수집 완료!")
    print("=" * 80)
    
    return stock_dict

if __name__ == "__main__":
    try:
        stocks = fetch_naver_stock_list()
    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
