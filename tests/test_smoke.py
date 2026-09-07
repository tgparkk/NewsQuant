def test_package_imports():
    import news_scraper  # noqa: F401
    from news_scraper.sentiment_analyzer import SentimentAnalyzer
    assert "naver_finance" in SentimentAnalyzer.SOURCE_CREDIBILITY
