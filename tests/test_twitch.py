import io
import json
import urllib.error

import pytest

from radio import twitch
from conftest import user


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_returning(payload, seen=None):
    def opener(req, timeout):
        if seen is not None:
            seen.append(req)
        return FakeResponse(json.dumps(payload).encode())

    return opener


def test_gql_sends_client_id_and_token():
    seen = []
    data = twitch.gql("query{x}", "tok", opener=opener_returning({"data": {"x": 1}}, seen))
    assert data == {"x": 1}
    headers = {k.lower(): v for k, v in seen[0].header_items()}
    assert headers["client-id"] == twitch.GQL_CLIENT_ID
    assert headers["authorization"] == "OAuth tok"
    assert json.loads(seen[0].data) == {"query": "query{x}"}


def test_gql_without_token_sends_no_authorization():
    seen = []
    twitch.gql("q", opener=opener_returning({"data": {}}, seen))
    assert "authorization" not in {k.lower() for k, _ in seen[0].header_items()}


def test_gql_error_without_data_raises():
    with pytest.raises(RuntimeError, match="bad field"):
        twitch.gql("q", opener=opener_returning({"errors": [{"message": "bad field"}]}))


def test_gql_401_is_a_permission_error():
    def opener(req, timeout):
        raise urllib.error.HTTPError(twitch.GQL_URL, 401, "nope", {}, None)

    with pytest.raises(PermissionError):
        twitch.gql("q", "tok", opener=opener)


def test_gql_other_http_errors_propagate():
    def opener(req, timeout):
        raise urllib.error.HTTPError(twitch.GQL_URL, 500, "boom", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        twitch.gql("q", opener=opener)


def test_status_batches_by_100_and_lowercases():
    queries = []

    def query(q, token=None):
        queries.append(q)
        return {"users": [user("abc", live=True), None]}

    out = twitch.status([f"User{i}" for i in range(150)], query=query)
    assert len(queries) == 2
    assert '"user0"' in queries[0]
    assert out == {"abc": user("abc", live=True)}


def test_status_of_nothing_makes_no_request():
    assert twitch.status([], query=lambda q: pytest.fail("no request expected")) == {}


def test_me_and_not_logged_in():
    assert twitch.me("t", query=lambda q, tok: {"currentUser": {"login": "me"}}) == {"login": "me"}
    with pytest.raises(PermissionError):
        twitch.me("t", query=lambda q, tok: {"currentUser": None})


def test_follows_pages_with_cursor():
    pages = [
        {"edges": [{"cursor": "c1", "node": user("a")}], "pageInfo": {"hasNextPage": True}},
        {
            "edges": [{"cursor": "c2", "node": user("b")}, {"cursor": "c3", "node": None}],
            "pageInfo": {"hasNextPage": False},
        },
    ]
    queries = []

    def query(q, token):
        queries.append(q)
        return {"currentUser": {"follows": pages[len(queries) - 1]}}

    assert [u["login"] for u in twitch.follows("t", query=query)] == ["a", "b"]
    assert 'after:"c1"' in queries[1]


def test_follows_expired_login():
    with pytest.raises(PermissionError):
        twitch.follows("t", query=lambda q, tok: {"currentUser": None})


def test_category_streams():
    edge = {
        "node": {"title": "x", "viewersCount": 3, "broadcaster": {"login": "a", "displayName": "A"}}
    }
    orphan = {"node": {"title": "y", "viewersCount": 1, "broadcaster": None}}
    data = {"game": {"streams": {"edges": [edge, orphan]}}}
    assert twitch.category_streams("Chess", query=lambda q: data) == [edge["node"]]
    assert twitch.category_streams("Nope", query=lambda q: {"game": None}) is None


def test_search_categories():
    data = {"searchCategories": {"edges": [{"node": {"name": "Chess", "viewersCount": 5}}]}}
    assert twitch.search_categories("che", query=lambda q: data) == [
        {"name": "Chess", "viewersCount": 5}
    ]


def test_is_live():
    info = {"a": user("a", live=True), "b": user("b")}
    assert twitch.is_live(info, "A")
    assert not twitch.is_live(info, "b")
    assert not twitch.is_live(info, "unknown")


def test_order_channels_favorites_first_then_live_by_viewers():
    info = {
        "x": user("x", live=True, viewers=5),
        "y": user("y", live=True, viewers=50),
        "z": user("z"),
        "fav": user("fav"),
    }
    order = twitch.order_channels(["fav"], ["z", "x", "FAV", "y"], info)
    assert order == ["fav", "y", "x", "z"]


def test_pick_live_skips_the_channel_that_just_ended():
    info = {"a": user("a", live=True), "b": user("b", live=True), "c": user("c")}
    assert twitch.pick_live(["c", "a", "b"], info) == "a"
    assert twitch.pick_live(["c", "a", "b"], info, after="A") == "b"
    assert twitch.pick_live(["c"], info) is None
