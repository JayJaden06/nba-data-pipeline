import random
from typing import Any

import pytest
import requests

from nba_pipeline.ingest.client import NbaApiClient, NbaApiError


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.now += s


def make_client(clock: FakeClock, **kw: Any) -> NbaApiClient:
    return NbaApiClient(sleep=clock.sleep, clock=clock, rng=random.Random(0), **kw)


def test_throttle_spaces_calls() -> None:
    clock = FakeClock()
    client = make_client(clock, min_interval_s=0.6)
    calls: list[dict[str, Any]] = []

    class Endpoint:
        def __init__(self, **kw: Any) -> None:
            calls.append(kw)

        def get_dict(self) -> dict[str, Any]:
            return {"ok": True}

    client.call(Endpoint, game_date="2026-03-15")
    client.call(Endpoint, game_date="2026-03-16")
    assert clock.sleeps == [pytest.approx(0.6)]
    assert calls[0] == {"game_date": "2026-03-15", "timeout": 30}


def test_retries_then_succeeds() -> None:
    clock = FakeClock()
    client = make_client(clock, min_interval_s=0, max_retries=3, base_backoff_s=1.0)
    attempts = 0

    class Flaky:
        def __init__(self, **kw: Any) -> None:
            pass

        def get_dict(self) -> dict[str, Any]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise requests.Timeout("slow")
            if attempts == 2:
                raise ValueError("Expecting value: line 1 column 1")  # HTML instead of JSON
            return {"ok": True}

    assert client.call(Flaky) == {"ok": True}
    assert attempts == 3
    # two backoff sleeps, exponential (1s, 2s) with jitter in [0.5x, 1.5x]
    assert len(clock.sleeps) == 2
    assert 0.5 <= clock.sleeps[0] <= 1.5
    assert 1.0 <= clock.sleeps[1] <= 3.0


def test_gives_up_after_max_retries() -> None:
    clock = FakeClock()
    client = make_client(clock, min_interval_s=0, max_retries=2)

    class Broken:
        def __init__(self, **kw: Any) -> None:
            pass

        def get_dict(self) -> dict[str, Any]:
            raise requests.ConnectionError("nope")

    with pytest.raises(NbaApiError, match="after 3 attempts"):
        client.call(Broken)


def test_non_retryable_errors_propagate() -> None:
    client = make_client(FakeClock(), min_interval_s=0)

    class Bug:
        def __init__(self, **kw: Any) -> None:
            pass

        def get_dict(self) -> dict[str, Any]:
            raise KeyError("programming error")

    with pytest.raises(KeyError):
        client.call(Bug)


class FakeResponse:
    def __init__(self, status: int, body: Any = None) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    def raise_for_status(self) -> None:
        raise requests.HTTPError(f"HTTP {self.status_code}")


def test_get_json_retries_5xx_and_bad_json_then_succeeds() -> None:
    responses = [
        FakeResponse(503),
        FakeResponse(200, ValueError("not json")),
        FakeResponse(200, {"ok": 1}),
    ]
    seen: list[dict[str, Any]] = []

    def http_get(url: str, **kw: Any) -> FakeResponse:
        seen.append({"url": url, **kw})
        return responses.pop(0)

    clock = FakeClock()
    client = NbaApiClient(
        sleep=clock.sleep, clock=clock, rng=random.Random(0), min_interval_s=0, http_get=http_get
    )  # type: ignore[arg-type]
    assert client.get_json("https://x/scoreboard", {"dates": "20260315"}) == {"ok": 1}
    assert len(seen) == 3 and len(clock.sleeps) == 2
    assert seen[0]["params"] == {"dates": "20260315"}
    assert seen[0]["headers"]["User-Agent"].startswith("nba-pipeline/")


def test_get_json_does_not_retry_404() -> None:
    calls = 0

    def http_get(url: str, **kw: Any) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse(404)

    clock = FakeClock()
    client = NbaApiClient(sleep=clock.sleep, clock=clock, min_interval_s=0, http_get=http_get)  # type: ignore[arg-type]
    with pytest.raises(NbaApiError, match="HTTP 404"):
        client.get_json("https://x/summary", {"event": "1"})
    assert calls == 1
