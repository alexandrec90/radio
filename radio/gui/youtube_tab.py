"""YouTube tab: search (optionally live-only) above the saved/subscribed channels list."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from radio import youtube
from radio.gui.channels import ChannelsPanel
from radio.gui.widgets import make_tree, selected
from radio.util import format_duration

DOT = "\N{BLACK CIRCLE}"


def result_row(r: dict[str, Any]) -> tuple[tuple[str, str, str], tuple[str, ...]]:
    if r["live"]:
        return (f"{DOT} {r['title']}", r["channel"], "LIVE"), ("live",)
    return (r["title"], r["channel"], format_duration(r["duration"])), ()


class YouTubeTab:
    def __init__(self, app: Any, notebook: ttk.Notebook) -> None:
        self.app = app
        self.results: list[dict[str, Any]] = []
        tab = ttk.Frame(notebook, padding=8)
        notebook.add(tab, text="  YouTube  ")
        self._build_search(tab)
        ttk.Separator(tab).pack(fill="x", pady=8)
        self.channels = ChannelsPanel(app, tab, self)

    def _build_search(self, tab: ttk.Frame) -> None:
        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Label(row, text="Search or paste a URL", style="Title.TLabel").pack(side="left")
        self.entry = ttk.Entry(row)
        self.entry.pack(side="left", fill="x", expand=True, padx=8)
        self.entry.bind("<Return>", lambda e: self.search())
        self.live_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Live only", variable=self.live_only).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(row, text="Search", command=self.search).pack(side="left")
        frame, self.tree = make_tree(tab, ("Title", "Channel", "Length"), (480, 180, 70), 6)
        frame.pack(fill="both", expand=True, pady=4)
        self.tree.bind("<Double-1>", lambda e: self.play())
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x")
        ttk.Button(
            buttons,
            text="\N{BLACK RIGHT-POINTING TRIANGLE} Play from here",
            style="Accent.TButton",
            command=self.play,
        ).pack(side="left")
        ttk.Button(buttons, text="Shuffle all", command=lambda: self.play(shuffle=True)).pack(
            side="left", padx=4
        )
        ttk.Button(buttons, text="\N{BLACK STAR} Save channel", command=self.save_channel).pack(
            side="left"
        )
        self.status = ttk.Label(buttons, text="", style="Dim.TLabel")
        self.status.pack(side="right")

    def search(self, text: str | None = None) -> None:
        text = (text or self.entry.get()).strip()
        if not text:
            return
        self.status.config(text="Searching\N{HORIZONTAL ELLIPSIS}")
        live = self.live_only.get()

        def failed(e: Exception) -> None:
            self.status.config(text="")
            self.app.error(e)

        self.app.bg(
            lambda: youtube.search(self.app.tools.ytdlp, text, live_only=live), self.show, failed
        )

    def show(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(results):
            values, tags = result_row(r)
            self.tree.insert("", "end", iid=str(i), values=values, tags=tags)
        self.status.config(text=f"{len(results)} results")

    def play(self, shuffle: bool = False) -> None:
        if not self.results:
            return
        sel = selected(self.tree)
        start = 0 if shuffle or sel is None else int(sel)
        self.app.waiting_for_live = False
        self.app.player.play_youtube(
            [r["url"] for r in self.results],
            start=start,
            shuffle=shuffle,
            volume=self.app.volume.get(),
        )

    def save_channel(self) -> None:
        sel = selected(self.tree)
        if sel is None:
            return
        r = self.results[int(sel)]
        if not r["channel_url"]:
            messagebox.showinfo("Radio", "No channel link for this result.", parent=self.app.root)
            return
        self.channels.add(
            [
                {
                    "name": r["channel"],
                    "url": r["channel_url"].rstrip("/") + "/videos",
                    "source": "saved",
                }
            ]
        )
