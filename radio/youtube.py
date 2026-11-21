"""YouTube through yt-dlp (search, channel listings, subscription import) and a light live check.

Nothing here downloads media: yt-dlp runs with `--flat-playlist`, and playback is mpv's job.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import subprocess
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
LIVE_FILTER = "EgJAAQ%253D%253D"  # YouTube's "Live" search filter, encoded twice for yt-dlp
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_CHANNEL = re.compile(
    r"(https?://(?:www\.)?youtube\.com/(?:@[^/?#]+|channel/[\w-]+|c/[^/?#]+|user/[^/?#]+))"
)
_CANONICAL = re.compile(r'rel="canonical" href="([^"]+)"')
_TITLE = re.compile(r'<meta name="title" content="([^"]*)"')

Result = dict[str, Any]


def run_ytdlp(
    ytdlp: str, args: list[str], timeout: int = 120, run: Callable[..., Any] = subprocess.run
) -> Any:
    p = run(
        [ytdlp, "--flat-playlist", "-J", "--no-warnings", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=NO_WINDOW,
        timeout=timeout,
    )
    if p.returncode != 0:
        lines = [line for line in (p.stderr or "").splitlines() if line.strip()]
        raise RuntimeError(lines[-1] if lines else "yt-dlp failed")
    return json.loads(p.stdout)


def search_target(text: str, n: int = 30, live_only: bool = False) -> str:
    if text.startswith("http"):
        return text
    if live_only:
        q = urllib.parse.quote_plus(text)
        return f"https://www.youtube.com/results?search_query={q}&sp={LIVE_FILTER}"
    return f"ytsearch{n}:{text}"


def to_results(data: dict[str, Any]) -> list[Result]:
    """yt-dlp's flat JSON (a playlist or a single video) -> rows for the results list."""
    out = []
    entries = data["entries"] if "entries" in data else [data]  # an empty playlist stays empty
    for e in entries or []:
        if not e:
            continue
        url = e.get("url") or e.get("webpage_url") or ""
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={e.get('id')}"
        out.append(
            {
                "title": e.get("title") or "?",
                "channel": e.get("channel") or e.get("uploader") or "",
                "channel_url": e.get("channel_url") or "",
                "duration": e.get("duration"),
                "url": url,
                "live": e.get("live_status") == "is_live",
            }
        )
    return out


def search(ytdlp: str, text: str, n: int = 30, live_only: bool = False) -> list[Result]:
    return to_results(run_ytdlp(ytdlp, ["-I", f"1:{n}", search_target(text, n, live_only)]))


def channel_base(url: str) -> str | None:
    """`https://www.youtube.com/@x/videos` -> `https://www.youtube.com/@x`; None for anything
    that is not a channel (a playlist, a video)."""
    m = _CHANNEL.match(url)
    return m.group(1) if m else None


def scan_live_page(chunks: Iterable[str]) -> Result:
    """Read a channel's `/live` page as it arrives and stop as soon as the answer is known.

    Not live: the canonical link is the channel itself, about 60% of the way in. Live: it
    is a watch link and `isLiveNow` follows; a scheduled stream is a watch link too, but
    `isUpcoming`.
    """
    text, canon = "", None
    for chunk in chunks:
        text += chunk
        if canon is None:
            m = _CANONICAL.search(text)
            if m:
                canon = m.group(1)
                if "watch?v=" not in canon:
                    return {"live": False}
        if canon and ('"isLiveNow":true' in text or '"isUpcoming":true' in text):
            break
    if canon and '"isLiveNow":true' in text and '"isUpcoming":true' not in text:
        t = _TITLE.search(text)
        return {"live": True, "url": canon, "title": html.unescape(t.group(1)) if t else "live"}
    return {"live": False}


def live_status(url: str, opener: Callable[..., Any] = urllib.request.urlopen) -> Result | None:
    """Is this channel live now? None for non-channels. Costs up to ~300 KB per call."""
    base = channel_base(url)
    if not base:
        return None
    headers = {
        "User-Agent": UA,
        "Accept-Language": "en",
        "Accept-Encoding": "gzip",
        "Cookie": "SOCS=CAI",
    }
    req = urllib.request.Request(base + "/live", headers=headers)
    with opener(req, timeout=20) as r:
        gz = r.headers.get("Content-Encoding") == "gzip"
        dec = zlib.decompressobj(16 + zlib.MAX_WBITS)

        def chunks() -> Iterable[str]:
            while chunk := r.read(32768):
                yield (dec.decompress(chunk) if gz else chunk).decode("utf-8", "ignore")

        return scan_live_page(chunks())


def parse_takeout_csv(text: str) -> list[Result]:
    """Google Takeout's `subscriptions.csv`: Channel Id, Channel Url, Channel Title."""
    rows = list(csv.reader(io.StringIO(text.lstrip("\N{ZERO WIDTH NO-BREAK SPACE}"))))
    return [
        {"name": r[2], "url": f"https://www.youtube.com/channel/{r[0]}/videos"}
        for r in rows[1:]
        if len(r) >= 3 and r[0].startswith("UC")
    ]


def subs_from_feed(data: dict[str, Any]) -> list[Result]:
    """yt-dlp's flat listing of `/feed/channels` -> saved-channel entries."""
    out = []
    for e in data.get("entries") or []:
        url = e.get("url") or e.get("channel_url") or ""
        if not url.startswith("http") and e.get("id"):
            url = f"https://www.youtube.com/channel/{e['id']}"
        base = channel_base(url)
        if base:
            out.append(
                {"name": e.get("title") or e.get("channel") or base, "url": base + "/videos"}
            )
    return out


def import_subscriptions(path: str | Path, ytdlp: str) -> list[Result]:
    """From a Takeout CSV, or a cookies.txt used once to read the subscription list."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        return parse_takeout_csv(p.read_text("utf-8-sig"))
    subs = subs_from_feed(
        run_ytdlp(ytdlp, ["--cookies", str(p), "https://www.youtube.com/feed/channels"], 300)
    )
    if not subs:
        raise RuntimeError("No subscriptions found: the cookies file may be expired or logged out.")
    return subs
