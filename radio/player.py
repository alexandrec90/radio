"""mpv as an audio-only player, controlled over its JSON IPC pipe.

Twitch goes through streamlink (which drops ad segments) piped into mpv's stdin; YouTube
goes straight to mpv, whose ytdl hook asks yt-dlp for an audio-only format.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from radio.tools import Tools

YT_FORMAT = "bestaudio[abr<=80]/worstaudio/bestaudio"  # ~50-70 kbps opus; live: the low HLS audio
IPC_PIPE = (
    r"\\.\pipe\radio-mpv-ui" if sys.platform == "win32" else str(Path.home() / ".radio-mpv.sock")
)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def mpv_args(tools: Tools, volume: int, ipc: str = IPC_PIPE) -> list[str]:
    return [
        tools.mpv,
        "--no-video",
        "--force-window=no",
        "--no-terminal",
        f"--volume={volume}",
        f"--input-ipc-server={ipc}",
        f"--script-opts=ytdl_hook-ytdl_path={tools.ytdlp}",
        f"--ytdl-format={YT_FORMAT}",
        "--idle=no",
    ]


def streamlink_args(tools: Tools, login: str, token: str | None = None) -> list[str]:
    cmd = [tools.streamlink, "--stdout", "--loglevel", "error"]
    if token:  # logged-in playback: no ads where the user is subscribed or has Turbo
        cmd += ["--twitch-api-header", f"Authorization=OAuth {token}"]
    return [*cmd, f"twitch.tv/{login}", "audio_only"]


def ipc_request(pipe: str, command: list[Any], request_id: int, timeout: float = 2.0) -> Any:
    """Send one mpv JSON-IPC command and return its `data`; None if mpv is gone or silent."""
    try:
        with open(pipe, "r+b", buffering=0) as f:
            f.write((json.dumps({"command": command, "request_id": request_id}) + "\n").encode())
            buf = b""
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                chunk = f.read(65536)
                if not chunk:
                    return None
                buf += chunk
                found, data = _reply(buf, request_id)
                if found:
                    return data
    except OSError:
        return None
    return None


def _reply(buf: bytes, request_id: int) -> tuple[bool, Any]:
    """Look through what mpv has sent so far for the answer to `request_id`. Partial lines
    and event messages are skipped."""
    for line in buf.split(b"\n"):
        try:
            msg = json.loads(line)
        except ValueError:
            continue  # a line still arriving
        if isinstance(msg, dict) and msg.get("request_id") == request_id:
            return True, msg.get("data")
    return False, None


class Player:
    """At most one mpv (and its streamlink feeder) at a time. `on_end(kind, channel)` fires
    when playback ends by itself, never after `stop()` or a replacement."""

    def __init__(
        self,
        tools: Tools,
        on_end: Callable[[str | None, str | None], None],
        popen: Callable[..., Any] = subprocess.Popen,
        ipc: str = IPC_PIPE,
    ) -> None:
        self.tools, self.on_end, self.popen, self.ipc = tools, on_end, popen, ipc
        self.mpv: Any = None
        self.feeder: Any = None
        self.kind: str | None = None
        self.channel: str | None = None
        self._lock = threading.Lock()
        self._req = 0

    def play_youtube(
        self,
        urls: list[str],
        start: int = 0,
        shuffle: bool = False,
        volume: int = 70,
        whole_list: bool = False,
    ) -> None:
        self.stop()
        args = mpv_args(self.tools, volume, self.ipc)
        if shuffle:
            args.append("--shuffle")
        if whole_list:
            args.append("--ytdl-raw-options=yes-playlist=")
        if start:
            args.append(f"--playlist-start={start}")
        self.mpv = self.popen(args + list(urls), creationflags=NO_WINDOW)
        self.kind, self.channel = "youtube", None
        self._watch(self.mpv)

    def play_twitch(
        self, login: str, title: str, volume: int = 70, token: str | None = None
    ) -> None:
        self.stop()
        self.feeder = self.popen(
            streamlink_args(self.tools, login, token),
            stdout=subprocess.PIPE,
            creationflags=NO_WINDOW,
        )
        args = [
            *mpv_args(self.tools, volume, self.ipc),
            f"--force-media-title=Twitch · {title}",
            "-",
        ]
        self.mpv = self.popen(args, stdin=self.feeder.stdout, creationflags=NO_WINDOW)
        self.feeder.stdout.close()  # mpv owns the read end now
        self.kind, self.channel = "twitch", login
        self._watch(self.mpv)

    def _watch(self, proc: Any) -> None:
        def run() -> None:
            proc.wait()
            if proc is self.mpv:  # ended on its own, not stopped or replaced
                kind, channel = self.kind, self.channel
                self.stop()
                self.on_end(kind, channel)

        threading.Thread(target=run, daemon=True).start()

    def stop(self) -> None:
        old, feeder = self.mpv, self.feeder
        self.mpv = self.feeder = None  # detach first, so the watcher knows it was us
        self.kind = self.channel = None
        for p in (old, feeder):
            if p is not None and p.poll() is None:
                p.kill()

    @property
    def active(self) -> bool:
        return self.mpv is not None and self.mpv.poll() is None

    def command(self, *command: Any) -> Any:
        if not self.active:
            return None
        with self._lock:
            self._req += 1
            return ipc_request(self.ipc, list(command), self._req)
