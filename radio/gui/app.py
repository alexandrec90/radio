"""The window: a now-playing bar, the two tabs, and the background-work plumbing they share."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from tkinter import messagebox, ttk
from typing import Any

from radio import config
from radio.gui.twitch_tab import TwitchTab
from radio.gui.widgets import BG, apply_style
from radio.gui.youtube_tab import YouTubeTab
from radio.player import Player
from radio.tools import find_tools
from radio.util import format_duration

NP_PROPS = (
    "media-title",
    "time-pos",
    "duration",
    "pause",
    "playlist-pos",
    "playlist-count",
    "audio-bitrate",
)


def now_playing_text(info: dict[str, Any]) -> tuple[str, str]:
    """mpv properties -> (title line, detail line) for the bar."""
    title = info.get("media-title") or ""
    if not title or title.startswith(("watch?v=", "https://")):
        title = "Loading\N{HORIZONTAL ELLIPSIS}"
    if info.get("pause"):
        title = "\N{DOUBLE VERTICAL BAR} " + title
    parts = []
    if info.get("time-pos") is not None:
        dur = info.get("duration")
        parts.append(
            format_duration(info["time-pos"]) + (f" / {format_duration(dur)}" if dur else "")
        )
    count, pos = info.get("playlist-count"), info.get("playlist-pos")
    if count and count > 1 and pos is not None:
        parts.append(f"item {pos + 1} of {count}")
    if info.get("audio-bitrate"):
        parts.append(f"{info['audio-bitrate'] // 1000} kbps audio")
    return title, "   \N{MIDDLE DOT}   ".join(parts)


class App:
    def __init__(self, root: tk.Tk, cfg: dict[str, Any] | None = None, player: Any = None) -> None:
        self.root = root
        self.cfg = config.load_config() if cfg is None else cfg
        self.q: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.tools = find_tools()
        self.player = player or Player(self.tools, lambda k, c: self.q.put(("ended", k, c)))
        self.waiting_for_live = False
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="radio")
        self._pending: list[Future[Any]] = []

        root.title("Radio")
        root.geometry("920x740")
        root.minsize(680, 520)
        root.configure(bg=BG)
        apply_style(root)
        self._build_bar()
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.notebook = nb
        self.twitch = TwitchTab(self, nb)
        self.youtube = YouTubeTab(self, nb)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self._pump_loop)
        root.after(1000, self._poll)

    def _build_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 8))
        bar.pack(fill="x")
        left = ttk.Frame(bar)
        left.pack(side="left", fill="x", expand=True)
        self.np_title = ttk.Label(left, text="Nothing playing", style="Title.TLabel")
        self.np_title.pack(anchor="w")
        self.np_sub = ttk.Label(left, text="", style="Dim.TLabel")
        self.np_sub.pack(anchor="w")
        ctl = ttk.Frame(bar)
        ctl.pack(side="right")
        buttons: list[tuple[str, Callable[[], Any]]] = [
            (
                "\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}",
                lambda: self.player.command("playlist-prev"),
            ),
            (
                "\N{BLACK RIGHT-POINTING TRIANGLE WITH DOUBLE VERTICAL BAR}",
                lambda: self.player.command("cycle", "pause"),
            ),
            ("\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}", self.next_item),
            ("\N{BLACK SQUARE FOR STOP}", self.stop),
        ]
        for text, fn in buttons:
            ttk.Button(ctl, text=text, width=3, command=fn).pack(side="left", padx=2)
        ttk.Label(ctl, text="  \N{SPEAKER WITH THREE SOUND WAVES}").pack(side="left")
        self.volume = tk.IntVar(value=self.cfg["volume"])
        ttk.Scale(
            ctl,
            from_=0,
            to=100,
            variable=self.volume,
            length=120,
            command=lambda v: self.set_volume(int(float(v))),
        ).pack(side="left", padx=4)

    # ---- background work: run off the UI thread, finish on it
    def bg(
        self,
        fn: Callable[[], Any],
        done: Callable[[Any], None],
        err: Callable[[Exception], None] | None = None,
    ) -> None:
        """Run `fn` on a worker; `done(result)` or `err(exception)` then runs on the UI thread."""
        future = self._pool.submit(fn)
        self._pending.append(future)
        future.add_done_callback(lambda f: self.q.put(("future", f, done, err or self.error)))

    def error(self, e: Exception) -> None:
        messagebox.showerror("Radio", str(e), parent=self.root)

    def _finish(
        self, future: Future[Any], done: Callable[[Any], None], err: Callable[[Exception], None]
    ) -> None:
        exc = future.exception()
        if exc is None:
            done(future.result())
        elif isinstance(exc, Exception):
            err(exc)
        else:
            raise exc  # KeyboardInterrupt / SystemExit from a worker: not the UI's to absorb

    def pump(self) -> None:
        while not self.q.empty():
            msg = self.q.get_nowait()
            if msg[0] == "future":
                self._finish(*msg[1:])
            elif msg[0] == "ended":
                self.twitch.on_end(msg[1], msg[2])
            elif msg[0] == "np":
                self._show(msg[1])

    def drain(self, timeout: float = 15.0) -> None:
        """Finish all background work and apply it (tests, and nothing else, need this)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._pending = [f for f in self._pending if not f.done()]
            if not self._pending and self.q.empty():
                return
            wait(self._pending, timeout=max(0.0, deadline - time.monotonic()))
            self.pump()

    def _pump_loop(self) -> None:
        self._pending = [f for f in self._pending if not f.done()]
        self.pump()
        self.root.after(100, self._pump_loop)

    def save(self) -> None:
        config.save_config(self.cfg)

    # ---- now playing
    def _poll(self) -> None:
        def run() -> None:
            info = None
            if self.player.active:
                info = {p: self.player.command("get_property", p) for p in NP_PROPS}
            self.q.put(("np", info))

        threading.Thread(target=run, daemon=True).start()
        self.root.after(1000, self._poll)

    def _show(self, info: dict[str, Any] | None) -> None:
        if info is None:
            if not self.player.active:
                idle = (
                    "Waiting for a channel to go live\N{HORIZONTAL ELLIPSIS}"
                    if self.waiting_for_live
                    else "Nothing playing"
                )
                self.np_title.config(text=idle)
                self.np_sub.config(text="")
            return
        title, sub = now_playing_text(info)
        self.np_title.config(text=title)
        self.np_sub.config(text=sub)

    # ---- transport
    def set_volume(self, v: int) -> None:
        self.cfg["volume"] = v
        if self.player.active:
            threading.Thread(
                target=lambda: self.player.command("set_property", "volume", v), daemon=True
            ).start()

    def stop(self) -> None:
        self.waiting_for_live = False
        self.player.stop()

    def next_item(self) -> None:
        if self.player.kind == "twitch":
            self.twitch.rotate(after=self.player.channel)
        else:
            self.player.command("playlist-next")

    def close(self) -> None:
        self.player.stop()
        self.save()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
