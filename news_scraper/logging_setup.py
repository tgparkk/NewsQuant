"""로깅 설정 일원화.

main.py / run_scheduler.py / run_api.py 가 각각 basicConfig 로 같은 파일에
append 하던 것을 이 모듈 하나로 모은다.

- RotatingFileHandler 로 파일 총량에 상한을 둔다
- RepeatSuppressFilter 로 같은 메시지의 폭주를 한 줄 + 요약으로 줄인다
"""

import logging
import re
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from typing import Callable, Dict, Tuple

DEFAULT_LOG_FILE = "news_scraper.log"
DEFAULT_MAX_BYTES = 20 * 1024 * 1024   # 20MB
DEFAULT_BACKUP_COUNT = 5               # 파일 총량 상한 120MB
DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
SUPPRESS_WINDOW = 60                   # 반복 억제 창 (초)
_MEMO_ATTR = "_repeat_suppress_decision"  # 레코드당 판정을 1회로 고정하는 표식

# 메시지를 묶기 위해 지워낼 가변 부분 (URL, 숫자).
# 실패 URL 마다 새 줄이 남으면 억제가 무의미해진다.
_URL_RE = re.compile(r"https?://\S+")
_NUM_RE = re.compile(r"\d+")


def _fingerprint(record: logging.LogRecord) -> Tuple[str, int, str]:
    """반복 판정 키. URL·숫자를 지워 같은 «종류»의 메시지를 한 덩어리로 본다."""
    message = record.getMessage()
    normalized = _NUM_RE.sub("#", _URL_RE.sub("<url>", message))
    return (record.name, record.levelno, normalized)


class RepeatSuppressFilter(logging.Filter):
    """같은 종류의 메시지가 창 안에서 반복되면 첫 줄만 남긴다.

    창이 지난 뒤 같은 메시지가 다시 오면 통과시키되, 그동안 생략된
    건수를 메시지 뒤에 덧붙여 «무엇이 얼마나 사라졌는지»를 남긴다.

    억제 대상은 WARNING/ERROR 뿐이다. INFO/DEBUG(정상 진행 흐름)와
    CRITICAL 은 반복이라도 그대로 통과시킨다.
    """

    def __init__(self, window: float = SUPPRESS_WINDOW,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self._window = window
        self._clock = clock
        self._lock = threading.Lock()
        # fingerprint -> (창 시작 시각, 생략 건수)
        self._seen: Dict[Tuple[str, int, str], Tuple[float, int]] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        # 같은 필터 인스턴스가 여러 핸들러에 걸리므로, 레코드 하나에 대한
        # 판정은 «한 번»만 내리고 이후 호출은 그 결과를 그대로 돌려준다.
        # (핸들러마다 새로 세면 생략 건수가 핸들러 수만큼 부풀려진다)
        memo = getattr(record, _MEMO_ATTR, None)
        if memo is not None:
            return memo
        decision = self._decide(record)
        setattr(record, _MEMO_ATTR, decision)
        return decision

    def _decide(self, record: logging.LogRecord) -> bool:
        # 억제는 WARNING/ERROR 에만 건다.
        # INFO/DEBUG 는 정상 진행 흐름이라 삼키면 로그를 못 읽고,
        # CRITICAL 은 반복이라도 반드시 남겨야 한다.
        if not logging.WARNING <= record.levelno <= logging.ERROR:
            return True

        key = _fingerprint(record)
        now = self._clock()

        with self._lock:
            entry = self._seen.get(key)
            if entry is None or now - entry[0] > self._window:
                suppressed = entry[1] if entry is not None else 0
                self._seen[key] = (now, 0)
                if suppressed:
                    record.msg = f"{record.getMessage()} (같은 메시지 {suppressed}회 생략)"
                    record.args = None
                return True

            started_at, suppressed = entry
            self._seen[key] = (started_at, suppressed + 1)
            return False


def setup_logging(
    log_file: str = DEFAULT_LOG_FILE,
    level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    console: bool = True,
    suppress_repeats: bool = True,
) -> None:
    """루트 로거를 설정한다. 여러 번 불러도 핸들러가 중복되지 않는다.

    Args:
        log_file:         로그 파일 경로
        level:            로그 레벨
        max_bytes:        파일 하나의 최대 크기
        backup_count:     보관할 롤오버 백업 개수
        console:          stdout 에도 출력할지
        suppress_repeats: 반복 메시지 억제 필터를 붙일지
    """
    root = logging.getLogger()

    # 기존 핸들러를 걷어낸다 (중복 append 방지)
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    root.setLevel(level)
    formatter = logging.Formatter(DEFAULT_FORMAT)
    repeat_filter = RepeatSuppressFilter() if suppress_repeats else None

    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    if repeat_filter is not None:
        file_handler.addFilter(repeat_filter)
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        if repeat_filter is not None:
            console_handler.addFilter(repeat_filter)
        root.addHandler(console_handler)

