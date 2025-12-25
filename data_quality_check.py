"""
수집된 뉴스 데이터 품질 조사 스크립트

이 스크립트는 데이터 품질 조사 기능을 실행하는 진입점입니다.
실제 구현은 news_scraper.data_quality 패키지에 모듈화되어 있습니다.
"""

from news_scraper.data_quality import check_data_quality

if __name__ == "__main__":
    check_data_quality()

