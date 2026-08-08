"""HTTP 层：httpx client + 注入式限速器 + tenacity 退避 + 熔断器。

硬性约束（goal 限速红线，见 tasks/003）：
- 默认 ≤1 次/2 秒（RateLimiter interval=2.0，测试可传 0）；连续出错自动降速到 5 秒/请求。
- 指数退避最多重试 3 次，仅对瞬时错误（网络错误 / HTTP 5xx）重试。
- 连续 5 次失败、HTTP 403、或响应非 JSON（疑似验证码/封禁页）→ CircuitOpenError，
  立即中止本轮运行，绝不硬闯。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

DEFAULT_USER_AGENT = (
    "ptcg-cn-db/0.1 (+https://github.com/Bingtuu/ptcg-cn-db; non-commercial research)"
)

DEFAULT_INTERVAL = 2.0  # 正常限速：1 次/2 秒
SLOW_INTERVAL = 5.0  # 连续出错后的降速：1 次/5 秒
MAX_ATTEMPTS = 3  # 指数退避最多重试 3 次
MAX_CONSECUTIVE_FAILURES = 5  # 连续 5 次失败熔断


class CircuitOpenError(RuntimeError):
    """熔断器断开：疑似被封禁/验证码/持续故障，必须立即中止本轮运行。"""


class TransientHttpError(RuntimeError):
    """可重试的瞬时错误（网络错误 / HTTP 5xx），重试耗尽后向上抛。"""


class RateLimiter:
    """注入式限速器：clock / sleep 可替换，测试传假时钟或 interval=0。"""

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL,
        slow_interval: float = SLOW_INTERVAL,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self.slow_interval = slow_interval
        self._clock = clock
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._consecutive_errors = 0

    @property
    def current_interval(self) -> float:
        """连续出错期间使用降速间隔，成功后恢复正常间隔。"""
        return self.slow_interval if self._consecutive_errors > 0 else self.interval

    def wait(self) -> None:
        """阻塞到距离上次请求满足当前间隔为止。"""
        if self._last_request_at is not None:
            delay = self._last_request_at + self.current_interval - self._clock()
            if delay > 0:
                self._sleep(delay)
        self._last_request_at = self._clock()

    def report_success(self) -> None:
        self._consecutive_errors = 0

    def report_error(self) -> None:
        self._consecutive_errors += 1


class HttpClient:
    """带限速/退避/熔断的 JSON 客户端（POST/GET 共用同一套限速/退避/熔断语义）。"""

    def __init__(
        self,
        base_url: str,
        *,
        rate_limiter: RateLimiter | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        max_attempts: int = MAX_ATTEMPTS,
        max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES,
        retry_wait: Any | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": user_agent},
            transport=transport,
            timeout=timeout,
        )
        self._limiter = rate_limiter or RateLimiter()
        self._max_attempts = max_attempts
        self._max_consecutive_failures = max_consecutive_failures
        # 测试传 wait_none() 避免真实退避等待
        self._retry_wait = (
            retry_wait if retry_wait is not None else wait_exponential(multiplier=1, min=1, max=10)
        )
        self._consecutive_failures = 0

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        """POST JSON，返回解析后的响应体。熔断条件满足时抛 CircuitOpenError。"""
        return self._request(lambda: self._client.post(path, json=payload))

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET JSON，返回解析后的响应体。限速/退避/熔断语义与 post_json 完全一致。"""
        return self._request(lambda: self._client.get(path, params=params))

    def _request(self, send: Callable[[], httpx.Response]) -> Any:
        """一次请求的完整生命周期：熔断闸 → 退避重试 → 成功/失败计数。"""
        if self._consecutive_failures >= self._max_consecutive_failures:
            raise CircuitOpenError(
                f"连续 {self._consecutive_failures} 次请求失败，熔断中止，请人工确认数据源状态"
            )
        try:
            body = self._with_retry(send)
        except CircuitOpenError:
            raise
        except Exception:
            self._consecutive_failures += 1
            self._limiter.report_error()
            raise
        self._consecutive_failures = 0
        self._limiter.report_success()
        return body

    def _with_retry(self, send: Callable[[], httpx.Response]) -> Any:
        retryer = Retrying(
            retry=retry_if_exception_type(TransientHttpError),
            stop=stop_after_attempt(self._max_attempts),
            wait=self._retry_wait,
            reraise=True,
        )
        for attempt in retryer:
            with attempt:
                return self._once(send)
        raise TransientHttpError("unreachable")  # pragma: no cover

    def _once(self, send: Callable[[], httpx.Response]) -> Any:
        self._limiter.wait()
        try:
            resp = send()
        except httpx.TransportError as exc:
            raise TransientHttpError(f"网络错误: {exc}") from exc
        if resp.status_code == 403:
            raise CircuitOpenError("HTTP 403，疑似触发封禁/风控，熔断中止")
        if resp.status_code >= 500:
            raise TransientHttpError(f"HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise CircuitOpenError(
                f"响应非 JSON（HTTP {resp.status_code}），疑似验证码/封禁页，熔断中止"
            ) from exc
