"""The "Connect Twitch account" dialog: paste the browser's auth-token cookie, verify it."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

from radio import secret_store, twitch
from radio.gui.widgets import BG

STEPS = (
    "This lets Radio list the channels you follow (and skip ads where you're subbed or "
    "have Turbo).\n\n"
    "1.  Open twitch.tv in your browser, logged in.\n"
    "2.  Press F12  \N{RIGHTWARDS ARROW}  Application tab  \N{RIGHTWARDS ARROW}  Cookies  "
    "\N{RIGHTWARDS ARROW}  https://www.twitch.tv\n"
    "3.  Find the row named  auth-token  and copy its Value.\n"
    "4.  Paste it below.\n\n"
    "It is stored encrypted for your Windows account only, and sent to nobody but Twitch.\n"
    "Logging out of Twitch in the browser invalidates it; just reconnect then."
)


def clean_token(raw: str) -> str:
    """Accept the cookie value however it was copied: quoted, or with an `OAuth ` prefix."""
    token = raw.strip()
    if token.lower().startswith("oauth "):
        token = token[6:]
    return token.strip().strip('"').strip()


class TwitchAccount:
    """The connected Twitch login: its token (sealed in the config) and the button showing it.
    `on_change()` runs whenever the user connects or disconnects."""

    def __init__(self, app: Any, parent: ttk.Frame, on_change: Callable[[], None]) -> None:
        self.app, self.cfg, self.on_change = app, app.cfg, on_change
        self.token: str | None = None
        if self.cfg.get("twitch_auth"):
            try:
                self.token = secret_store.unseal(self.cfg["twitch_auth"])
            except (OSError, NotImplementedError, ValueError):
                self.cfg["twitch_auth"] = None
        self.button = ttk.Button(parent, command=self.click)
        self.button.pack(side="left", padx=10)
        self.label()

    def label(self) -> None:
        ellipsis = "\N{HORIZONTAL ELLIPSIS}"
        text = (
            f"\N{BLACK HEART SUIT} {self.cfg.get('twitch_login')} (account{ellipsis})"
            if self.token
            else f"Connect Twitch account{ellipsis}"
        )
        self.button.config(text=text)

    def click(self) -> None:
        if not self.token:
            ConnectDialog(self.app, self.connected)
        elif messagebox.askyesno(
            "Radio",
            f"Connected as {self.cfg.get('twitch_login')}.\n\nDisconnect?",
            parent=self.app.root,
        ):
            self.forget()
            self.on_change()

    def connected(self, user: dict[str, Any], token: str) -> None:
        self.token = token
        self.cfg["twitch_auth"] = secret_store.seal(token)
        self.cfg["twitch_login"] = user["displayName"]
        self.app.save()
        self.label()
        self.on_change()

    def forget(self) -> None:
        self.token = self.cfg["twitch_auth"] = self.cfg["twitch_login"] = None
        self.app.save()
        self.label()

    def expired(self, e: Exception) -> None:
        self.forget()
        messagebox.showwarning("Radio", f"{e} Reconnect your Twitch account.", parent=self.app.root)


class ConnectDialog:
    def __init__(self, app: Any, on_ok: Callable[[dict[str, Any], str], None]) -> None:
        self.app, self.on_ok = app, on_ok
        self.window = d = tk.Toplevel(app.root)
        d.title("Connect Twitch")
        d.configure(bg=BG)
        d.transient(app.root)
        d.resizable(False, False)
        fr = ttk.Frame(d, padding=16)
        fr.pack(fill="both")
        ttk.Label(fr, text="Connect your Twitch account", style="Title.TLabel").pack(anchor="w")
        ttk.Label(fr, text=STEPS, justify="left", wraplength=470).pack(anchor="w", pady=8)
        ttk.Button(
            fr, text="Open twitch.tv", command=lambda: webbrowser.open("https://www.twitch.tv")
        ).pack(anchor="w")
        self.entry = ttk.Entry(fr, width=50, show="\N{BULLET}")
        self.entry.pack(fill="x", pady=10)
        self.message = ttk.Label(fr, text="", style="Dim.TLabel")
        self.message.pack(anchor="w")
        self.entry.bind("<Return>", lambda e: self.connect())
        ttk.Button(fr, text="Connect", style="Accent.TButton", command=self.connect).pack(
            anchor="e"
        )
        self.entry.focus_set()

    def connect(self) -> None:
        token = clean_token(self.entry.get())
        if not token:
            return
        self.message.config(text="Checking\N{HORIZONTAL ELLIPSIS}")
        self.app.bg(
            lambda: twitch.me(token),
            lambda user: self._ok(user, token),
            lambda e: self.message.config(text=f"\N{BALLOT X} {e}"),
        )

    def _ok(self, user: dict[str, Any], token: str) -> None:
        self.window.destroy()
        self.on_ok(user, token)
