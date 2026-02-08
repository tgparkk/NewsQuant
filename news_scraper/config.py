"""
설정 관리 모듈
config.yaml 파일을 로드하고 환경 변수로 오버라이드를 지원합니다.
"""

import os
import re
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_config: Optional[Dict] = None


def _resolve_env_vars(value: Any) -> Any:
    """문자열 내 ${ENV_VAR} 패턴을 환경 변수 값으로 치환"""
    if isinstance(value, str):
        pattern = re.compile(r'\$\{(\w+)\}')
        match = pattern.search(value)
        if match:
            env_key = match.group(1)
            env_val = os.environ.get(env_key)
            if env_val is not None:
                return pattern.sub(env_val, value)
            else:
                logger.warning(f"환경 변수 {env_key}가 설정되지 않았습니다.")
                return value
        return value
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def load_config(config_path: Optional[str] = None) -> Dict:
    """
    config.yaml 로드 및 환경 변수 오버라이드 적용

    Args:
        config_path: config.yaml 경로 (기본: 프로젝트 루트)

    Returns:
        설정 딕셔너리
    """
    global _config
    if _config is not None:
        return _config

    if config_path is None:
        # 프로젝트 루트 기준
        project_root = Path(__file__).parent.parent
        config_path = project_root / "config.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        logger.warning(f"config.yaml을 찾을 수 없습니다: {config_path}. 기본값을 사용합니다.")
        _config = {
            "database": {"path": "news_data.db"},
            "api": {"host": "127.0.0.1", "port": 8000, "cors_origins": ["http://localhost:3000"]},
            "dart": {"api_key": ""},
            "crawling": {
                "market_hours_interval": 60,
                "after_hours_interval": 300,
                "weekend_interval": 1800,
            },
        }
        return _config

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    _config = _resolve_env_vars(raw)
    logger.info(f"설정 로드 완료: {config_path}")
    return _config


def get_config(key: str, default: Any = None) -> Any:
    """
    점(.) 구분 키로 설정값 조회.  예: get_config('dart.api_key')
    """
    cfg = load_config()
    keys = key.split(".")
    val = cfg
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return default
        if val is None:
            return default
    return val
