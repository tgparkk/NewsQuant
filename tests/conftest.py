"""NewsQuant 테스트 공통 픽스처."""
import pytest


@pytest.fixture(scope="session")
def db():
    """실 DB(kis_template) 연결. 없으면 이 픽스처를 쓰는 테스트를 skip 한다."""
    try:
        import psycopg2
        from news_scraper.database import NewsDatabase
        instance = NewsDatabase()
    except Exception as e:  # OperationalError 포함 — DB 없는 환경
        pytest.skip(f"실 DB 없음: {type(e).__name__}: {e}")
    return instance
