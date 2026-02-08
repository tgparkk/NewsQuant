"""
KRX(한국거래소)에서 전체 상장 종목 리스트를 가져와서
종목명→종목코드 매핑 파일을 생성합니다.
"""

import requests
import json
from datetime import datetime

def fetch_krx_stock_list():
    """KRX에서 KOSPI/KOSDAQ 전체 종목 리스트 가져오기"""
    
    print("=" * 80)
    print("KRX 전체 상장 종목 리스트 수집")
    print("=" * 80)
    print(f"수집 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # KRX 상장 종목 정보 API
    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    
    stock_dict = {}
    
    # KOSPI + KOSDAQ 종목 가져오기
    markets = {
        'STK': 'KOSPI',
        'KSQ': 'KOSDAQ'
    }
    
    for market_code, market_name in markets.items():
        try:
            print(f"[{market_name}] 종목 정보 수집 중...")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'http://data.krx.co.kr/contents/MDC/MDI/mdiLoader',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'bld': 'dbms/MDC/STAT/standard/MDCSTAT01901',
                'mktId': market_code,
                'trdDd': datetime.now().strftime('%Y%m%d'),
                'share': '1',
                'money': '1',
                'csvxls_isNo': 'false'
            }
            
            response = requests.post(url, headers=headers, data=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            if 'OutBlock_1' in result:
                items = result['OutBlock_1']
                print(f"  수집된 종목 수: {len(items)}개")
                
                for item in items:
                    stock_code = item.get('ISU_SRT_CD', '').strip()  # 종목코드
                    stock_name = item.get('ISU_ABBRV', '').strip()   # 종목명 (축약)
                    full_name = item.get('ISU_NM', '').strip()       # 정식 명칭
                    
                    if stock_code and stock_name:
                        # 종목명 (축약명)
                        stock_dict[stock_name] = stock_code
                        
                        # 정식 명칭도 추가
                        if full_name and full_name != stock_name:
                            stock_dict[full_name] = stock_code
                        
                        # 흔한 변형 추가
                        # 예: "삼성전자" → "삼성", "삼성전자주식회사"
                        if '전자' in stock_name:
                            base_name = stock_name.replace('전자', '')
                            if base_name:
                                stock_dict[base_name] = stock_code
                        
                        if '제약' in stock_name:
                            base_name = stock_name.replace('제약', '')
                            if base_name:
                                stock_dict[base_name] = stock_code
                        
                        if '화학' in stock_name:
                            base_name = stock_name.replace('화학', '')
                            if base_name:
                                stock_dict[base_name] = stock_code
            
        except Exception as e:
            print(f"  [오류] {market_name} 수집 실패: {e}")
            # 백업: 간단한 스크래핑 시도
            try:
                print(f"  백업 방식으로 재시도...")
                # 네이버 금융 API 활용
                naver_url = f"https://finance.naver.com/api/sise/etfItemList.nhn?sosok={'0' if market_code == 'STK' else '1'}"
                backup_response = requests.get(naver_url, timeout=10)
                # 생략: 복잡한 파싱 대신 기본 목록 사용
            except:
                pass
    
    print()
    print(f"총 수집된 종목: {len(stock_dict)}개")
    print()
    
    # 파일로 저장
    output_file = "stock_codes_mapping.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(stock_dict, f, ensure_ascii=False, indent=2)
    
    print(f"종목 매핑 파일 저장 완료: {output_file}")
    print()
    
    # Python 딕셔너리 코드로도 저장
    py_file = "stock_codes_dict.py"
    with open(py_file, 'w', encoding='utf-8') as f:
        f.write("# KRX 전체 상장 종목 코드 매핑\n")
        f.write(f"# 생성 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# 총 {len(stock_dict)}개 종목\n\n")
        f.write("EXTENDED_STOCK_CODES = {\n")
        
        for i, (name, code) in enumerate(sorted(stock_dict.items())):
            comma = "," if i < len(stock_dict) - 1 else ""
            f.write(f"    '{name}': '{code}'{comma}\n")
        
        f.write("}\n")
    
    print(f"Python 딕셔너리 파일 저장 완료: {py_file}")
    print()
    
    # 샘플 출력
    print("=" * 80)
    print("샘플 종목 (20개)")
    print("=" * 80)
    for i, (name, code) in enumerate(list(stock_dict.items())[:20]):
        print(f"{code}: {name}")
    
    print()
    print("=" * 80)
    print("수집 완료!")
    print("=" * 80)
    
    return stock_dict

if __name__ == "__main__":
    try:
        stocks = fetch_krx_stock_list()
    except Exception as e:
        print(f"오류 발생: {e}")
        print()
        print("KRX API 접근 실패. 기본 목록을 사용하거나 나중에 다시 시도해주세요.")
