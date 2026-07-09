from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DidaConfig:
    profile: str
    web_origin: str
    api_v2_base: str
    signin_url: str
    cookie_name: str = "t"

    @classmethod
    def default(cls) -> "DidaConfig":
        return cls.for_profile("dida")

    @classmethod
    def for_profile(cls, profile: str) -> "DidaConfig":
        normalized = profile.lower().strip()
        if normalized in {"dida", "dida365", "cn", "china"}:
            return cls(
                profile="dida",
                web_origin="https://dida365.com",
                api_v2_base="https://api.dida365.com/api/v2",
                signin_url="https://dida365.com/signin",
            )
        if normalized in {"ticktick", "global", "intl", "international"}:
            return cls(
                profile="ticktick",
                web_origin="https://ticktick.com",
                api_v2_base="https://api.ticktick.com/api/v2",
                signin_url="https://www.ticktick.com/signin",
            )
        raise ValueError(f"Unknown Dida/TickTick profile: {profile}")
