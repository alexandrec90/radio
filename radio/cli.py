"""`radio` on the command line: the picker by default, or straight to playback in this
terminal (mpv's keys work here: space pause, < > prev/next, 9 0 volume, q quit/skip).

    radio                       the picker window
    radio tw [name]             one Twitch channel, or rotate through favorites + follows
    radio yt <url> [--shuffle]  a video, playlist or channel, back to back
    radio search <words>        the top 50 YouTube results, back to back
"""

from __future__ import annotations

import argparse
import subprocess
import time
from collections.abc import Callable, Sequence
from typing import Any

from radio import config, secret_store, twitch
from radio.player import YT_FORMAT, streamlink_args
from radio.tools import Tools, find_tools

WAIT_SECONDS = 120


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="radio", description="Audio-only Twitch / YouTube radio.")
    sub = p.add_subparsers(dest="cmd")
    tw = sub.add_parser(
        "tw", aliases=["twitch"], help="Twitch: one channel, or rotate through favorites"
    )
    tw.add_argument("name", nargs="?")
    yt = sub.add_parser("yt", aliases=["youtube"], help="YouTube video, playlist or channel URL")
    yt.add_argument("url")
    yt.add_argument("--shuffle", action="store_true")
    se = sub.add_parser("search", help="play YouTube search results")
    se.add_argument("words", nargs="+")
    se.add_argument("--shuffle", action="store_true")
    sub.add_parser("gui", help="the picker window (the default)")
    return p


def console_args(
    tools: Tools, target: str, shuffle: bool = False, whole_list: bool = True
) -> list[str]:
    args = [
        tools.mpv_console,
        "--no-video",
        "--force-window=no",
        "--volume=70",
        "--term-osd-bar",
        f"--script-opts=ytdl_hook-ytdl_path={tools.ytdlp}",
        f"--ytdl-format={YT_FORMAT}",
    ]
    if whole_list:
        args.append("--ytdl-raw-options=yes-playlist=")
    if shuffle:
        args.append("--shuffle")
    return [*args, target]


def play_twitch(
    tools: Tools, login: str, token: str | None, run: Callable[..., Any] = subprocess.run
) -> int:
    print(f"\n>>> twitch.tv/{login} (audio only)", flush=True)
    feeder = subprocess.Popen(streamlink_args(tools, login, token), stdout=subprocess.PIPE)
    try:
        return int(
            run(
                [tools.mpv_console, "--no-video", "--force-window=no", "--volume=70", "-"],
                stdin=feeder.stdout,
            ).returncode
        )
    finally:
        feeder.kill()


def rotate(
    cfg: dict[str, Any],
    token: str | None,
    play: Callable[[str], Any],
    sleep: Callable[[float], None] = time.sleep,
    rounds: int | None = None,
) -> None:
    """Play the first live channel (favorites, then follows); when it ends, the next one."""
    last = None
    while rounds is None or rounds > 0:
        rounds = None if rounds is None else rounds - 1
        follows = twitch.follows(token) if token else []
        info = twitch.status(cfg["twitch"])
        info.update({u["login"]: u for u in follows})
        order = twitch.order_channels(cfg["twitch"], [u["login"] for u in follows], info)
        login = twitch.pick_live(order, info, after=last)
        if login is None:
            print(
                f"Nobody live; checking again in {WAIT_SECONDS // 60} min\N{HORIZONTAL ELLIPSIS}",
                flush=True,
            )
            last = None
            sleep(WAIT_SECONDS)
            continue
        play(login)
        last = login


def load_token(cfg: dict[str, Any]) -> str | None:
    try:
        return secret_store.unseal(cfg["twitch_auth"]) if cfg.get("twitch_auth") else None
    except (OSError, NotImplementedError, ValueError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd in (None, "gui"):
        from radio.gui.app import main as gui  # tkinter only when the window is wanted

        gui()
        return 0
    tools = find_tools()
    if args.cmd in ("yt", "youtube"):
        return subprocess.run(console_args(tools, args.url, args.shuffle)).returncode
    if args.cmd == "search":
        target = "ytdl://ytsearch50:" + " ".join(args.words)
        return subprocess.run(
            console_args(tools, target, args.shuffle, whole_list=False)
        ).returncode
    cfg = config.load_config()
    token = load_token(cfg)
    if args.name:
        return play_twitch(tools, args.name, token)
    try:
        rotate(cfg, token, lambda login: play_twitch(tools, login, token))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
