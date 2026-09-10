"""HTTP 요청 가드: 회로 차단기 · 실패 URL 캐시 · 적응형 딜레이.

크롤러가 막힌 사이트를 계속 두드려 시간 예산을 태우는 것을 막는다.
- is_retryable_status: 재시도해도 안 바뀌는 상태코드를 걸러낸다
- FailedUrlCache:     403/404 난 URL 을 TTL 동안 기억해 재요청을 막는다
- CircuitBreaker:     연속 실패가 임계에 닿으면 남은 요청을 즉시 포기한다
- AdaptiveDelay:      429 를 맞으면 요청 간격을 늘리고, 성공이 이어지면 되돌린다

시간은 모두 주입 가능한 clock 으로 다룬다 (테스트에서 sleep 없이 제어).
"""

import threading
import time
from typing import Callable, Dict

# 재시도해도 결과가 바뀌지 않는 상태코드.
# 인증/권한/부재 계열이라 같은 요청을 반복해봐야 같은 응답만 돌아온다.
PERMANENT_STATUS = frozenset({401, 403, 404, 410, 451})


def is_retryable_status(status: int) -> bool:
    """이 상태코드를 재시도할 가치가 있는가."""
    return status not in PERMANENT_STATUS


class CircuitOpen(Exception):
    """회로가 열려 요청이 거부되었음을 알린다."""


class FailedUrlCache:
    """영구 실패한 URL 을 TTL 동안 기억한다.

    프로세스 메모리에만 둔다. 재시작하면 초기화되는 것이 의도된 동작으로,
    사이트가 복구되었을 때 자동으로 다시 시도하게 된다.
    """

    def __init__(self, ttl: float = 21600, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl
        self._clock = clock
        self._blocked: Dict[str, float] = {}
        self._lock = threading.Lock()

    def record(self, url: str) -> None:
        """URL 을 실패로 기록한다."""
        with self._lock:
            self._blocked[url] = self._clock()

    def is_blocked(self, url: str) -> bool:
        """이 URL 이 아직 차단 중인가."""
        with self._lock:
            recorded_at = self._blocked.get(url)
            if recorded_at is None:
                return False
            if self._clock() - recorded_at > self._ttl:
                del self._blocked[url]
                return False
            return True

    def purge_expired(self) -> int:
        """만료된 항목을 지운다. 지운 개수를 반환한다."""
        now = self._clock()
        with self._lock:
            expired = [u for u, at in self._blocked.items() if now - at > self._ttl]
            for url in expired:
                del self._blocked[url]
            return len(expired)

    def __len__(self) -> int:
        with self._lock:
            return len(self._blocked)


class CircuitBreaker:
    """소스 단위 회로 차단기.

    «연속» 실패만 센다. 성공이 한 번이라도 끼면 카운터가 초기화되므로,
    부분적으로만 막힌 소스(예: 유료 기사만 403 인 한국경제)의
    정상 수집분까지 죽이지 않는다.

    상태 전이: closed --(연속 실패 threshold 회)--> open
               open   --(cooldown 경과)-----------> half_open (시험 1건만 허용)
               half_open --(성공)-----------------> closed
               half_open --(실패)-----------------> open (쿨다운 재시작)
    """

    def __init__(
        self,
        threshold: int = 5,
        cooldown: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._threshold = threshold
        self._cooldown = cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self._state = "closed"
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._probe_taken = False

    @property
    def state(self) -> str:
        """현재 상태 ('closed' | 'open' | 'half_open')."""
        with self._lock:
            return self._state

    def allows_request(self) -> bool:
        """지금 요청을 보내도 되는가.

        열린 상태에서 쿨다운이 지났다면 half_open 으로 넘어가며
        시험용 요청 «1건»만 허용한다.
        """
        with self._lock:
            if self._state == "closed":
                return True

            if self._state == "open":
                if self._clock() - self._opened_at < self._cooldown:
                    return False
                self._state = "half_open"
                self._probe_taken = True
                return True

            # half_open: 시험용 1건이 이미 나갔으면 더 보내지 않는다
            if self._probe_taken:
                return False
            self._probe_taken = True
            return True

    def guard(self) -> None:
        """요청 직전에 부른다. 회로가 열려 있으면 CircuitOpen 을 던진다."""
        if not self.allows_request():
            raise CircuitOpen(f"회로 열림 (연속 실패 {self._consecutive_failures}회)")

    def reset(self) -> None:
        """사이클 경계에서 회로를 원상복구한다.

        쿨다운을 끝까지 기다리느라 소스를 통째로 잃지 않도록,
        매 수집 사이클마다 새 기회를 준다.
        """
        with self._lock:
            self._state = "closed"
            self._consecutive_failures = 0
            self._opened_at = 0.0
            self._probe_taken = False

    def record_success(self) -> None:
        """성공을 기록한다. 연속 실패 카운터가 초기화되고 회로가 닫힌다."""
        with self._lock:
            self._consecutive_failures = 0
            self._state = "closed"
            self._probe_taken = False

    def record_failure(self) -> None:
        """실패를 기록한다. 임계에 닿으면 회로를 연다."""
        with self._lock:
            if self._state == "half_open":
                # 시험 요청이 실패 - 다시 열고 쿨다운을 재시작한다
                self._state = "open"
                self._opened_at = self._clock()
                self._probe_taken = False
                return

            self._consecutive_failures += 1
            if self._consecutive_failures >= self._threshold:
                self._state = "open"
                self._opened_at = self._clock()
                self._probe_taken = False


class AdaptiveDelay:
    """429 응답에 반응해 요청 간격을 조절한다.

    고정 간격으로 계속 두드리면 429 를 자초한다. 맞으면 물러서고,
    성공이 recover_after 회 쌓이면 절반으로 되돌린다.
    """

    def __init__(self, base: float = 1.0, maximum: float = 8.0, recover_after: int = 5):
        self._base = base
        self._maximum = maximum
        self._recover_after = recover_after
        self._current = base
        self._successes = 0
        self._lock = threading.Lock()

    def current(self) -> float:
        """지금 적용할 요청 간격(초)."""
        with self._lock:
            return self._current

    def penalize(self) -> None:
        """429 를 맞았다. 간격을 두 배로 늘린다 (상한까지)."""
        with self._lock:
            self._current = min(self._current * 2, self._maximum)
            self._successes = 0

    def reward(self) -> None:
        """성공했다. 충분히 쌓이면 간격을 절반으로 되돌린다 (기본값까지)."""
        with self._lock:
            if self._current <= self._base:
                self._successes = 0
                return
            self._successes += 1
            if self._successes >= self._recover_after:
                self._current = max(self._current / 2, self._base)
                self._successes = 0
