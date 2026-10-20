"""HTTP client for the sports data sources, with polite throttling and retries.

Two kinds of call share one throttle and one retry policy:

* `call(endpoint, **params)` instantiates an nba_api endpoint class (stats.nba.com);
* `get_json(url, params)` is a plain GET used for ESPN's public JSON.

Sources throttle aggressively and occasionally return HTML or empty bodies instead of
JSON. Every call is spaced by at least `min_interval_s`, and transient failures
(network errors, timeouts, HTTP 429/5xx, unparseable JSON) are retried with exponential
backoff plus jitter. Other 4xx responses are not retried: they will not get better.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any, Protocol

import requests

log = logging.getLogger(__name__)


class Endpoint(Protocol):
    """The subset of the nba_api endpoint interface we rely on."""

    def get_dict(self) -> dict[str, Any]: ...


EndpointFactory = Callable[..., Endpoint]
HttpGet = Callable[..., requests.Response]

RETRYABLE: tuple[type[Exception], ...] = (requests.RequestException, ValueError)
USER_AGENT = "nba-pipeline/0.1 (+https://github.com/JayJaden06/nba-data-pipeline)"


class NbaApiError(RuntimeError):
    """Raised after retries are exhausted, or on a non-retryable HTTP error."""


class ApiClient(Protocol):
    """What the sources need from a client; satisfied by NbaApiClient and test fakes."""

    def call(self, endpoint: EndpointFactory, **params: Any) -> dict[str, Any]: ...

    def get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]: ...


class NbaApiClient:
    def __init__(
        self,
        *,
        min_interval_s: float = 0.6,
        max_retries: int = 5,
        timeout_s: int = 30,
        base_backoff_s: float = 1.0,
        max_backoff_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
        http_get: HttpGet = requests.get,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self.base_backoff_s = base_backoff_s
        self.max_backoff_s = max_backoff_s
        self._sleep = sleep
        self._clock = clock
        self._rng = rng or random.Random()
        self._last_call_at: float | None = None
        self._http_get = http_get

    def call(self, endpoint: EndpointFactory, **params: Any) -> dict[str, Any]:
        """Instantiate `endpoint(**params, timeout=...)` and return its raw dict payload."""
        name = getattr(endpoint, "__name__", repr(endpoint))
        return self._with_retries(
            name, lambda: endpoint(**params, timeout=self.timeout_s).get_dict()
        )

    def get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        """GET `url` and return the decoded JSON object."""

        def fetch() -> Any:
            resp = self._http_get(
                url,
                params=params,
                timeout=self.timeout_s,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                resp.raise_for_status()  # HTTPError is a RequestException: retried
            if resp.status_code >= 400:
                raise NbaApiError(f"GET {url} {params} -> HTTP {resp.status_code}")
            return resp.json()

        return self._with_retries(url.rsplit("/", 1)[-1], fetch)

    def _with_retries(self, name: str, fetch: Callable[[], Any]) -> dict[str, Any]:
        attempt = 0
        while True:
            self._throttle()
            try:
                payload = fetch()
                if not isinstance(payload, dict):
                    raise ValueError(f"{name} returned non-dict payload: {type(payload)}")
                return payload
            except RETRYABLE as exc:
                attempt += 1
                if attempt > self.max_retries:
                    raise NbaApiError(f"{name} failed after {attempt} attempts: {exc}") from exc
                delay = self._backoff(attempt)
                log.warning(
                    "%s attempt %d/%d failed (%s); retrying in %.1fs",
                    name,
                    attempt,
                    self.max_retries,
                    exc,
                    delay,
                )
                self._sleep(delay)

    def _throttle(self) -> None:
        now = self._clock()
        if self._last_call_at is not None:
            wait = self.min_interval_s - (now - self._last_call_at)
            if wait > 0:
                self._sleep(wait)
        self._last_call_at = self._clock()

    def _backoff(self, attempt: int) -> float:
        raw: float = min(self.max_backoff_s, self.base_backoff_s * (2 ** (attempt - 1)))
        jitter: float = 0.5 + self._rng.random()
        return raw * jitter  # jitter between 0.5x and 1.5x
