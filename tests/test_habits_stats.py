import json
from urllib.parse import parse_qs, urlparse

from dida_v2_client.config import DidaConfig
from dida_v2_client.transport import DidaV2Client


class FakeResponse:
    def __init__(self, body=b"{}"):
        self.status = 200
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_list_habits_and_sections_use_v2_get(monkeypatch):
    urls = []

    def fake_urlopen(req, timeout):
        urls.append(req.full_url)
        if req.full_url.endswith("/habits"):
            return FakeResponse(b'[{"id":"h1","name":"Drink"}]')
        return FakeResponse(b'[{"id":"s1","name":"Morning"}]')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.list_habits() == [{"id": "h1", "name": "Drink"}]
    assert client.list_habit_sections() == [{"id": "s1", "name": "Morning"}]
    assert [urlparse(url).path for url in urls] == ["/api/v2/habits", "/api/v2/habitSections"]


def test_habit_checkins_query_and_batch(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, json.loads(req.data.decode("utf-8"))))
        return FakeResponse(b'{"ok":true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.query_habit_checkins(["h1", "h2"], after_stamp=20260701) == {"ok": True}
    assert client.batch_habit_checkins(add=[{"habitId":"h1"}], update=[{"id":"c1"}], delete=["c2"]) == {"ok": True}

    assert urlparse(calls[0][0]).path == "/api/v2/habitCheckins/query"
    assert calls[0][1] == {"habitIds": ["h1", "h2"], "afterStamp": 20260701}
    assert urlparse(calls[1][0]).path == "/api/v2/habitCheckins/batch"
    assert calls[1][1] == {"add": [{"habitId": "h1"}], "update": [{"id": "c1"}], "delete": ["c2"]}


def test_batch_habits_posts_v2_habits_batch(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(b'{"ok":true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.batch_habits(add=[{"name":"Drink"}], update=[{"id":"h1","name":"Water"}], delete=["h2"]) == {"ok": True}
    assert urlparse(seen["url"]).path == "/api/v2/habits/batch"
    assert seen["body"] == {"add": [{"name": "Drink"}], "update": [{"id": "h1", "name": "Water"}], "delete": ["h2"]}


def test_user_and_focus_stats_endpoints(monkeypatch):
    urls = []

    def fake_urlopen(req, timeout):
        urls.append(req.full_url)
        return FakeResponse(b'{"ok":true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.user_profile() == {"ok": True}
    assert client.user_preferences() == {"ok": True}
    assert client.productivity_stats() == {"ok": True}
    assert client.focus_heatmap("20260701", "20260709") == {"ok": True}
    assert client.focus_distribution("20260701", "20260709") == {"ok": True}
    assert client.focus_timeline(to_timestamp=12345) == {"ok": True}

    parsed = [urlparse(url) for url in urls]
    assert [p.path for p in parsed] == [
        "/api/v2/user/profile",
        "/api/v2/user/preferences/settings",
        "/api/v2/statistics/general",
        "/api/v2/pomodoros/statistics/heatmap/20260701/20260709",
        "/api/v2/pomodoros/statistics/dist/20260701/20260709",
        "/api/v2/pomodoros/timeline",
    ]
    assert parse_qs(parsed[1].query) == {"includeWeb": ["true"]}
    assert parse_qs(parsed[5].query) == {"to": ["12345"]}
