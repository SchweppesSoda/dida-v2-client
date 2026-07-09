from __future__ import annotations

import os
from typing import Callable

from .config import DidaConfig

HeadlessLogin = Callable[..., str]


def selenium_headless_login(*, profile: str = "cn", config: DidaConfig | None = None, username_env: str = "DIDA_EMAIL", password_env: str = "DIDA_PASSWORD") -> str:
    """Obtain a v2 session token using Selenium headless login.

    This is intentionally conservative in v0.1: the function is the default strategy
    but requires optional browser dependencies and local credentials. The exact Dida
    login selectors are likely to evolve, so callers should treat failures as a cue
    to refresh the auth implementation, not to paste cookies into chat.
    """
    cfg = config or DidaConfig.for_profile(profile)
    username = os.getenv(username_env) or os.getenv("TICKTICK_EMAIL")
    password = os.getenv(password_env) or os.getenv("TICKTICK_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            f"Headless login needs local env credentials ({username_env}/{password_env}); "
            "fallback DIDA_SESSION_TOKEN is supported for private local use."
        )
    try:
        from selenium import webdriver  # type: ignore
        from selenium.webdriver.common.by import By  # type: ignore
        from selenium.webdriver.chrome.options import Options  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency path
        raise RuntimeError("Install dida-v2-client[headless] to use Selenium headless login.") from exc

    options = Options()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    try:  # pragma: no cover - live browser path
        driver.get(cfg.signin_url)
        # TickTick/Dida login pages have changed over time. Try broad selectors first.
        user_el = driver.find_element(By.CSS_SELECTOR, 'input[type="email"], input[placeholder="Email"], input[name="username"]')
        pass_el = driver.find_element(By.CSS_SELECTOR, 'input[type="password"], #password')
        user_el.send_keys(username)
        pass_el.send_keys(password)
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], #app div[class^=body] button').click()
        driver.implicitly_wait(5)
        for cookie in driver.get_cookies():
            if cookie.get("name") == cfg.cookie_name and cookie.get("value"):
                return str(cookie["value"])
    finally:
        driver.quit()
    raise RuntimeError("Headless login finished but did not find session cookie `t`.")


def resolve_session_token(*, profile: str = "cn", headless: bool = True, headless_login: HeadlessLogin | None = None) -> str | None:
    """Resolve v2 session token.

    Default order is intentionally: headless login first, raw t-cookie env fallback second.
    Tests may inject `headless_login` to avoid launching a browser.
    """
    if headless:
        login = headless_login or selenium_headless_login
        try:
            return login(profile=profile)
        except Exception:
            # Fallback exists for local/private use; callers can surface the real
            # headless error if no token is available.
            pass
    return os.getenv("DIDA_SESSION_TOKEN") or os.getenv("TICKTICK_SESSION_TOKEN")
