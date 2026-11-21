"""Small formatting helpers shared by the GUI and the CLI."""

from __future__ import annotations


def format_duration(seconds: float | None) -> str:
    """`75` -> `1:15`, `3725` -> `1:02:05`; `None` (no length known) reads as a live stream."""
    if seconds is None:
        return "live"
    s = max(0, int(seconds))
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"
