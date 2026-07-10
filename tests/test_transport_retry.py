import io
import urllib.error
from email.message import Message

import pytest

from dida_v2_client.config import DidaConfig
from dida_v2_client.transport import DidaV2Client, DidaV2Error, DidaV2HTTPError


class FakeResponse:
    def __init__(self, body=b"{}"):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def http_error(req, status, *, retry_after=None, body=b"{}"):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(req.full_url, status, "transient", headers, io.BytesIO(body))


def client_with_retry(*, sleeps, jitter=lambda delay: delay):
    return DidaV2Client(
        DidaConfig.for_profile("dida"),
        session_token="TOKEN_A",
        max_read_attempts=3,
        retry_backoff_seconds=0.25,
        sleep=sleeps.append,
        jitter=jitter,
    )


def test_get_retries_retryable_http_with_retry_after(monkeypatch):
    sleeps = []
    client = client_with_retry(sleeps=sleeps)
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise http_error(req, 503, retry_after="2")
        return FakeResponse(b'{"ok":true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert client.request("GET", "/status") == {"ok": True}
    assert len(calls) == 2
    assert sleeps == [2.0]


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_get_retries_only_known_transient_http_statuses(monkeypatch, status):
    sleeps = []
    client = client_with_retry(sleeps=sleeps)
    attempts = 0

    def fake_urlopen(req, timeout):
        nonlocal attempts
        attempts += 1
        raise http_error(req, status)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(DidaV2HTTPError) as excinfo:
        client.request("GET", "/status")
    assert excinfo.value.status == status
    assert attempts == 3
    assert sleeps == [0.25, 0.5]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
def test_get_does_not_retry_non_transient_http_status(monkeypatch, status):
    sleeps = []
    client = client_with_retry(sleeps=sleeps)
    attempts = 0

    def fake_urlopen(req, timeout):
        nonlocal attempts
        attempts += 1
        raise http_error(req, status)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(DidaV2HTTPError) as excinfo:
        client.request("GET", "/status")
    assert excinfo.value.status == status
    assert attempts == 1
    assert sleeps == []


def test_get_retries_network_failures_with_secret_free_final_error(monkeypatch):
    sleeps = []
    client = client_with_retry(sleeps=sleeps)
    attempts = 0

    def fake_urlopen(req, timeout):
        nonlocal attempts
        attempts += 1
        raise urllib.error.URLError("network echoed TOKEN_A")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(DidaV2Error) as excinfo:
        client.request("GET", "/status")
    assert "TOKEN_A" not in str(excinfo.value)
    assert attempts == 3
    assert sleeps == [0.25, 0.5]


def test_write_is_never_retried_even_for_503(monkeypatch):
    sleeps = []
    client = client_with_retry(sleeps=sleeps)
    attempts = 0

    def fake_urlopen(req, timeout):
        nonlocal attempts
        attempts += 1
        raise http_error(req, 503, retry_after="1")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(DidaV2HTTPError):
        client.request("POST", "/batch/task", payload={"add": []})
    assert attempts == 1
    assert sleeps == []


def test_head_is_treated_as_safe_read(monkeypatch):
    sleeps = []
    client = client_with_retry(sleeps=sleeps)
    attempts = 0

    def fake_urlopen(req, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.URLError("temporary")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert client.request("HEAD", "/status") == {}
    assert attempts == 2


def test_retry_keeps_call_start_identity_across_identity_change(monkeypatch):
    sleeps = []
    client = client_with_retry(sleeps=sleeps)
    seen = []

    def fake_urlopen(req, timeout):
        seen.append((req.full_url, req.headers.get("Cookie")))
        if len(seen) == 1:
            raise urllib.error.URLError("temporary")
        return FakeResponse()

    def change_identity_then_sleep(delay):
        sleeps.append(delay)
        client.set_identity(DidaConfig.for_profile("ticktick"), "TOKEN_B")

    client._sleep = change_identity_then_sleep
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert client.request("GET", "/status") == {}
    assert len(seen) == 2
    assert all(url.startswith("https://api.dida365.com/") for url, _ in seen)
    assert [cookie for _, cookie in seen] == ["t=TOKEN_A", "t=TOKEN_A"]


def test_retry_after_http_date_and_delay_cap(monkeypatch):
    sleeps = []
    client = DidaV2Client(
        DidaConfig.for_profile("dida"),
        session_token="TOKEN_A",
        max_read_attempts=2,
        sleep=sleeps.append,
        jitter=lambda delay: delay,
        wall_clock=lambda: 0.0,
    )
    attempts = 0

    def fake_urlopen(req, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise http_error(req, 503, retry_after="Thu, 01 Jan 1970 00:01:00 GMT")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert client.request("GET", "/status") == {}
    assert sleeps == [30.0]


def test_retry_configuration_rejects_unsafe_values():
    with pytest.raises(ValueError, match="max_read_attempts"):
        DidaV2Client(session_token="TOKEN", max_read_attempts=0)
    with pytest.raises(ValueError, match="retry_backoff_seconds"):
        DidaV2Client(session_token="TOKEN", retry_backoff_seconds=-1)

    client = DidaV2Client(session_token="TOKEN")
    with pytest.raises(ValueError, match="max_read_attempts"):
        client.max_read_attempts = 0
    with pytest.raises(ValueError, match="retry_backoff_seconds"):
        client.retry_backoff_seconds = float("nan")
