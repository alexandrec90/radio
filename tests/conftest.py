"""Shared fixtures. Nothing here touches the network, mpv, or the real config file.

Tests that open a tkinter window are marked `local`: `addopts` deselects them and
`scripts/e2e.py` runs them on this PC, since a CI runner has no display.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from typing import Any

import pytest

from radio import config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    path = tmp_path / "radio.json"
    monkeypatch.setenv("RADIO_CONFIG", str(path))
    return path


@pytest.fixture(scope="session")
def _session_root() -> Iterator[tk.Tk]:
    # One interpreter for the run: creating a fresh Tk per test fails intermittently on
    # Windows after a few dozen ("Can't find a usable tk.tcl").
    try:
        r = tk.Tk()
    except tk.TclError as e:
        pytest.fail(f"the local tier needs a display for tkinter: {e}")
    yield r
    r.destroy()


@pytest.fixture
def root(_session_root) -> Iterator[tk.Tk]:
    """The shared root, emptied after each test: its widgets and pending timers go."""
    r = _session_root
    yield r
    for timer in r.tk.splitlist(r.tk.call("after", "info")):
        r.after_cancel(timer)
    for child in r.winfo_children():
        child.destroy()


class FakePlayer:
    """Records what the UI asked to play; never starts a process."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.kind: str | None = None
        self.channel: str | None = None
        self.active = False

    def play_youtube(self, urls, **kw):
        self.calls.append(("youtube", (list(urls), kw)))
        self.kind = "youtube"

    def play_twitch(self, login, title, volume=70, token=None):
        self.calls.append(("twitch", (login, title, token)))
        self.kind, self.channel = "twitch", login

    def stop(self):
        self.calls.append(("stop", None))
        self.kind = self.channel = None

    def command(self, *command):
        self.calls.append(("command", command))


@pytest.fixture
def fake_player() -> FakePlayer:
    return FakePlayer()


def stream(title: str = "t", viewers: int = 10, game: str = "Chess") -> dict[str, Any]:
    return {"title": title, "viewersCount": viewers, "game": {"name": game}}


def user(login: str, live: bool = False, viewers: int = 10) -> dict[str, Any]:
    return {
        "login": login,
        "displayName": login.title(),
        "stream": stream(viewers=viewers) if live else None,
    }


@pytest.fixture
def cfg() -> dict[str, Any]:
    return config.load_config()


@pytest.fixture
def dialogs(monkeypatch) -> list[tuple[str, str]]:
    """Every messagebox the GUI would have shown, instead of showing it."""
    shown: list[tuple[str, str]] = []
    from tkinter import messagebox

    for name in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(
            messagebox, name, lambda title, msg, _n=name, **kw: shown.append((_n, msg))
        )
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **kw: True)
    monkeypatch.setattr(messagebox, "askokcancel", lambda *a, **kw: True)
    return shown
