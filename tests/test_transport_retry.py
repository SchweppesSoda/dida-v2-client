import http.client
import io
import traceback
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
    transient = None

    def fake_urlopen(req, timeout):
        nonlocal transient
        calls.append(req)
        if len(calls) == 1:
            transient = http_error(req, 503, retry_after="2")
            raise transient
        return FakeResponse(b'{"ok":true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert client.request("GET", "/status") == {"ok": True}
    assert len(calls) == 2
    assert sleeps == [2.0]
    assert transient is not None and transient.fp.closed


def test_final_http_error_is_closed_after_safe_body_parsing(monkeypatch):
    client = client_with_retry(sleeps=[])
    final = None

    def fake_urlopen(req, timeout):
        nonlocal final
        final = http_error(req, 401, body=b'{"errorCode":"user_not_sign_on"}')
        raise final

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(DidaV2HTTPError) as excinfo:
        client.request("GET", "/status")
    assert excinfo.value.error_code == "user_not_sign_on"
    assert final is not None and final.fp.closed


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


def test_success_response_read_failure_is_bounded_retried_and_not_leaked(monkeypatch):
    class HostileResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            raise ValueError("response stream echoed TOKEN_A")

    attempts = 0

    def fake_urlopen(req, timeout):
        nonlocal attempts
        attempts += 1
        return HostileResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sleeps = []
    client = client_with_retry(sleeps=sleeps)

    with pytest.raises(DidaV2Error) as excinfo:
        client.request("GET", "/status")
    formatted = "".join(traceback.format_exception(excinfo.type, excinfo.value, excinfo.tb))
    assert "TOKEN_A" not in formatted
    assert "Response handling failed" in str(excinfo.value)
    assert attempts == 3
    assert sleeps == [0.25, 0.5]


def test_incomplete_read_and_response_close_failures_retry_only_safe_reads(monkeypatch):
    class FailingResponse(FakeResponse):
        def __init__(self, *, read_error=None, close_error=None, body=b"{}"):
            super().__init__(body)
            self.read_error = read_error
            self.close_error = close_error

        def read(self):
            if self.read_error is not None:
                raise self.read_error
            return super().read()

        def __exit__(self, *args):
            if self.close_error is not None:
                raise self.close_error
            return False

    sleeps = []
    responses = [FailingResponse(read_error=http.client.IncompleteRead(b"partial")), FakeResponse(b'{"ok":true}')]
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: responses.pop(0))
    client = client_with_retry(sleeps=sleeps)
    assert client.request("GET", "/status") == {"ok": True}
    assert sleeps == [0.25]

    sleeps.clear()
    responses = [FailingResponse(close_error=ValueError("close echoed TOKEN_A")), FakeResponse(b'{"ok":true}')]
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: responses.pop(0))
    assert client.request("HEAD", "/status") == {"ok": True}
    assert sleeps == [0.25]

    attempts = 0

    def fail_write(req, timeout):
        nonlocal attempts
        attempts += 1
        return FailingResponse(close_error=ValueError("close echoed TOKEN_A"))

    monkeypatch.setattr("urllib.request.urlopen", fail_write)
    with pytest.raises(DidaV2Error) as excinfo:
        client.request("POST", "/batch/task", payload={"update": []})
    formatted = "".join(traceback.format_exception(excinfo.type, excinfo.value, excinfo.tb))
    assert "TOKEN_A" not in formatted
    assert attempts == 1


def test_invalid_utf8_response_is_retried_then_safely_rejected(monkeypatch):
    attempts = 0

    def fake_urlopen(req, timeout):
        nonlocal attempts
        attempts += 1
        return FakeResponse(b'{"secret":"\xff"}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(DidaV2Error, match="Response handling failed"):
        client_with_retry(sleeps=[]).request("GET", "/status")
    assert attempts == 3


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


def test_past_retry_after_http_date_retries_immediately(monkeypatch):
    sleeps = []
    client = DidaV2Client(
        DidaConfig.for_profile("dida"),
        session_token="TOKEN_A",
        max_read_attempts=2,
        sleep=sleeps.append,
        jitter=lambda delay: delay,
        wall_clock=lambda: 120.0,
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
    assert sleeps == [0.0]


def test_deeply_nested_json_is_wrapped_for_success_and_http_error(monkeypatch):
    deep = ("[" * 2000 + "0" + "]" * 2000).encode()
    client = client_with_retry(sleeps=[])

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: FakeResponse(deep))
    with pytest.raises(DidaV2Error) as success_exc:
        client.request("GET", "/status")
    assert not isinstance(success_exc.value, RecursionError)

    def fail_http(req, timeout):
        raise http_error(req, 400, body=deep)

    monkeypatch.setattr("urllib.request.urlopen", fail_http)
    with pytest.raises(DidaV2HTTPError) as http_exc:
        client.request("GET", "/status")
    assert http_exc.value.status == 400


def test_malformed_retry_after_header_falls_back_and_closes(monkeypatch):
    class HostileHeaders:
        def get(self, name):
            raise ValueError("header echoed TOKEN_A")

    sleeps = []
    client = client_with_retry(sleeps=sleeps)
    transient = None
    attempts = 0

    def fake_urlopen(req, timeout):
        nonlocal transient, attempts
        attempts += 1
        if attempts == 1:
            transient = http_error(req, 503)
            setattr(transient, "headers", HostileHeaders())
            raise transient
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert client.request("GET", "/status") == {}
    assert sleeps == [0.25]
    assert transient is not None and transient.fp.closed


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
