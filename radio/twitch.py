"""Twitch lookups through its public GraphQL endpoint, plus the channel-ordering rules.

The client id is the Twitch web player's public one (the same one streamlink sends).
Follow lists are private now, so `follows` needs the user's own `auth-token` cookie.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from typing import Any

GQL_URL = "https://gql.twitch.tv/gql"
GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
STREAM_FIELDS = "login displayName stream{title viewersCount game{name}}"
MAX_FOLLOW_PAGES = 20  # 100 per page

User = dict[str, Any]
Opener = Callable[..., Any]


def gql(query: str, token: str | None = None, opener: Opener = urllib.request.urlopen) -> Any:
    headers = {"Client-ID": GQL_CLIENT_ID, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"OAuth {token}"
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(GQL_URL, data=body, headers=headers)
    try:
        with opener(req, timeout=15) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise PermissionError("Twitch rejected the login token (expired or logged out).") from e
        raise
    if res.get("errors") and not res.get("data"):
        raise RuntimeError(res["errors"][0].get("message", "Twitch error"))
    return res["data"]


def status(logins: Iterable[str], query: Callable[..., Any] = gql) -> dict[str, User]:
    """login (lowercase) -> user with `stream` (None when offline), 100 logins per request."""
    out: dict[str, User] = {}
    names = [n.lower() for n in logins]
    for i in range(0, len(names), 100):
        batch = ",".join(json.dumps(n) for n in names[i : i + 100])
        data = query("query{users(logins:[%s]){%s}}" % (batch, STREAM_FIELDS))
        for u in data.get("users") or []:
            if u:
                out[u["login"]] = u
    return out


def me(token: str, query: Callable[..., Any] = gql) -> User:
    user = query("query{currentUser{login displayName}}", token).get("currentUser")
    if not user:
        raise PermissionError("That token isn't logged in to Twitch.")
    return user


def follows(token: str, query: Callable[..., Any] = gql) -> list[User]:
    users: list[User] = []
    after = None
    for _ in range(MAX_FOLLOW_PAGES):
        cursor = f",after:{json.dumps(after)}" if after else ""
        q = "query{currentUser{follows(first:100%s){edges{cursor node{%s}} pageInfo{hasNextPage}}}}"
        user = query(q % (cursor, STREAM_FIELDS), token).get("currentUser")
        if not user:
            raise PermissionError("Twitch login expired.")
        page = user["follows"]
        users += [e["node"] for e in page["edges"] if e["node"]]
        if not page["pageInfo"]["hasNextPage"] or not page["edges"]:
            break
        after = page["edges"][-1]["cursor"]
    return users


def category_streams(name: str, query: Callable[..., Any] = gql) -> list[dict[str, Any]] | None:
    """Live streams in a category by its exact name; None when no such category exists."""
    q = "query{game(name:%s){streams(first:30){edges{node{title viewersCount broadcaster{login displayName}}}}}}"
    game = query(q % json.dumps(name)).get("game")
    if not game:
        return None
    return [e["node"] for e in game["streams"]["edges"] if e["node"]["broadcaster"]]


def search_categories(text: str, query: Callable[..., Any] = gql) -> list[dict[str, Any]]:
    q = "query{searchCategories(query:%s,first:12){edges{node{name viewersCount}}}}"
    return [e["node"] for e in query(q % json.dumps(text))["searchCategories"]["edges"]]


def is_live(info: dict[str, User], login: str) -> bool:
    return bool((info.get(login.lower()) or {}).get("stream"))


def order_channels(favorites: list[str], followed: list[str], info: dict[str, User]) -> list[str]:
    """Favorites in the user's order, then the other follows: live by viewers, then A-Z."""
    fav = {f.lower() for f in favorites}
    rest = [f for f in followed if f.lower() not in fav]

    def key(login: str) -> tuple[bool, int, str]:
        stream = (info.get(login.lower()) or {}).get("stream") or {}
        return (not stream, -(stream.get("viewersCount") or 0), login.lower())

    return list(favorites) + sorted(rest, key=key)


def pick_live(order: list[str], info: dict[str, User], after: str | None = None) -> str | None:
    """The first live channel in `order`, skipping `after` (the one that just ended)."""
    skip = (after or "").lower()
    return next((c for c in order if c.lower() != skip and is_live(info, c)), None)
