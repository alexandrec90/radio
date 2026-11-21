import json
import threading

from radio import player
from radio.player import Player, ipc_request, mpv_args, streamlink_args
from radio.tools import Tools

TOOLS = Tools(mpv="mpv", mpv_console="mpv.com", ytdlp="yt-dlp", streamlink="streamlink")


def test_mpv_args_are_audio_only_with_ipc():
    args = mpv_args(TOOLS, 55, ipc="PIPE")
    assert args[0] == "mpv"
    assert "--no-video" in args and "--volume=55" in args and "--input-ipc-server=PIPE" in args
    assert f"--ytdl-format={player.YT_FORMAT}" in args
    assert "--script-opts=ytdl_hook-ytdl_path=yt-dlp" in args


def test_streamlink_args_with_and_without_token():
    assert streamlink_args(TOOLS, "chan") == [
        "streamlink",
        "--stdout",
        "--loglevel",
        "error",
        "twitch.tv/chan",
        "audio_only",
    ]
    with_token = streamlink_args(TOOLS, "chan", "tok")
    assert with_token[with_token.index("--twitch-api-header") + 1] == "Authorization=OAuth tok"
    assert with_token[-2:] == ["twitch.tv/chan", "audio_only"]


class FakePipe:
    """Stands in for mpv's IPC pipe: answers the request it was sent, after an event line."""

    def __init__(self, data):
        self.data, self.written, self.out = data, b"", []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write(self, b):
        self.written += b
        rid = json.loads(b)["request_id"]
        event = b'{"event":"playback-restart"}\n'
        reply = json.dumps({"request_id": rid, "data": self.data, "error": "success"}).encode()
        self.out = [event + reply[:10], reply[10:] + b"\n"]

    def read(self, n):
        return self.out.pop(0) if self.out else b""


def test_ipc_request_returns_matching_reply(monkeypatch):
    pipe = FakePipe("Title")
    monkeypatch.setattr("builtins.open", lambda *a, **kw: pipe)
    assert ipc_request("P", ["get_property", "media-title"], 7) == "Title"
    assert json.loads(pipe.written) == {"command": ["get_property", "media-title"], "request_id": 7}


def test_ipc_request_when_mpv_is_gone(monkeypatch):
    def gone(*a, **kw):
        raise FileNotFoundError

    monkeypatch.setattr("builtins.open", gone)
    assert ipc_request("P", ["x"], 1) is None


def test_ipc_request_when_pipe_closes(monkeypatch):
    pipe = FakePipe(None)
    pipe.write = lambda b: None  # never answers
    monkeypatch.setattr("builtins.open", lambda *a, **kw: pipe)
    assert ipc_request("P", ["x"], 1) is None


class FakeProc:
    def __init__(self, argv, **kw):
        self.argv, self.kw = argv, kw
        self.stdout = FakeStdout()
        self._done = threading.Event()
        self.killed = False

    def poll(self):
        return 0 if self._done.is_set() else None

    def wait(self):
        self._done.wait(5)

    def kill(self):
        self.killed = True
        self._done.set()

    def finish(self):
        self._done.set()


class FakeStdout:
    closed = False

    def close(self):
        self.closed = True


def make_player():
    procs, ended = [], []

    def popen(argv, **kw):
        procs.append(FakeProc(argv, **kw))
        return procs[-1]

    return Player(TOOLS, lambda k, c: ended.append((k, c)), popen=popen, ipc="P"), procs, ended


def test_play_youtube_builds_the_command():
    p, procs, _ = make_player()
    p.play_youtube(["u1", "u2"], start=1, shuffle=True, volume=30, whole_list=True)
    argv = procs[0].argv
    assert argv[-2:] == ["u1", "u2"]
    assert (
        "--shuffle" in argv
        and "--playlist-start=1" in argv
        and "--ytdl-raw-options=yes-playlist=" in argv
    )
    assert p.active and p.kind == "youtube"
    p.stop()


def test_play_twitch_pipes_streamlink_into_mpv():
    p, procs, _ = make_player()
    p.play_twitch("chan", "Chan - title", volume=40, token="tok")
    feeder, mpv = procs
    assert feeder.argv[-2:] == ["twitch.tv/chan", "audio_only"]
    assert mpv.kw["stdin"] is feeder.stdout and feeder.stdout.closed
    assert mpv.argv[-1] == "-" and "--force-media-title=Twitch · Chan - title" in mpv.argv
    assert (p.kind, p.channel) == ("twitch", "chan")
    p.stop()
    assert feeder.killed and mpv.killed and not p.active


def test_natural_end_reports_once_but_stop_does_not():
    p, procs, ended = make_player()
    p.play_twitch("chan", "t")
    procs[1].finish()
    for _ in range(100):
        if ended:
            break
        threading.Event().wait(0.01)
    assert ended == [("twitch", "chan")]
    assert procs[0].killed  # the feeder is cleaned up with it
    p.play_youtube(["u"])
    p.stop()
    threading.Event().wait(0.05)
    assert ended == [("twitch", "chan")]


def test_replacing_playback_does_not_report_an_end():
    p, procs, ended = make_player()
    p.play_youtube(["a"])
    p.play_youtube(["b"])
    threading.Event().wait(0.05)
    assert ended == [] and procs[0].killed
    p.stop()


def test_command_only_while_active(monkeypatch):
    p, _, _ = make_player()
    assert p.command("get_property", "pause") is None
    p.play_youtube(["u"])
    monkeypatch.setattr(player, "ipc_request", lambda pipe, cmd, rid: (pipe, cmd, rid))
    assert p.command("get_property", "pause") == ("P", ["get_property", "pause"], 1)
    assert p.command("x")[2] == 2
    p.stop()
