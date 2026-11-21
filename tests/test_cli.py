import subprocess

import pytest

from radio import cli, config, twitch
from radio.tools import Tools
from conftest import user

TOOLS = Tools(mpv="mpv", mpv_console="mpv.com", ytdlp="yt-dlp", streamlink="streamlink")


def test_build_parser_subcommands():
    p = cli.build_parser()
    assert p.parse_args([]).cmd is None
    assert p.parse_args(["tw", "chan"]).name == "chan"
    assert p.parse_args(["twitch"]).name is None
    args = p.parse_args(["yt", "https://x", "--shuffle"])
    assert (args.url, args.shuffle) == ("https://x", True)
    assert p.parse_args(["search", "a", "b"]).words == ["a", "b"]
    with pytest.raises(SystemExit):
        p.parse_args(["yt"])


def test_console_args():
    args = cli.console_args(TOOLS, "https://x", shuffle=True)
    assert args[0] == "mpv.com" and args[-1] == "https://x"
    assert "--shuffle" in args and "--ytdl-raw-options=yes-playlist=" in args
    assert "--ytdl-raw-options=yes-playlist=" not in cli.console_args(TOOLS, "t", whole_list=False)


def test_play_twitch_feeds_mpv_and_cleans_up(monkeypatch):
    killed = []

    class Feeder:
        stdout = object()

        def __init__(self, argv, **kw):
            self.argv = argv

        def kill(self):
            killed.append(True)

    monkeypatch.setattr(subprocess, "Popen", Feeder)
    runs = []

    def run(argv, **kw):
        runs.append((argv, kw))
        return subprocess.CompletedProcess(argv, 3)

    assert cli.play_twitch(TOOLS, "chan", None, run=run) == 3
    assert runs[0][0][0] == "mpv.com" and runs[0][1]["stdin"] is Feeder.stdout
    assert killed == [True]


def test_rotate_plays_live_then_waits(monkeypatch):
    infos = [{"a": user("a", live=True)}, {}]
    monkeypatch.setattr(twitch, "status", lambda logins: infos.pop(0))
    monkeypatch.setattr(twitch, "follows", lambda tok: pytest.fail("no token, no follows"))
    played, slept = [], []
    cli.rotate({"twitch": ["a"]}, None, played.append, sleep=slept.append, rounds=2)
    assert played == ["a"]
    assert slept == [cli.WAIT_SECONDS]


def test_rotate_includes_follows_with_token(monkeypatch):
    monkeypatch.setattr(twitch, "status", lambda logins: {})
    monkeypatch.setattr(twitch, "follows", lambda tok: [user("f", live=True)])
    played = []
    cli.rotate({"twitch": []}, "tok", played.append, sleep=lambda s: None, rounds=1)
    assert played == ["f"]


def test_load_token(monkeypatch):
    assert cli.load_token({"twitch_auth": None}) is None
    monkeypatch.setattr(cli.secret_store, "unseal", lambda s: "tok")
    assert cli.load_token({"twitch_auth": "sealed"}) == "tok"

    def broken(s):
        raise OSError("other user")

    monkeypatch.setattr(cli.secret_store, "unseal", broken)
    assert cli.load_token({"twitch_auth": "sealed"}) is None


def test_main_youtube_and_search(monkeypatch):
    runs = []
    monkeypatch.setattr(cli, "find_tools", lambda: TOOLS)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: runs.append(argv) or subprocess.CompletedProcess(argv, 0),
    )
    assert cli.main(["yt", "https://x"]) == 0
    assert cli.main(["search", "lofi", "beats"]) == 0
    assert runs[0][-1] == "https://x"
    assert runs[1][-1] == "ytdl://ytsearch50:lofi beats"


def test_main_twitch_single_and_rotation(monkeypatch):
    monkeypatch.setattr(cli, "find_tools", lambda: TOOLS)
    played = []
    monkeypatch.setattr(cli, "play_twitch", lambda tools, login, token: played.append(login) or 0)
    assert cli.main(["tw", "chan"]) == 0
    assert played == ["chan"]

    def interrupted(cfg, token, play):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "rotate", interrupted)
    config.save_config({"twitch": ["x"]})
    assert cli.main(["tw"]) == 0


def test_main_defaults_to_the_window(monkeypatch):
    opened = []
    monkeypatch.setattr("radio.gui.app.main", lambda: opened.append(True))
    assert cli.main([]) == 0
    assert cli.main(["gui"]) == 0
    assert opened == [True, True]
