from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Protocol, cast

from .config import DidaConfig
from .transport import DidaV2Error
from .version import USER_AGENT

HeadlessLogin = Callable[..., str]


class DidaAuthError(DidaV2Error):
    """Raised when no usable v2 session token can be resolved."""


class SessionStore(Protocol):
    def get(self, profile: str) -> str | None:
        ...

    def set(self, profile: str, token: str) -> None:
        ...

    def delete(self, profile: str) -> None:
        ...


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None:
        ...

    def set_password(self, service: str, username: str, password: str) -> None:
        ...

    def delete_password(self, service: str, username: str) -> None:
        ...


class KeyringSessionStore:
    """Store v2 session tokens in the operating-system credential vault."""

    def __init__(self, *, backend: KeyringBackend | None = None, service_name: str = "dida-v2-client"):
        if backend is None:
            try:
                import keyring  # type: ignore
            except ImportError:
                raise DidaAuthError("Install dida-v2-client[secure-store] to use OS session storage.") from None
            backend = cast(KeyringBackend, keyring)
        self.backend = backend
        self.service_name = service_name

    @staticmethod
    def _username(profile: str) -> str:
        normalized = DidaConfig.for_profile(profile).profile
        return f"session:{normalized}"

    @staticmethod
    def _backend_failure(exc: Exception) -> DidaAuthError:
        return DidaAuthError(f"OS secure session store failed ({exc.__class__.__name__}).")

    def get(self, profile: str) -> str | None:
        try:
            return self.backend.get_password(self.service_name, self._username(profile))
        except Exception as exc:
            raise self._backend_failure(exc) from None

    def set(self, profile: str, token: str) -> None:
        try:
            self.backend.set_password(self.service_name, self._username(profile), token)
        except Exception as exc:
            raise self._backend_failure(exc) from None

    def delete(self, profile: str) -> None:
        username = self._username(profile)
        try:
            if self.backend.get_password(self.service_name, username) is not None:
                self.backend.delete_password(self.service_name, username)
        except Exception as exc:
            raise self._backend_failure(exc) from None


def _credential_pair(
    *,
    profile: str,
    username_env: str | None = None,
    password_env: str | None = None,
) -> tuple[str, str]:
    canonical = DidaConfig.for_profile(profile).profile
    default_username_env = "TICKTICK_EMAIL" if canonical == "ticktick" else "DIDA_EMAIL"
    default_password_env = "TICKTICK_PASSWORD" if canonical == "ticktick" else "DIDA_PASSWORD"
    selected_username_env = username_env or default_username_env
    selected_password_env = password_env or default_password_env
    username = os.getenv(selected_username_env)
    password = os.getenv(selected_password_env)
    if not username or not password:
        session_env = "TICKTICK_SESSION_TOKEN" if canonical == "ticktick" else "DIDA_SESSION_TOKEN"
        raise DidaAuthError(
            f"Automated login needs local env credentials ({selected_username_env}/{selected_password_env}); "
            f"fallback {session_env} is supported for private local use."
        )
    return username, password


def _device_id(profile: str) -> str:
    canonical = DidaConfig.for_profile(profile).profile
    device_env = "TICKTICK_DEVICE_ID" if canonical == "ticktick" else "DIDA_DEVICE_ID"
    configured = os.getenv(device_env)
    if configured:
        if not re.fullmatch(r"[0-9a-fA-F]{24}", configured):
            raise DidaAuthError(f"{device_env} must be a 24-character hex string.")
        return configured.lower()
    # Dida's sign-on endpoint rejects arbitrary/non-web-like device IDs with a
    # misleading username_password_not_match error. Keep the default stable and
    # v2-client specific, in the same 24-hex shape used by the web app. Users can
    # override it with DIDA_DEVICE_ID/TICKTICK_DEVICE_ID if needed.
    return "6790a0b0c1d2e3f4a5b6c7d8"


def _device_header(profile: str) -> str:
    return json.dumps(
        {
            "platform": "web",
            "os": "python",
            "device": "dida-v2-client",
            "name": "",
            "version": 8006,
            "id": _device_id(profile),
            "channel": "website",
        },
        separators=(",", ":"),
    )


def _safe_error(exc: Exception) -> str:
    return exc.__class__.__name__


def direct_signon_login(
    *,
    profile: str = "cn",
    config: DidaConfig | None = None,
    username_env: str | None = None,
    password_env: str | None = None,
    timeout: int = 30,
) -> str:
    """Obtain a v2 session token through the web sign-on API.

    Dida365 China currently exposes ``POST /api/v2/user/signon?wc=true&remember=true``.
    This path is more reliable than automating the web form and works cross-platform,
    but it must only read credentials from local env/secret stores and never log them.
    """
    cfg = config or DidaConfig.for_profile(profile)
    canonical = cfg.profile
    username, password = _credential_pair(
        profile=canonical,
        username_env=username_env,
        password_env=password_env,
    )
    url = cfg.api_v2_base + "/user/signon?" + urllib.parse.urlencode({"wc": "true", "remember": "true"})
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Origin": cfg.web_origin,
            "Referer": cfg.signin_url,
            "X-Device": _device_header(canonical),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            exc.close()
        except Exception:
            pass
        raise DidaAuthError(f"Direct sign-on failed: HTTP {status}") from None
    except (urllib.error.URLError, OSError):
        raise DidaAuthError("Direct sign-on failed: network error") from None
    except (UnicodeError, ValueError, RecursionError):
        raise DidaAuthError("Direct sign-on failed: malformed response") from None
    except Exception:
        raise DidaAuthError("Direct sign-on failed: response handling error") from None

    try:
        data = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, RecursionError):
        raise DidaAuthError("Direct sign-on returned non-JSON response.") from None
    token = data.get("token") if isinstance(data, dict) else None
    if not token:
        raise DidaAuthError("Direct sign-on succeeded but did not return a session token.")
    return str(token)


def selenium_headless_login(
    *,
    profile: str = "cn",
    config: DidaConfig | None = None,
    username_env: str | None = None,
    password_env: str | None = None,
) -> str:
    """Obtain a v2 session token using Selenium headless form automation.

    This is a fallback path. Prefer ``direct_signon_login`` for Dida365 because the
    web form can be gated by captcha/Turnstile and selectors change over time.
    """
    cfg = config or DidaConfig.for_profile(profile)
    canonical = cfg.profile
    username, password = _credential_pair(
        profile=canonical,
        username_env=username_env,
        password_env=password_env,
    )
    try:
        from selenium import webdriver  # type: ignore
        from selenium.webdriver.common.by import By  # type: ignore
        from selenium.webdriver.chrome.options import Options  # type: ignore
        from selenium.webdriver.support import expected_conditions as EC  # type: ignore
        from selenium.webdriver.support.ui import WebDriverWait  # type: ignore
    except Exception:  # pragma: no cover - optional dependency path
        raise DidaAuthError("Install dida-v2-client[headless] to use Selenium headless login.") from None

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    driver = webdriver.Chrome(options=options)
    try:  # pragma: no cover - live browser path
        driver.get(cfg.signin_url)
        wait = WebDriverWait(driver, 20)
        user_el = wait.until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "#emailOrPhone, input[name='emailOrPhone'], input[type='email'], "
                    "input[placeholder*='Email'], input[placeholder*='邮箱'], "
                    "input[placeholder*='手机'], input[name='username'], input[type='text']",
                )
            )
        )
        pass_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password'], #password")))
        user_el.clear()
        user_el.send_keys(username)
        pass_el.clear()
        pass_el.send_keys(password)
        submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], #app div[class^=body] button, button")
        submit.click()
        deadline = time.time() + 30
        while time.time() < deadline:
            for cookie in driver.get_cookies():
                if cookie.get("name") == cfg.cookie_name and cookie.get("value"):
                    return str(cookie["value"])
            time.sleep(1)
    finally:
        driver.quit()
    raise DidaAuthError("Selenium login finished but did not find session cookie `t`.")


def resolve_session_token(
    *,
    profile: str = "cn",
    session_token: str | None = None,
    headless: bool = True,
    headless_login: HeadlessLogin | None = None,
    session_store: SessionStore | None = None,
) -> str | None:
    """Resolve a v2 session token in session-first order.

    Order: explicit token, OS secure store, profile-specific session env,
    injected/direct sign-on, then Selenium fallback.
    """
    if session_token:
        return session_token

    canonical = DidaConfig.for_profile(profile).profile
    errors: list[str] = []
    if session_store is not None:
        try:
            stored = session_store.get(canonical)
        except Exception as exc:
            errors.append(f"secure session store: {exc.__class__.__name__}")
        else:
            if stored:
                return stored

    env_name = "TICKTICK_SESSION_TOKEN" if canonical == "ticktick" else "DIDA_SESSION_TOKEN"
    token = os.getenv(env_name)
    if token:
        return token

    if headless:
        if headless_login is not None:
            strategies: list[tuple[str, HeadlessLogin]] = [("injected headless_login", headless_login)]
        else:
            strategies = [("direct sign-on", direct_signon_login), ("selenium fallback", selenium_headless_login)]
        for name, login in strategies:
            try:
                return login(profile=canonical)
            except Exception as exc:
                errors.append(f"{name}: {_safe_error(exc)}")
    if errors:
        raise DidaAuthError("Could not resolve v2 session token. " + "; ".join(errors))
    return None
