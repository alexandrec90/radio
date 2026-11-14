"""Twitch tab: favorites + followed channels with live status, auto-switching, and the
category browser below them."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from radio import twitch
from radio.gui.account import TwitchAccount
from radio.gui.category import CategoryBrowser
from radio.gui.widgets import make_tree, selected

REFRESH_MS = 120_000
STAR, HEART, DOT = "\N{BLACK STAR}", "\N{BLACK HEART SUIT}", "\N{BLACK CIRCLE}"


def channel_row(
    login: str, info: dict[str, Any], favorites: set[str], followed: set[str]
) -> tuple[tuple[str, ...], str]:
    """The values and tag ("live" / "off") of one row in the channel list."""
    user = info.get(login.lower())
    stream = (user or {}).get("stream")
    mark = (STAR if login.lower() in favorites else "") + (
        HEART if login.lower() in followed else ""
    )
    name = (user or {}).get("displayName", login)
    if stream:
        game = (stream.get("game") or {}).get("name", "")
        return (mark, f"{DOT} {name}", f"{stream['viewersCount']:,}", game, stream["title"]), "live"
    return (mark, name, "", "offline" if user else "?", ""), "off"


class TwitchTab:
    def __init__(self, app: Any, notebook: ttk.Notebook) -> None:
        self.app = app
        self.cfg = app.cfg
        self.info: dict[str, Any] = {}
        self.followed: list[str] = []
        tab = ttk.Frame(notebook, padding=8)
        notebook.add(tab, text="  Twitch  ")
        self._build_list(tab)
        self._build_buttons(tab)
        ttk.Separator(tab).pack(fill="x", pady=8)
        self.category = CategoryBrowser(app, tab, self)
        self.render()
        self.refresh()
        app.root.after(REFRESH_MS, self._auto_refresh)

    def _build_list(self, tab: ttk.Frame) -> None:
        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Label(top, text="Channels", style="Title.TLabel").pack(side="left")
        self.account = TwitchAccount(self.app, top, self._account_changed)
        self.live_only = tk.BooleanVar(value=self.cfg["tw_live_only"])
        ttk.Checkbutton(
            top,
            text="Live only",
            variable=self.live_only,
            command=lambda: self._setting("tw_live_only", self.live_only),
        ).pack(side="right")
        self.auto = tk.BooleanVar(value=self.cfg["auto_rotate"])
        ttk.Checkbutton(
            top,
            text="Auto-switch when a stream ends",
            variable=self.auto,
            command=lambda: self._setting("auto_rotate", self.auto),
        ).pack(side="right", padx=12)
        frame, self.tree = make_tree(
            tab, ("", "Channel", "Viewers", "Game", "Title"), (28, 130, 70, 160, 380), 10
        )
        frame.pack(fill="both", expand=True, pady=4)
        self.tree.bind("<Double-1>", lambda e: self.play_selected())

    def _build_buttons(self, tab: ttk.Frame) -> None:
        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Button(
            row,
            text="\N{BLACK RIGHT-POINTING TRIANGLE} Play",
            style="Accent.TButton",
            command=self.play_selected,
        ).pack(side="left")
        ttk.Button(
            row,
            text="\N{BLACK RIGHT-POINTING TRIANGLE} First live",
            command=lambda: self.rotate(user=True),
        ).pack(side="left", padx=4)
        ttk.Button(row, text=f"{STAR} Favorite", command=self.toggle_favorite).pack(side="left")
        ttk.Button(
            row, text="\N{UPWARDS ARROW}", width=3, command=lambda: self.move_favorite(-1)
        ).pack(side="left", padx=(4, 0))
        ttk.Button(
            row, text="\N{DOWNWARDS ARROW}", width=3, command=lambda: self.move_favorite(1)
        ).pack(side="left", padx=4)
        ttk.Button(row, text="\N{CLOCKWISE OPEN CIRCLE ARROW}", width=3, command=self.refresh).pack(
            side="left"
        )
        self.add_entry = ttk.Entry(row, width=18)
        self.add_entry.pack(side="right")
        self.add_entry.bind("<Return>", lambda e: self.add_favorite())
        ttk.Button(row, text="+ Add channel", command=self.add_favorite).pack(side="right", padx=4)
        ttk.Label(
            tab,
            text=f"{STAR} = favorite (plays first, in your order)   {HEART} = followed on your account",
            style="Dim.TLabel",
        ).pack(anchor="w", pady=(2, 0))

    def _setting(self, key: str, var: tk.BooleanVar) -> None:
        self.cfg[key] = var.get()
        self.app.save()
        self.render()

    def _account_changed(self) -> None:
        if not self.account.token:
            self.followed = []
        self.render()
        self.refresh()

    # ---- data
    def _fetch(self) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
        token = self.account.token
        follows = twitch.follows(token) if token else None
        return follows, twitch.status(self.cfg["twitch"])

    def apply(self, result: tuple[list[dict[str, Any]] | None, dict[str, Any]]) -> None:
        follows, status = result
        self.info.update(status)
        if follows is not None:
            self.followed = [u["login"] for u in follows]
            self.info.update({u["login"]: u for u in follows})
        self.render()

    def _failed(self, e: Exception) -> None:
        if isinstance(e, PermissionError):  # the token died: forget it and say so
            self.account.expired(e)
        # anything else is the network: keep the last list and try again next refresh

    def refresh(self, then: Any = None) -> None:
        def done(result: Any) -> None:
            self.apply(result)
            if then:
                then()

        self.app.bg(self._fetch, done, self._failed)

    def _auto_refresh(self) -> None:
        self.refresh(
            lambda: (
                self.rotate() if self.app.waiting_for_live and not self.app.player.active else None
            )
        )
        self.app.root.after(REFRESH_MS, self._auto_refresh)

    def order(self) -> list[str]:
        return twitch.order_channels(self.cfg["twitch"], self.followed, self.info)

    def render(self) -> None:
        sel = selected(self.tree)
        self.tree.delete(*self.tree.get_children())
        favorites = {f.lower() for f in self.cfg["twitch"]}
        followed = {f.lower() for f in self.followed}
        for login in self.order():
            if self.live_only.get() and not twitch.is_live(self.info, login):
                continue
            values, tag = channel_row(login, self.info, favorites, followed)
            self.tree.insert("", "end", iid=login, values=values, tags=(tag,))
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)

    # ---- playback
    def rotate(self, after: str | None = None, user: bool = False) -> None:
        """Play the first live favorite, else the most-watched live followed channel."""

        def done(result: Any) -> None:
            self.apply(result)
            login = twitch.pick_live(self.order(), self.info, after)
            if login:
                self.play(login)
            elif user:
                messagebox.showinfo(
                    "Radio", "None of your channels are live right now.", parent=self.app.root
                )
            else:
                self.app.player.stop()
                self.app.waiting_for_live = True

        self.app.bg(self._fetch, done, self._failed)

    def on_end(self, kind: str | None, channel: str | None) -> None:
        if kind == "twitch" and self.auto.get():
            self.rotate(after=channel)

    def play(self, login: str) -> None:
        user = self.info.get(login.lower()) or {}
        name = user.get("displayName") or login
        stream = user.get("stream") or {}
        title = f"{name} \N{EM DASH} {stream['title']}" if stream.get("title") else name
        self.app.waiting_for_live = False
        self.app.player.play_twitch(login, title, self.app.volume.get(), self.account.token)

    def play_selected(self) -> None:
        login = selected(self.tree)
        if not login:
            return
        if login.lower() in self.info and not twitch.is_live(self.info, login):
            messagebox.showinfo("Radio", f"{login} is offline.", parent=self.app.root)
            return
        self.play(login)

    # ---- favorites
    def add_favorite(self, login: str | None = None) -> None:
        login = (login or self.add_entry.get()).strip().rstrip("/").split("/")[-1]
        if not login or login.lower() in (f.lower() for f in self.cfg["twitch"]):
            return
        self.cfg["twitch"].append(login)
        self.app.save()
        self.add_entry.delete(0, "end")
        self.render()
        self.refresh()

    def toggle_favorite(self) -> None:
        login = selected(self.tree)
        if not login:
            return
        favorites = self.cfg["twitch"]
        match = [f for f in favorites if f.lower() == login.lower()]
        if match:
            favorites.remove(match[0])
        else:
            favorites.append(login)
        self.app.save()
        self.render()

    def move_favorite(self, delta: int) -> None:
        login = selected(self.tree)
        favorites = self.cfg["twitch"]
        if not login or login not in favorites:
            return
        i = favorites.index(login)
        j = max(0, min(len(favorites) - 1, i + delta))
        favorites[i], favorites[j] = favorites[j], favorites[i]
        self.app.save()
        self.render()
        self.tree.selection_set(login)
