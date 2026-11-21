"""Saved and subscribed YouTube channels, with a live-now filter.

A live check reads each channel's `/live` page (~300 KB), so it runs two at a time and
only on demand or every ten minutes while the filter is on.
"""

from __future__ import annotations

import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from radio import youtube
from radio.gui.widgets import make_tree, selected

RECHECK_SECONDS = 10 * 60
STAR, HEART, DOT = "\N{BLACK STAR}", "\N{BLACK HEART SUIT}", "\N{BLACK CIRCLE}"
IMPORT_HELP = (
    "Pick either file:\n\n"
    "\N{BULLET} subscriptions.csv from Google Takeout (takeout.google.com, only 'YouTube', "
    "subscriptions). Safest: nothing logged-in is kept.\n\n"
    "\N{BULLET} cookies.txt exported from youtube.com while logged in (e.g. with the "
    "'Get cookies.txt LOCALLY' extension). Read once for the subscription list and not "
    "kept; delete the file afterwards."
)


def merge_bookmarks(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> int:
    """Append the channels not already saved (same channel = same base URL); return how many."""
    have = {youtube.channel_base(b["url"]) or b["url"] for b in existing}
    added = 0
    for item in new:
        key = youtube.channel_base(item["url"]) or item["url"]
        if key not in have:
            existing.append(item)
            have.add(key)
            added += 1
    return added


def check_all(
    urls: list[str], probe: Any = youtube.live_status, workers: int = 2
) -> dict[str, Any]:
    """url -> live status for every channel; a channel that failed to load is left out."""

    def one(url: str) -> tuple[str, Any]:
        try:
            return url, probe(url)
        except OSError:  # network or HTTP failure for this channel: no verdict
            return url, None

    with ThreadPoolExecutor(workers) as pool:
        return {u: v for u, v in pool.map(one, urls) if v is not None}


class ChannelsPanel:
    def __init__(self, app: Any, parent: ttk.Frame, tab: Any) -> None:
        self.app, self.tab, self.cfg = app, tab, app.cfg
        self.live: dict[str, Any] = {}
        self.checked = 0.0
        self.checking = False
        self._build(parent)
        self.render()
        if self.cfg["yt_live_only"]:
            self.check_live()
        app.root.after(60_000, self._auto)

    def _build(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Label(row, text="Channels", style="Title.TLabel").pack(side="left")
        ttk.Button(
            row, text="Import subscriptions\N{HORIZONTAL ELLIPSIS}", command=self.import_subs
        ).pack(side="left", padx=10)
        self.live_only = tk.BooleanVar(value=self.cfg["yt_live_only"])
        ttk.Checkbutton(
            row, text="Live only", variable=self.live_only, command=self.toggle_live
        ).pack(side="right")
        ttk.Button(row, text="Check live", command=self.check_live).pack(side="right", padx=8)
        self.status = ttk.Label(row, text="", style="Dim.TLabel")
        self.status.pack(side="right")
        frame, self.tree = make_tree(parent, ("", "Name", "Now"), (28, 220, 500), 6)
        frame.pack(fill="both", expand=True, pady=4)
        self.tree.bind("<Double-1>", lambda e: self.play())
        buttons = ttk.Frame(parent)
        buttons.pack(fill="x")
        ttk.Button(
            buttons,
            text="\N{BLACK RIGHT-POINTING TRIANGLE} Play (live or newest)",
            style="Accent.TButton",
            command=self.play,
        ).pack(side="left")
        ttk.Button(buttons, text="Shuffle videos", command=lambda: self.play(shuffle=True)).pack(
            side="left", padx=4
        )
        ttk.Button(buttons, text="Browse videos", command=self.browse).pack(side="left")
        ttk.Button(buttons, text="Remove", command=self.remove).pack(side="right")
        ttk.Button(buttons, text="+ Add URL", command=self.add_url).pack(side="right", padx=4)

    def add(self, items: list[dict[str, Any]]) -> int:
        added = merge_bookmarks(self.cfg["bookmarks"], items)
        self.app.save()
        self.render()
        return added

    def render(self) -> None:
        sel = selected(self.tree)
        self.tree.delete(*self.tree.get_children())
        marks = self.cfg["bookmarks"]

        def key(ib: tuple[int, dict[str, Any]]) -> tuple[bool, str]:
            return (not (self.live.get(ib[1]["url"]) or {}).get("live"), ib[1]["name"].lower())

        for i, b in sorted(enumerate(marks), key=key):
            status = self.live.get(b["url"]) or {}
            if self.live_only.get() and not status.get("live"):
                continue
            mark = HEART if b.get("source") == "sub" else STAR
            if status.get("live"):
                self.tree.insert(
                    "",
                    "end",
                    iid=str(i),
                    tags=("live",),
                    values=(mark, f"{DOT} {b['name']}", status["title"]),
                )
            else:
                note = "" if youtube.channel_base(b["url"]) else "playlist"
                self.tree.insert(
                    "",
                    "end",
                    iid=str(i),
                    tags=("off",) if status else (),
                    values=(mark, b["name"], note),
                )
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)

    def toggle_live(self) -> None:
        self.cfg["yt_live_only"] = self.live_only.get()
        self.app.save()
        self.render()
        if self.live_only.get() and time.time() - self.checked > RECHECK_SECONDS:
            self.check_live()

    def _auto(self) -> None:
        if self.live_only.get() and time.time() - self.checked > RECHECK_SECONDS:
            self.check_live()
        self.app.root.after(60_000, self._auto)

    def check_live(self) -> None:
        urls = [b["url"] for b in self.cfg["bookmarks"] if youtube.channel_base(b["url"])]
        if self.checking or not urls:
            return
        self.checking = True
        self.status.config(text=f"checking {len(urls)} channels\N{HORIZONTAL ELLIPSIS}")

        def done(result: dict[str, Any]) -> None:
            self.checking = False
            self.checked = time.time()
            self.live.update(result)
            n = sum(1 for v in result.values() if v.get("live"))
            self.status.config(text=f"{n} live \N{MIDDLE DOT} checked {time.strftime('%H:%M')}")
            self.render()

        def failed(e: Exception) -> None:
            self.checking = False
            self.status.config(text=f"check failed: {e}")

        self.app.bg(lambda: check_all(urls), done, failed)

    def import_subs(self) -> None:
        if not messagebox.askokcancel(
            "Import YouTube subscriptions", IMPORT_HELP, parent=self.app.root
        ):
            return
        path = filedialog.askopenfilename(
            title="subscriptions.csv or cookies.txt",
            parent=self.app.root,
            filetypes=[("Subscriptions / cookies", "*.csv *.txt"), ("All", "*.*")],
        )
        if path:
            self.status.config(text="importing\N{HORIZONTAL ELLIPSIS}")
            self.app.bg(
                lambda: youtube.import_subscriptions(path, self.app.tools.ytdlp), self.imported
            )

    def imported(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            item["source"] = "sub"
        added = self.add(items)
        self.status.config(text="")
        messagebox.showinfo(
            "Radio",
            f"Found {len(items)} subscriptions, added {added} new channels.",
            parent=self.app.root,
        )
        if self.live_only.get():
            self.check_live()

    def add_url(self) -> None:
        url = simpledialog.askstring(
            "Radio", "YouTube channel, playlist or video URL:", parent=self.app.root
        )
        if not url:
            return
        url = url.strip()
        base = youtube.channel_base(url)
        if base and base == url.rstrip("/"):
            url = base + "/videos"
        name = simpledialog.askstring("Radio", "Name:", parent=self.app.root) or url
        self.add([{"name": name, "url": url, "source": "saved"}])

    def _selected(self) -> dict[str, Any] | None:
        sel = selected(self.tree)
        return self.cfg["bookmarks"][int(sel)] if sel is not None else None

    def remove(self) -> None:
        b = self._selected()
        if b:
            self.cfg["bookmarks"].remove(b)
            self.app.save()
            self.render()

    def play(self, shuffle: bool = False) -> None:
        b = self._selected()
        if not b:
            return
        status = self.live.get(b["url"]) or {}
        self.app.waiting_for_live = False
        if status.get("live") and not shuffle:
            self.app.player.play_youtube([status["url"]], volume=self.app.volume.get())
        else:
            self.app.player.play_youtube(
                [b["url"]], shuffle=shuffle, volume=self.app.volume.get(), whole_list=True
            )

    def browse(self) -> None:
        b = self._selected()
        if b:
            self.tab.entry.delete(0, "end")
            self.tab.entry.insert(0, b["url"])
            self.tab.search(b["url"])
