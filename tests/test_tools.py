from pathlib import Path

from radio.tools import Tools, find_tools


def test_path_wins():
    t = find_tools(which=lambda n: f"/usr/bin/{n}", env={}, exists=lambda p: False)
    assert t == Tools(
        mpv="/usr/bin/mpv",
        mpv_console="/usr/bin/mpv",
        ytdlp="/usr/bin/yt-dlp",
        streamlink="/usr/bin/streamlink",
    )


def test_windows_install_locations():
    env = {"LOCALAPPDATA": "L", "ProgramFiles": "P"}
    present = {
        str(Path("P/MPV Player/mpv.exe")),
        str(Path("P/MPV Player/mpv.com")),
        str(Path("L/Microsoft/WinGet/Links/yt-dlp.exe")),
        str(Path("L/Programs/Streamlink/bin/streamlink.exe")),
    }
    t = find_tools(which=lambda n: None, env=env, exists=present.__contains__)
    assert t.mpv.endswith("mpv.exe")
    assert t.mpv_console.endswith("mpv.com")
    assert t.ytdlp.endswith("yt-dlp.exe")
    assert t.streamlink.endswith("streamlink.exe")


def test_missing_tool_falls_back_to_its_name():
    t = find_tools(which=lambda n: None, env={}, exists=lambda p: False)
    assert (t.mpv, t.ytdlp, t.streamlink) == ("mpv", "yt-dlp", "streamlink")
    assert t.mpv_console == "mpv"
