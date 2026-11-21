"""The GUI's pure helpers: no window is opened, so these run in CI."""

from conftest import user

from radio.gui.account import clean_token
from radio.gui.app import now_playing_text
from radio.gui.category import category_label
from radio.gui.channels import check_all, merge_bookmarks
from radio.gui.twitch_tab import channel_row
from radio.gui.youtube_tab import result_row


def test_now_playing_text_full():
    title, sub = now_playing_text(
        {
            "media-title": "Song",
            "time-pos": 65,
            "duration": 3700,
            "pause": False,
            "playlist-pos": 1,
            "playlist-count": 5,
            "audio-bitrate": 64000,
        }
    )
    assert title == "Song"
    assert sub == "1:05 / 1:01:40   \N{MIDDLE DOT}   item 2 of 5   \N{MIDDLE DOT}   64 kbps audio"


def test_now_playing_text_loading_paused_and_live():
    title, sub = now_playing_text({"media-title": "watch?v=abc", "pause": True, "time-pos": 3})
    assert title == "\N{DOUBLE VERTICAL BAR} Loading\N{HORIZONTAL ELLIPSIS}"
    assert sub == "0:03"
    assert now_playing_text({})[1] == ""


def test_channel_row_live_and_offline():
    info = {"a": user("a", live=True, viewers=1234), "b": user("b")}
    values, tag = channel_row("a", info, {"a"}, {"a"})
    assert tag == "live"
    assert values[0] == "\N{BLACK STAR}\N{BLACK HEART SUIT}"
    assert values[2] == "1,234" and values[3] == "Chess"
    values, tag = channel_row("b", info, set(), {"b"})
    assert (tag, values[3]) == ("off", "offline")
    assert channel_row("unknown", info, set(), set())[0][3] == "?"


def test_category_label():
    assert (
        category_label({"name": "Chess", "viewersCount": 1500})
        == "Chess   \N{EM DASH}   1,500 viewers"
    )
    assert category_label({"name": "Quiet", "viewersCount": None}).endswith("0 viewers")


def test_clean_token():
    assert clean_token('  "abc123"  ') == "abc123"
    assert clean_token("OAuth abc123") == "abc123"
    assert clean_token('oauth "abc123"') == "abc123"
    assert clean_token("   ") == ""


def test_result_row():
    live = {"title": "T", "channel": "C", "duration": None, "live": True}
    assert result_row(live) == (("\N{BLACK CIRCLE} T", "C", "LIVE"), ("live",))
    vod = {"title": "T", "channel": "C", "duration": 90, "live": False}
    assert result_row(vod) == (("T", "C", "1:30"), ())


def test_merge_bookmarks_dedupes_by_channel():
    existing = [{"name": "A", "url": "https://www.youtube.com/@a/videos"}]
    new = [
        {"name": "A again", "url": "https://www.youtube.com/@a/streams"},
        {"name": "B", "url": "https://www.youtube.com/@b/videos"},
        {"name": "B twice", "url": "https://www.youtube.com/@b"},
        {"name": "P", "url": "https://www.youtube.com/playlist?list=1"},
    ]
    assert merge_bookmarks(existing, new) == 2
    assert [b["name"] for b in existing] == ["A", "B", "P"]


def test_check_all_drops_failed_channels():
    def probe(url):
        if "bad" in url:
            raise OSError("offline")
        return {"live": "live" in url}

    result = check_all(["https://y/@live", "https://y/@quiet", "https://y/@bad"], probe=probe)
    assert result == {"https://y/@live": {"live": True}, "https://y/@quiet": {"live": False}}
