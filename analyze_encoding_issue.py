#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
한글 깨짐 원인 분석 스크립트
"""

import sys
import io
import requests
from bs4 import BeautifulSoup

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def analyze_encoding_issue():
    """한글 깨짐 원인 분석"""
    print("=" * 80)
    print("한글 깨짐 원인 분석")
    print("=" * 80)
    print()
    
    # 1. 시스템 인코딩 확인
    print("[1] 시스템 인코딩 확인")
    print("-" * 80)
    print(f"Python 기본 인코딩: {sys.getdefaultencoding()}")
    print(f"stdout 인코딩: {sys.stdout.encoding}")
    print(f"stdin 인코딩: {sys.stdin.encoding}")
    import locale
    print(f"로케일 기본 인코딩: {locale.getpreferredencoding()}")
    print()
    
    # 2. 네이버 금융 페이지 실제 인코딩 확인
    print("[2] 네이버 금융 페이지 인코딩 확인")
    print("-" * 80)
    
    test_url = 'https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258&page=1'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    response = requests.get(test_url, headers=headers, timeout=10)
    
    print(f"HTTP 상태 코드: {response.status_code}")
    print(f"Content-Type 헤더: {response.headers.get('Content-Type', 'N/A')}")
    print(f"Response 인코딩 (requests 추정): {response.encoding}")
    print(f"Response apparent_encoding: {response.apparent_encoding}")
    print()
    
    # 3. 실제 HTML 내용 분석
    print("[3] HTML 내용 인코딩 분석")
    print("-" * 80)
    
    # 원본 바이트 확인
    raw_bytes = response.content[:500]
    print(f"원본 바이트 (처음 100바이트): {raw_bytes[:100]}")
    print()
    
    # charset 메타 태그 확인
    try:
        temp_html = response.content.decode('utf-8', errors='ignore')
        import re
        charset_match = re.search(r'charset\s*=\s*["\']?([^"\'\s>]+)', temp_html, re.IGNORECASE)
        if charset_match:
            html_charset = charset_match.group(1).lower()
            print(f"HTML charset 메타 태그: {html_charset}")
        else:
            print("HTML charset 메타 태그: 없음")
    except:
        print("HTML charset 확인 실패")
    print()
    
    # 4. 다양한 인코딩으로 디코딩 시도
    print("[4] 다양한 인코딩으로 디코딩 테스트")
    print("-" * 80)
    
    test_encodings = ['utf-8', 'euc-kr', 'cp949', 'latin1']
    
    for encoding in test_encodings:
        try:
            decoded = response.content[:1000].decode(encoding, errors='strict')
            # 한글 확인
            has_korean = any('\uac00' <= char <= '\ud7a3' for char in decoded)
            has_broken = '\ufffd' in decoded
            
            status = "✓ 정상" if has_korean and not has_broken else "❌ 문제"
            print(f"{encoding:10s}: {status}", end="")
            if has_korean:
                # 한글 샘플 추출
                korean_chars = [c for c in decoded if '\uac00' <= c <= '\ud7a3']
                if korean_chars:
                    print(f" (한글 샘플: {''.join(korean_chars[:5])})")
                else:
                    print()
            else:
                print()
        except UnicodeDecodeError as e:
            print(f"{encoding:10s}: ❌ 디코딩 실패 - {e}")
    print()
    
    # 5. BeautifulSoup 파싱 테스트
    print("[5] BeautifulSoup 파싱 테스트")
    print("-" * 80)
    
    # UTF-8로 디코딩 후 BeautifulSoup
    try:
        html_utf8 = response.content.decode('utf-8', errors='replace')
        soup_utf8 = BeautifulSoup(html_utf8, 'lxml')
        title_tag = soup_utf8.find('title')
        if title_tag:
            title_text = title_tag.get_text()
            has_korean = any('\uac00' <= char <= '\ud7a3' for char in title_text)
            print(f"UTF-8 디코딩 후 BeautifulSoup:")
            print(f"  제목: {title_text[:50]}")
            print(f"  한글 포함: {'✓' if has_korean else '✗'}")
    except Exception as e:
        print(f"UTF-8 파싱 오류: {e}")
    print()
    
    # 6. 실제 크롤러 동작 시뮬레이션
    print("[6] 크롤러 동작 시뮬레이션")
    print("-" * 80)
    
    # 현재 base_crawler의 fetch_page 로직 시뮬레이션
    html_content = None
    encodings_to_try = ['utf-8', 'euc-kr', 'cp949', 'latin1']
    
    for encoding in encodings_to_try:
        try:
            html_content = response.content.decode(encoding, errors='strict')
            if any('\uac00' <= char <= '\ud7a3' for char in html_content[:1000]):
                print(f"✓ {encoding}로 디코딩 성공 (한글 확인됨)")
                break
            elif encoding == 'utf-8':
                print(f"✓ {encoding}로 디코딩 (한글 없음, 영문일 수 있음)")
                break
        except (UnicodeDecodeError, UnicodeError) as e:
            print(f"✗ {encoding} 디코딩 실패: {e}")
            continue
    
    if html_content:
        soup = BeautifulSoup(html_content, 'lxml')
        links = soup.find_all('a', href=True)
        news_links = [l for l in links if '/news/news_read' in l.get('href', '')]
        
        if news_links:
            test_link = news_links[0]
            title = test_link.get_text(strip=True)
            print(f"\n첫 번째 뉴스 링크 제목 추출:")
            print(f"  제목: {title[:80]}")
            has_korean = any('\uac00' <= char <= '\ud7a3' for char in title)
            has_broken = '\ufffd' in title
            print(f"  한글 포함: {'✓' if has_korean else '✗'}")
            print(f"  깨진 문자: {'✓' if has_broken else '✗'}")
    
    print()
    print("=" * 80)
    print()
    print("[결론]")
    print("-" * 80)
    print("1. 커밋 메시지 깨짐: PowerShell의 cp949 인코딩과 Git의 인코딩 불일치")
    print("2. 데이터 깨짐: 네이버 금융 페이지 크롤링 시 인코딩 처리 문제")
    print("   - 이전에는 response.text를 사용하여 자동 인코딩에 의존")
    print("   - 현재는 response.content를 직접 디코딩하여 여러 인코딩 시도")
    print("3. 해결: UTF-8 파일로 커밋 메시지 작성, 크롤러에서 명시적 인코딩 처리")
    print("=" * 80)

if __name__ == "__main__":
    analyze_encoding_issue()












