"""The user's state: favorites, saved channels, volume, the sealed Twitch login.

It lives outside the checkout (`%APPDATA%/radio/radio.json`, or `~/.config/radio`) so a
re-clone or a second checkout keeps it. `RADIO_CONFIG` points it elsewhere (tests).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "twitch": [],  # favorite Twitch logins, in play-preference order
    "bookmarks": [],  # [{"name", "url", "source": "saved" | "sub"}]
    "volume": 70,
    "auto_rotate": True,
    "category": "",
    "tw_live_only": False,
    "yt_live_only": False,
    "twitch_auth": None,  # DPAPI-sealed token, see secret_store
    "twitch_login": None,
}


def config_path(env: dict[str, str] | None = None) -> Path:
    env = dict(os.environ) if env is None else env
    if env.get("RADIO_CONFIG"):
        return Path(env["RADIO_CONFIG"])
    base = env.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "radio" / "radio.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Defaults overlaid with the saved file; a missing or corrupt file is just defaults."""
    path = path or config_path()
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy: the lists must not be shared
    try:
        saved = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        saved = {}
    if isinstance(saved, dict):
        cfg.update(saved)
    for b in cfg["bookmarks"]:
        b.setdefault("source", "saved")
    return cfg


def save_config(cfg: dict[str, Any], path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), "utf-8")
    tmp.replace(path)
