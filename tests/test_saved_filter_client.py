import pytest

from dida_v2_client.config import DidaConfig
from dida_v2_client.transport import DidaV2Client, DidaV2Error


def fixture_client(load_fixture):
    client = DidaV2Client(DidaConfig.default(), session_token="TEST")
    payload = load_fixture("full_sync_with_filters.json")
    client.full_sync = lambda: payload
    return client


def test_list_filters_reads_full_sync_snapshot(load_fixture):
    client = fixture_client(load_fixture)

    filters = client.list_filters()

    assert [item["name"] for item in filters] == ["Today P1"]


def test_get_and_find_filter(load_fixture):
    client = fixture_client(load_fixture)

    assert client.get_filter("filter-today-p1")["name"] == "Today P1"
    assert client.find_filter("Today P1")["id"] == "filter-today-p1"
    assert client.find_filter("Missing") is None


def test_get_filter_raises_clear_error(load_fixture):
    client = fixture_client(load_fixture)

    with pytest.raises(DidaV2Error, match="Saved filter not found"):
        client.get_filter("missing-filter")
