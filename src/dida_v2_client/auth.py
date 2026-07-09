from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .config import DidaConfig

HeadlessLogin = Callable[..., str]


def _credential_pair(*, username_env: str, password_env: str) -> tuple[str, str]:
    username = os.getenv(username_env) or os.getenv("TICKTICK_EMAIL")
    password = os.getenv(password_env) or os.getenv("TICKTICK_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            f"Automated login needs local env credentials ({username_env}/{password_env}); "
            "fallback DIDA_SESSION_TOKEN is supported for private local use."
        )
    return username, password


def _device_header() -> str:
    return json.dumps(
        {
            "platform": "web",
            "os": "python",
            "device": "dida-v2-client",
            "name": "",
            "version": 8006,
            "id": "dida-v2-client-local",
            "channel": "website",
        },
        separators=(",", ":"),
    )


def direct_signon_login(
    *,
    profile: str = "cn",
    config: DidaConfig | None = None,
    username_env: str = "DIDA_EMAIL",
    password_env: str = "DIDA_PASSWORD",
    timeout: int = 30,
) -> str:
    """Obtain a v2 session token through the web sign-on API.

    Dida365 China currently exposes ``POST /api/v2/user/signon?wc=true&remember=true``.
    This path is more reliable than automating the web form and works cross-platform,
    but it must only read credentials from local env/secret stores and never log them.
    """
    cfg = config or DidaConfig.for_profile(profile)
    username, password = _credential_pair(username_env=username_env, password_env=password_env)
    url = cfg.api_v2_base + "/user/signon?" + urllib.parse.urlencode({"wc": "true", "remember": "true"})
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "dida-v2-client/0.1",
            "Origin": cfg.web_origin,
            "Referer": cfg.signin_url,
            "X-Device": _device_header(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        detail = ""
        try:
            data = json.loads(body) if body else {}
            if isinstance(data, dict):
                detail = str(data.get("errorMessage") or data.get("message") or data.get("errorCode") or "")
        except Exception:
            detail = body[:120]
        detail = detail.replace(username, "[USERNAME]").replace(password, "[PASSWORD]")
        raise RuntimeError(f"Direct sign-on failed: HTTP {exc.code} {detail}".rstrip()) from exc

    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("Direct sign-on returned non-JSON response.") from exc
    token = data.get("token") if isinstance(data, dict) else None
    if not token:
        raise RuntimeError("Direct sign-on succeeded but did not return a session token.")
    return str(token)


def selenium_headless_login(
    *,
    profile: str = "cn",
    config: DidaConfig | None = None,
    username_env: str = "DIDA_EMAIL",
    password_env: str = "DIDA_PASSWORD",
) -> str:
    """Obtain a v2 session token using Selenium headless form automation.

    This is a fallback path. Prefer ``direct_signon_login`` for Dida365 because the
    web form can be gated by captcha/Turnstile and selectors change over time.
    """
    cfg = config or DidaConfig.for_profile(profile)
    username, password = _credential_pair(username_env=username_env, password_env=password_env)
    try:
        from selenium import webdriver  # type: ignore
        from selenium.webdriver.common.by import By  # type: ignore
        from selenium.webdriver.chrome.options import Options  # type: ignore
        from selenium.webdriver.support import expected_conditions as EC  # type: ignore
        from selenium.webdriver.support.ui import WebDriverWait  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency path
        raise RuntimeError("Install dida-v2-client[headless] to use Selenium headless login.") from exc

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
    raise RuntimeError("Selenium login finished but did not find session cookie `t`.")


def resolve_session_token(*, profile: str = "cn", headless: bool = True, headless_login: HeadlessLogin | None = None) -> str | None:
    """Resolve v2 session token.

    Default order:
    1. injected login callback, when supplied by tests/callers;
    2. direct Dida/TickTick web sign-on using local env credentials;
    3. Selenium headless form fallback;
    4. raw local session-token env fallback.
    """
    if headless:
        if headless_login is not None:
            strategies: list[HeadlessLogin] = [headless_login]
        else:
            strategies = [direct_signon_login, selenium_headless_login]
        for login in strategies:
            try:
                return login(profile=profile)
            except Exception:
                # Fallback exists for local/private use; callers can run the login
                # strategy directly if they need the detailed auth error.
                pass
    return os.getenv("DIDA_SESSION_TOKEN") or os.getenv("TICKTICK_SESSION_TOKEN")
