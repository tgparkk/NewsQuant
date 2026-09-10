"""HTTP 가드(회로 차단기·실패 URL 캐시·적응형 딜레이) 테스트.

네트워크를 타지 않는다. 시간은 주입한 clock 으로 제어한다.
"""
import pytest

from news_scraper.http_guard import (
    AdaptiveDelay,
    CircuitBreaker,
    CircuitOpen,
    FailedUrlCache,
    is_retryable_status,
)


class FakeClock:
    """단조 시계 대역. now() 가 반환할 값을 테스트가 직접 민다."""

    def __init__(self, start: float = 1000.0):
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


# --------------------------------------------------------------------------
# is_retryable_status — 재시도해도 안 바뀌는 코드를 걸러낸다
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", [403, 404, 410, 401, 451])
def test_영구_실패_상태코드는_재시도하지_않는다(status):
    assert is_retryable_status(status) is False


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_일시적_실패_상태코드는_재시도한다(status):
    assert is_retryable_status(status) is True


# --------------------------------------------------------------------------
# FailedUrlCache — 403/404 난 URL 을 TTL 동안 기억해 재요청을 막는다
# --------------------------------------------------------------------------

def test_기록한_URL은_TTL_안에서_차단된다():
    clock = FakeClock()
    cache = FailedUrlCache(ttl=3600, clock=clock)

    cache.record("https://www.hankyung.com/premium9/0101003")

    assert cache.is_blocked("https://www.hankyung.com/premium9/0101003") is True


def test_기록하지_않은_URL은_차단되지_않는다():
    cache = FailedUrlCache(ttl=3600, clock=FakeClock())

    assert cache.is_blocked("https://www.hankyung.com/economy?page=1") is False


def test_TTL이_지나면_차단이_풀린다():
    clock = FakeClock()
    cache = FailedUrlCache(ttl=3600, clock=clock)
    cache.record("https://www.hankyung.com/premium9/0101003")

    clock.advance(3601)

    assert cache.is_blocked("https://www.hankyung.com/premium9/0101003") is False


def test_TTL_경계에서는_아직_차단된다():
    clock = FakeClock()
    cache = FailedUrlCache(ttl=3600, clock=clock)
    cache.record("https://www.hankyung.com/premium9/0101003")

    clock.advance(3600)

    assert cache.is_blocked("https://www.hankyung.com/premium9/0101003") is True


def test_만료된_항목은_정리되어_메모리에_쌓이지_않는다():
    clock = FakeClock()
    cache = FailedUrlCache(ttl=60, clock=clock)
    for i in range(100):
        cache.record(f"https://example.com/{i}")

    clock.advance(61)
    cache.purge_expired()

    assert len(cache) == 0


# --------------------------------------------------------------------------
# CircuitBreaker — 연속 실패가 임계에 닿으면 OPEN, 쿨다운 뒤 half-open
# --------------------------------------------------------------------------

def test_초기_상태는_닫힘이라_요청이_통과한다():
    breaker = CircuitBreaker(threshold=5, cooldown=300, clock=FakeClock())

    assert breaker.allows_request() is True
    assert breaker.state == "closed"


def test_연속_실패가_임계에_닿으면_열린다():
    breaker = CircuitBreaker(threshold=5, cooldown=300, clock=FakeClock())

    for _ in range(5):
        breaker.record_failure()

    assert breaker.state == "open"
    assert breaker.allows_request() is False


def test_임계_직전까지는_열리지_않는다():
    breaker = CircuitBreaker(threshold=5, cooldown=300, clock=FakeClock())

    for _ in range(4):
        breaker.record_failure()

    assert breaker.state == "closed"
    assert breaker.allows_request() is True


def test_성공하면_연속_실패_카운터가_초기화된다():
    """한경처럼 부분적으로만 막힌 소스가 정상분까지 죽지 않게 하는 핵심 동작."""
    breaker = CircuitBreaker(threshold=5, cooldown=300, clock=FakeClock())

    for _ in range(4):
        breaker.record_failure()
    breaker.record_success()
    for _ in range(4):
        breaker.record_failure()

    assert breaker.state == "closed"


def test_쿨다운이_지나면_half_open_으로_한_건을_허용한다():
    clock = FakeClock()
    breaker = CircuitBreaker(threshold=2, cooldown=300, clock=clock)
    breaker.record_failure()
    breaker.record_failure()

    clock.advance(301)

    assert breaker.allows_request() is True
    assert breaker.state == "half_open"


def test_half_open_에서는_두_번째_요청을_막는다():
    clock = FakeClock()
    breaker = CircuitBreaker(threshold=2, cooldown=300, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.advance(301)

    breaker.allows_request()  # 시험용 1건 소진

    assert breaker.allows_request() is False


def test_half_open_에서_성공하면_닫힌다():
    clock = FakeClock()
    breaker = CircuitBreaker(threshold=2, cooldown=300, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.advance(301)
    breaker.allows_request()

    breaker.record_success()

    assert breaker.state == "closed"
    assert breaker.allows_request() is True


def test_half_open_에서_실패하면_다시_열리고_쿨다운이_재시작된다():
    clock = FakeClock()
    breaker = CircuitBreaker(threshold=2, cooldown=300, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.advance(301)
    breaker.allows_request()

    breaker.record_failure()

    assert breaker.state == "open"
    clock.advance(299)
    assert breaker.allows_request() is False
    clock.advance(2)
    assert breaker.allows_request() is True


def test_열린_차단기는_guard_호출_시_CircuitOpen_을_던진다():
    breaker = CircuitBreaker(threshold=1, cooldown=300, clock=FakeClock())
    breaker.record_failure()

    with pytest.raises(CircuitOpen):
        breaker.guard()


# --------------------------------------------------------------------------
# AdaptiveDelay — 429 를 맞으면 요청 간격을 늘리고, 성공이 이어지면 되돌린다
# --------------------------------------------------------------------------

def test_초기_딜레이는_기본값이다():
    delay = AdaptiveDelay(base=1.0, maximum=8.0)

    assert delay.current() == 1.0


def test_429를_맞으면_딜레이가_두_배가_된다():
    delay = AdaptiveDelay(base=1.0, maximum=8.0)

    delay.penalize()

    assert delay.current() == 2.0


def test_딜레이는_상한을_넘지_않는다():
    delay = AdaptiveDelay(base=1.0, maximum=8.0)

    for _ in range(10):
        delay.penalize()

    assert delay.current() == 8.0


def test_성공이_이어지면_딜레이가_점차_줄어든다():
    delay = AdaptiveDelay(base=1.0, maximum=8.0, recover_after=3)
    delay.penalize()
    delay.penalize()  # 4.0

    for _ in range(3):
        delay.reward()

    assert delay.current() == 2.0


def test_성공이_충분히_쌓이지_않으면_딜레이가_유지된다():
    delay = AdaptiveDelay(base=1.0, maximum=8.0, recover_after=3)
    delay.penalize()

    delay.reward()
    delay.reward()

    assert delay.current() == 2.0


def test_딜레이는_기본값_아래로는_내려가지_않는다():
    delay = AdaptiveDelay(base=1.0, maximum=8.0, recover_after=1)

    for _ in range(10):
        delay.reward()

    assert delay.current() == 1.0


def test_reset하면_닫힌_상태로_돌아간다():
    """사이클 경계에서 새 기회를 준다 - 쿨다운을 기다리며 소스를 통째로 잃지 않게."""
    clock = FakeClock()
    breaker = CircuitBreaker(threshold=2, cooldown=300, clock=clock)
    breaker.record_failure()
    breaker.record_failure()

    breaker.reset()

    assert breaker.state == "closed"
    assert breaker.allows_request() is True


def test_reset은_연속_실패_카운터도_비운다():
    breaker = CircuitBreaker(threshold=3, cooldown=300, clock=FakeClock())
    breaker.record_failure()
    breaker.record_failure()

    breaker.reset()
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state == "closed"
