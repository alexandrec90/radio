import gzip
import io
import json
import subprocess

import pytest

from radio import youtube

LIVE_PAGE = (
    '<meta name="title" content="Lofi &amp; chill">'
    + "x" * 5000
    + '<link rel="canonical" href="https://www.youtube.com/watch?v=abcdefghijk">'
    + "y" * 5000
    + '"isLive":true "isLiveNow":true'
    + "z" * 5000
)
OFFLINE_PAGE = (
    "a" * 3000 + '<link rel="canonical" href="https://www.youtube.com/channel/UCx">' + "b" * 3000
)
UPCOMING_PAGE = (
    '<link rel="canonical" href="https://www.youtube.com/watch?v=abcdefghijk">"isUpcoming":true'
)


def fake_run(stdout="", returncode=0, stderr=""):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)

    return run, calls


def test_run_ytdlp_parses_json():
    run, calls = fake_run(json.dumps({"entries": []}))
    assert youtube.run_ytdlp("yt-dlp", ["x"], run=run) == {"entries": []}
    assert calls[0][:3] == ["yt-dlp", "--flat-playlist", "-J"]
    assert calls[0][-1] == "x"


def test_run_ytdlp_failure_reports_last_stderr_line():
    run, _ = fake_run(returncode=1, stderr="WARNING: a\nERROR: Video unavailable\n\n")
    with pytest.raises(RuntimeError, match="Video unavailable"):
        youtube.run_ytdlp("yt-dlp", [], run=run)
    run, _ = fake_run(returncode=1, stderr="")
    with pytest.raises(RuntimeError, match="yt-dlp failed"):
        youtube.run_ytdlp("yt-dlp", [], run=run)


def test_search_target():
    assert youtube.search_target("lofi beats", 10) == "ytsearch10:lofi beats"
    assert youtube.search_target("https://youtu.be/x") == "https://youtu.be/x"
    live = youtube.search_target("lofi beats", live_only=True)
    assert live.startswith("https://www.youtube.com/results?search_query=lofi+beats")
    assert live.endswith(youtube.LIVE_FILTER)


def test_to_results_playlist_and_single():
    data = {
        "entries": [
            {
                "id": "aaaaaaaaaaa",
                "url": "aaaaaaaaaaa",
                "title": "A",
                "channel": "C",
                "duration": 61,
                "channel_url": "https://www.youtube.com/channel/UC1",
            },
            None,
            {
                "url": "https://www.youtube.com/watch?v=b",
                "title": None,
                "uploader": "U",
                "live_status": "is_live",
            },
        ]
    }
    rows = youtube.to_results(data)
    assert rows[0]["url"] == "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    assert rows[0]["duration"] == 61 and not rows[0]["live"]
    assert rows[1] == {
        "title": "?",
        "channel": "U",
        "channel_url": "",
        "duration": None,
        "url": "https://www.youtube.com/watch?v=b",
        "live": True,
    }
    single = youtube.to_results({"webpage_url": "https://www.youtube.com/watch?v=s", "title": "S"})
    assert single[0]["title"] == "S"


def test_search_runs_ytdlp_with_limit(monkeypatch):
    seen = []
    monkeypatch.setattr(
        youtube, "run_ytdlp", lambda exe, args, *a, **kw: seen.append(args) or {"entries": []}
    )
    assert youtube.search("yt-dlp", "q", n=5) == []
    assert seen == [["-I", "1:5", "ytsearch5:q"]]


@pytest.mark.parametrize(
    ("url", "base"),
    [
        ("https://www.youtube.com/@name/videos", "https://www.youtube.com/@name"),
        ("https://youtube.com/channel/UC_x-y/streams", "https://youtube.com/channel/UC_x-y"),
        ("https://www.youtube.com/c/Old", "https://www.youtube.com/c/Old"),
        ("https://www.youtube.com/user/older/", "https://www.youtube.com/user/older"),
        ("https://www.youtube.com/playlist?list=PL1", None),
        ("https://www.youtube.com/watch?v=abc", None),
    ],
)
def test_channel_base(url, base):
    assert youtube.channel_base(url) == base


def chunked(text, size=1000):
    return [text[i : i + size] for i in range(0, len(text), size)]


def test_scan_live_page_live():
    assert youtube.scan_live_page(chunked(LIVE_PAGE)) == {
        "live": True,
        "url": "https://www.youtube.com/watch?v=abcdefghijk",
        "title": "Lofi & chill",
    }


def test_scan_live_page_offline_stops_early():
    consumed = []

    def chunks():
        for c in chunked(OFFLINE_PAGE):
            consumed.append(c)
            yield c

    assert youtube.scan_live_page(chunks()) == {"live": False}
    assert len(consumed) < len(chunked(OFFLINE_PAGE))


def test_scan_live_page_upcoming_and_empty():
    assert youtube.scan_live_page([UPCOMING_PAGE]) == {"live": False}
    assert youtube.scan_live_page([]) == {"live": False}


class FakeResponse(io.BytesIO):
    def __init__(self, body, gz):
        super().__init__(gzip.compress(body) if gz else body)
        self.headers = {"Content-Encoding": "gzip"} if gz else {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("gz", [True, False])
def test_live_status_reads_the_live_page(gz):
    seen = []

    def opener(req, timeout):
        seen.append(req.full_url)
        return FakeResponse(LIVE_PAGE.encode(), gz)

    result = youtube.live_status("https://www.youtube.com/@name/videos", opener=opener)
    assert result["live"] is True
    assert seen == ["https://www.youtube.com/@name/live"]


def test_live_status_of_a_playlist_is_none():
    assert youtube.live_status("https://www.youtube.com/playlist?list=PL1", opener=None) is None


def test_parse_takeout_csv():
    text = (
        "\N{ZERO WIDTH NO-BREAK SPACE}Channel Id,Channel Url,Channel Title\n"
        "UCabc,http://www.youtube.com/channel/UCabc,Some Channel\n"
        "bad,row\n"
    )
    assert youtube.parse_takeout_csv(text) == [
        {"name": "Some Channel", "url": "https://www.youtube.com/channel/UCabc/videos"}
    ]


def test_subs_from_feed():
    data = {
        "entries": [
            {"url": "https://www.youtube.com/@one", "title": "One"},
            {"id": "UC2", "channel": "Two"},
            {"url": "https://www.youtube.com/watch?v=x", "title": "not a channel"},
        ]
    }
    assert youtube.subs_from_feed(data) == [
        {"name": "One", "url": "https://www.youtube.com/@one/videos"},
        {"name": "Two", "url": "https://www.youtube.com/channel/UC2/videos"},
    ]


def test_import_subscriptions_csv(tmp_path):
    p = tmp_path / "subscriptions.csv"
    p.write_text("Channel Id,Channel Url,Channel Title\nUC1,u,One\n", "utf-8")
    assert youtube.import_subscriptions(p, "yt-dlp") == [
        {"name": "One", "url": "https://www.youtube.com/channel/UC1/videos"}
    ]


def test_import_subscriptions_cookies(tmp_path, monkeypatch):
    seen = []

    def run(exe, args, timeout=120):
        seen.append(args)
        return {"entries": [{"url": "https://www.youtube.com/@one", "title": "One"}]}

    monkeypatch.setattr(youtube, "run_ytdlp", run)
    cookies = tmp_path / "cookies.txt"
    assert youtube.import_subscriptions(cookies, "yt-dlp")[0]["name"] == "One"
    assert seen[0] == ["--cookies", str(cookies), "https://www.youtube.com/feed/channels"]


def test_import_subscriptions_cookies_logged_out(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "run_ytdlp", lambda *a, **kw: {"entries": []})
    with pytest.raises(RuntimeError, match="No subscriptions"):
        youtube.import_subscriptions(tmp_path / "cookies.txt", "yt-dlp")
