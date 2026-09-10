"""로깅 설정(로테이션·반복 억제) 테스트."""
import logging
from pathlib import Path

import pytest

from news_scraper.logging_setup import RepeatSuppressFilter, setup_logging


@pytest.fixture
def clean_root():
    """루트 로거를 테스트 전후로 원상복구한다."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers = []
    yield root
    for handler in root.handlers:
        handler.close()
    root.handlers = saved_handlers
    root.level = saved_level


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


# --------------------------------------------------------------------------
# setup_logging — 파일이 무한히 자라지 않아야 한다
# --------------------------------------------------------------------------

def test_로그_파일이_maxBytes를_넘으면_롤오버된다(clean_root, tmp_path):
    log_file = tmp_path / "test.log"
    setup_logging(log_file=str(log_file), max_bytes=2000, backup_count=2, console=False)
    logger = logging.getLogger("rollover_probe")

    for i in range(200):
        logger.info("가나다라마바사아자차카타파하 %d", i)

    assert log_file.with_suffix(".log.1").exists()


def test_백업_개수가_상한을_넘지_않는다(clean_root, tmp_path):
    log_file = tmp_path / "test.log"
    setup_logging(log_file=str(log_file), max_bytes=1000, backup_count=2, console=False)
    logger = logging.getLogger("backup_cap_probe")

    for i in range(2000):
        logger.info("가나다라마바사아자차카타파하 %d", i)

    rotated = sorted(Path(tmp_path).glob("test.log.*"))
    assert len(rotated) == 2


def test_setup_logging을_두_번_불러도_핸들러가_중복되지_않는다(clean_root, tmp_path):
    """main.py / run_scheduler.py / run_api.py 가 한 프로세스에서 겹쳐 부를 수 있다."""
    log_file = tmp_path / "test.log"

    setup_logging(log_file=str(log_file), console=False)
    setup_logging(log_file=str(log_file), console=False)

    assert len(clean_root.handlers) == 1


def test_로그_파일에_한글이_깨지지_않고_기록된다(clean_root, tmp_path):
    log_file = tmp_path / "test.log"
    setup_logging(log_file=str(log_file), console=False)

    logging.getLogger("encoding_probe").info("한글 로그 기록 확인")

    for handler in clean_root.handlers:
        handler.flush()
    assert "한글 로그 기록 확인" in log_file.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# RepeatSuppressFilter — 같은 메시지가 창 안에서 반복되면 한 줄만 남긴다
# --------------------------------------------------------------------------

def _record(msg: str, name: str = "news_scraper.base_crawler",
            level: int = logging.WARNING) -> logging.LogRecord:
    return logging.LogRecord(name, level, "x.py", 1, msg, None, None)


def test_창_안의_첫_메시지는_통과한다():
    filt = RepeatSuppressFilter(window=60, clock=FakeClock())

    assert filt.filter(_record("[hankyung] 429 에러 발생")) is True


def test_창_안에서_같은_메시지가_반복되면_막힌다():
    filt = RepeatSuppressFilter(window=60, clock=FakeClock())
    filt.filter(_record("[hankyung] 429 에러 발생"))

    assert filt.filter(_record("[hankyung] 429 에러 발생")) is False


def test_창이_지나면_다시_통과한다():
    clock = FakeClock()
    filt = RepeatSuppressFilter(window=60, clock=clock)
    filt.filter(_record("[hankyung] 429 에러 발생"))

    clock.advance(61)

    assert filt.filter(_record("[hankyung] 429 에러 발생")) is True


def test_창이_지나_다시_통과할_때_생략된_건수가_메시지에_붙는다():
    clock = FakeClock()
    filt = RepeatSuppressFilter(window=60, clock=clock)
    filt.filter(_record("[hankyung] 429 에러 발생"))
    for _ in range(99):
        filt.filter(_record("[hankyung] 429 에러 발생"))

    clock.advance(61)
    record = _record("[hankyung] 429 에러 발생")
    filt.filter(record)

    assert "99회 생략" in record.getMessage()


def test_생략된_것이_없으면_요약이_붙지_않는다():
    clock = FakeClock()
    filt = RepeatSuppressFilter(window=60, clock=clock)
    filt.filter(_record("[hankyung] 429 에러 발생"))

    clock.advance(61)
    record = _record("[hankyung] 429 에러 발생")
    filt.filter(record)

    assert "생략" not in record.getMessage()


def test_다른_메시지는_서로_영향을_주지_않는다():
    filt = RepeatSuppressFilter(window=60, clock=FakeClock())
    filt.filter(_record("[hankyung] 429 에러 발생"))

    assert filt.filter(_record("[mk_news] 429 에러 발생")) is True


def test_URL과_숫자만_다른_메시지는_같은_것으로_묶인다():
    """실패 URL 마다 새 줄이 남으면 억제가 무의미해진다."""
    filt = RepeatSuppressFilter(window=60, clock=FakeClock())
    filt.filter(_record("[hankyung] 최종 실패: https://www.hankyung.com/article/1111"))

    blocked = filt.filter(
        _record("[hankyung] 최종 실패: https://www.hankyung.com/article/2222")
    )

    assert blocked is False


def test_ERROR보다_높은_레벨은_억제하지_않는다():
    """CRITICAL 은 반복이라도 삼키면 안 된다."""
    filt = RepeatSuppressFilter(window=60, clock=FakeClock())
    filt.filter(_record("치명적 오류", level=logging.CRITICAL))

    assert filt.filter(_record("치명적 오류", level=logging.CRITICAL)) is True


def test_같은_메시지라도_로거가_다르면_따로_센다():
    filt = RepeatSuppressFilter(window=60, clock=FakeClock())
    filt.filter(_record("타임아웃", name="news_scraper.base_crawler"))

    assert filt.filter(_record("타임아웃", name="news_scraper.scheduler")) is True


# --------------------------------------------------------------------------
# 통합 — 필터가 «실제 크롤러 로거»의 폭주를 잡아야 한다
# --------------------------------------------------------------------------

def _count_lines(log_file: Path) -> int:
    return len([ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()])


def test_자식_로거의_반복_메시지가_파일에서_억제된다(clean_root, tmp_path):
    """로거에 건 필터는 전파된 레코드에 적용되지 않는다 - 핸들러에 걸어야 한다."""
    log_file = tmp_path / "test.log"
    setup_logging(log_file=str(log_file), console=False)
    crawler_logger = logging.getLogger("news_scraper.base_crawler")

    for _ in range(500):
        crawler_logger.warning("[hankyung] 429 에러 발생, 1.0초 대기 후 재시도...")

    for handler in clean_root.handlers:
        handler.flush()
    assert _count_lines(log_file) == 1


def test_콘솔_핸들러가_있어도_억제_카운트가_두_배가_되지_않는다(clean_root, tmp_path, capsys):
    """핸들러마다 필터를 걸면 같은 레코드를 두 번 세어 생략 건수가 어긋난다."""
    log_file = tmp_path / "test.log"
    setup_logging(log_file=str(log_file), console=True)
    crawler_logger = logging.getLogger("news_scraper.base_crawler")

    for _ in range(10):
        crawler_logger.warning("[hankyung] 429 에러 발생")

    for handler in clean_root.handlers:
        handler.flush()
    assert _count_lines(log_file) == 1
    assert len([ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]) == 1


def test_서로_다른_소스의_경고는_각각_한_줄씩_남는다(clean_root, tmp_path):
    log_file = tmp_path / "test.log"
    setup_logging(log_file=str(log_file), console=False)
    crawler_logger = logging.getLogger("news_scraper.base_crawler")

    for _ in range(50):
        crawler_logger.warning("[hankyung] 429 에러 발생")
        crawler_logger.warning("[mk_news] 429 에러 발생")

    for handler in clean_root.handlers:
        handler.flush()
    assert _count_lines(log_file) == 2


def test_INFO_로그는_반복되어도_억제하지_않는다():
    """폭주는 전부 WARNING/ERROR 다. 정상 진행 로그까지 삼키면 흐름을 못 읽는다."""
    filt = RepeatSuppressFilter(window=60, clock=FakeClock())
    filt.filter(_record("[hankyung] 크롤링 시작...", level=logging.INFO))

    assert filt.filter(_record("[hankyung] 크롤링 시작...", level=logging.INFO)) is True


def test_사이클_요약_INFO는_매_사이클_남는다(clean_root, tmp_path):
    log_file = tmp_path / "test.log"
    setup_logging(log_file=str(log_file), console=False)
    logger = logging.getLogger("news_scraper.scheduler")

    for _ in range(5):
        logger.info("[hankyung] 요청 45 · 성공 12 · 429 27 · 403 6")

    for handler in clean_root.handlers:
        handler.flush()
    assert _count_lines(log_file) == 5
