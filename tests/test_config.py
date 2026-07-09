from dida_v2_client.config import DidaConfig


def test_dida_profile_is_default():
    cfg = DidaConfig.default()
    assert cfg.profile == "dida"
    assert cfg.web_origin == "https://dida365.com"
    assert cfg.api_v2_base == "https://api.dida365.com/api/v2"
    assert cfg.signin_url == "https://dida365.com/signin"


def test_ticktick_profile_switches_domains():
    cfg = DidaConfig.for_profile("ticktick")
    assert cfg.profile == "ticktick"
    assert cfg.web_origin == "https://ticktick.com"
    assert cfg.api_v2_base == "https://api.ticktick.com/api/v2"


def test_legacy_aliases_still_work():
    assert DidaConfig.for_profile("cn").profile == "dida"
    assert DidaConfig.for_profile("global").profile == "ticktick"
