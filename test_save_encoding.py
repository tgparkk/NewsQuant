#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
실제 데이터 저장 테스트 - 한글 인코딩 확인
"""

import sys
import io
from news_scraper.database import NewsDatabase
from news_scraper.crawlers.naver_finance_crawler import NaverFinanceCrawler

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_save_encoding():
    """실제 크롤링 및 저장 테스트"""
    print("=" * 80)
    print("네이버 금융 크롤링 및 저장 테스트")
    print("=" * 80)
    print()
    
    crawler = NaverFinanceCrawler()
    db = NewsDatabase()
    
    # 테스트: 1페이지만 크롤링
    print("크롤링 시작...")
    news_list = crawler.crawl_news_list(max_pages=1)
    
    if not news_list:
        print("❌ 크롤링된 뉴스가 없습니다.")
        return
    
    print(f"✓ {len(news_list)}개 뉴스 크롤링 완료")
    print()
    
    # 처음 3개만 저장 테스트
    test_news = news_list[:3]
    
    print("저장 테스트 (처음 3개):")
    print("-" * 80)
    
    for idx, news in enumerate(test_news, 1):
        title = news.get('title', '')
        print(f"\n{idx}. 제목 (크롤링 후): {title[:80]}")
        
        # 한글 확인
        has_korean = any('\uac00' <= char <= '\ud7a3' for char in title)
        has_broken = '\ufffd' in title
        
        if has_broken:
            print(f"   ❌ 깨진 문자 발견")
        elif has_korean:
            print(f"   ✓ 한글 정상")
        else:
            print(f"   ⚠ 한글 없음")
        
        # 저장
        success = db.insert_news(news)
        if success:
            print(f"   ✓ 저장 성공")
        else:
            print(f"   ❌ 저장 실패")
    
    print()
    print("=" * 80)
    print("저장된 데이터 확인:")
    print("=" * 80)
    
    # 저장된 데이터 확인
    saved_news = db.get_latest_news(limit=3, source='naver_finance')
    
    for idx, news in enumerate(saved_news[:3], 1):
        title = news.get('title', '')
        print(f"\n{idx}. 제목 (DB에서 조회): {title[:80]}")
        
        # 한글 확인
        has_korean = any('\uac00' <= char <= '\ud7a3' for char in title)
        has_broken = '\ufffd' in title
        
        if has_broken:
            print(f"   ❌ 깨진 문자 발견")
        elif has_korean:
            print(f"   ✓ 한글 정상")
        else:
            print(f"   ⚠ 한글 없음")
    
    print()
    print("=" * 80)

if __name__ == "__main__":
    test_save_encoding()












