"""
NewsQuant API 모듈
REST API를 통해 뉴스 데이터를 제공하는 서버
"""

from .server import start_api_server, app

__all__ = ['start_api_server', 'app']
