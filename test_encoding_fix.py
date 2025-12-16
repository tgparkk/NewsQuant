"""
인코딩 수정 테스트 스크립트
"""

import sys
import io
from news_scraper.crawlers.naver_finance_crawler import NaverFinanceCrawler

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_encoding():
    """인코딩 수정 테스트"""
    print("=" * 80)
    print("네이버 금융 인코딩 수정 테스트")
    print("=" * 80)
    print()
    
    crawler = NaverFinanceCrawler()
    
    # 테스트 URL
    test_url = 'https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258&page=1'
    
    print(f"테스트 URL: {test_url}")
    print("페이지 가져오는 중...")
    
    soup = crawler.fetch_page(test_url)
    
    if not soup:
        print("❌ 페이지를 가져오지 못했습니다.")
        return
    
    print("✓ 페이지 가져오기 성공")
    print()
    
    # 제목 확인
    title_tag = soup.find('title')
    if title_tag:
        title_text = title_tag.get_text()
        print(f"페이지 제목: {title_text}")
        print(f"제목 길이: {len(title_text)} 문자")
        
        # 한글이 포함되어 있는지 확인
        has_korean = any('\uac00' <= char <= '\ud7a3' for char in title_text)
        if has_korean:
            print("✓ 한글 포함 확인됨")
        else:
            print("⚠ 한글이 포함되어 있지 않습니다.")
        print()
    
    # 뉴스 링크 몇 개 확인
    print("뉴스 링크 제목 확인 (최대 5개):")
    print("-" * 80)
    
    all_links = soup.find_all('a', href=True)
    news_count = 0
    
    for link in all_links:
        href = link.get('href', '')
        if '/news/news_read' in href or '/news/news_view' in href:
            title = crawler.extract_text(link)
            if title and len(title) >= 10:
                news_count += 1
                print(f"{news_count}. {title[:80]}")
                
                # 한글 확인
                has_korean = any('\uac00' <= char <= '\ud7a3' for char in title)
                if has_korean:
                    print(f"   ✓ 한글 정상")
                else:
                    # 깨진 문자 확인
                    has_broken = '\ufffd' in title or any(ord(c) > 0x7f and not ('\uac00' <= c <= '\ud7a3') for c in title if c)
                    if has_broken:
                        print(f"   ❌ 한글 깨짐 의심")
                    else:
                        print(f"   ⚠ 한글 없음 (영문 뉴스일 수 있음)")
                print()
                
                if news_count >= 5:
                    break
    
    print("=" * 80)

if __name__ == "__main__":
    test_encoding()
