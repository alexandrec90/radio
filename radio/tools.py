"""Where the three external programs live: PATH first, then their usual Windows installs."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Tools:
    mpv: str  # GUI-subsystem build: no console window
    mpv_console: str  # console build (mpv.com on Windows): keeps keyboard control in a terminal
    ytdlp: str
    streamlink: str


def find_tools(
    which: Callable[[str], str | None] = shutil.which,
    env: Mapping[str, str] | None = None,
    exists: Callable[[str], bool] = os.path.exists,
) -> Tools:
    env = os.environ if env is None else env
    local = env.get("LOCALAPPDATA", "")
    program_files = env.get("ProgramFiles", r"C:\Program Files")

    def pick(name: str, *fallbacks: str) -> str:
        found = which(name)
        if found:
            return found
        for f in fallbacks:
            if f and exists(f):
                return f
        return name  # let the launch fail with the tool's own name in the error

    mpv_dir = str(Path(program_files) / "MPV Player")
    mpv = pick("mpv", str(Path(mpv_dir) / "mpv.exe"))
    console = str(Path(mpv).with_suffix(".com"))
    return Tools(
        mpv=mpv,
        mpv_console=console if exists(console) else mpv,
        ytdlp=pick(
            "yt-dlp", str(Path(local) / "Microsoft/WinGet/Links/yt-dlp.exe") if local else ""
        ),
        streamlink=pick(
            "streamlink",
            str(Path(local) / "Programs/Streamlink/bin/streamlink.exe") if local else "",
        ),
    )
