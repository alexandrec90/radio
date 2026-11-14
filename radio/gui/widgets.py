"""Theme, the list widget every panel uses, and an autocomplete dropdown for an Entry."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

BG, PANEL, FG, DIM, ACCENT, LIVE = "#1b1d22", "#25282f", "#e6e6e6", "#8a8f98", "#9b6dff", "#ff4d5e"


def apply_style(root: tk.Misc) -> ttk.Style:
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(
        ".",
        background=BG,
        foreground=FG,
        fieldbackground=PANEL,
        bordercolor=PANEL,
        font=("Segoe UI", 10),
    )
    s.configure("TNotebook", background=BG, borderwidth=0)
    s.configure("TNotebook.Tab", background=PANEL, foreground=DIM, padding=(14, 6))
    s.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "white")])
    s.configure("TButton", background=PANEL, foreground=FG, padding=(10, 4), borderwidth=0)
    s.map("TButton", background=[("active", ACCENT)])
    s.configure("Accent.TButton", background=ACCENT, foreground="white")
    s.configure(
        "Treeview",
        background=PANEL,
        fieldbackground=PANEL,
        foreground=FG,
        rowheight=24,
        borderwidth=0,
    )
    s.configure("Treeview.Heading", background=BG, foreground=DIM, borderwidth=0)
    s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
    s.configure("TEntry", foreground=FG, insertcolor=FG)
    s.configure("TCheckbutton", background=BG, foreground=FG)
    s.map("TCheckbutton", background=[("active", BG)])
    s.configure("Title.TLabel", font=("Segoe UI Semibold", 12))
    s.configure("Dim.TLabel", foreground=DIM)
    s.configure("Horizontal.TScale", background=BG, troughcolor=PANEL)
    s.configure(
        "Vertical.TScrollbar",
        background=PANEL,
        troughcolor=BG,
        arrowcolor=DIM,
        bordercolor=BG,
        lightcolor=PANEL,
        darkcolor=PANEL,
    )
    return s


def make_tree(
    parent: tk.Misc, columns: tuple[str, ...], widths: tuple[int, ...], height: int = 8
) -> tuple[ttk.Frame, ttk.Treeview]:
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height, selectmode="browse")
    for col, width in zip(columns, widths, strict=True):
        tree.heading(col, text=col)
        tree.column(col, width=width, stretch=width > 200, anchor="w")
    bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    tree.tag_configure("live", foreground=LIVE)
    tree.tag_configure("off", foreground=DIM)
    return frame, tree


def selected(tree: ttk.Treeview) -> str | None:
    sel = tree.selection()
    return sel[0] if sel else None


class Suggest:
    """A dropdown under `entry` filled by `fetch(text)` (run in the background) as the user
    types; Up/Down move, Enter or a click calls `on_pick(item)`."""

    def __init__(
        self,
        app: Any,
        entry: ttk.Entry,
        fetch: Callable[[str], list[Any]],
        label: Callable[[Any], str],
        on_pick: Callable[[Any], None],
    ) -> None:
        self.app, self.entry, self.fetch, self.label, self.on_pick = (
            app,
            entry,
            fetch,
            label,
            on_pick,
        )
        self.items: list[Any] = []
        self._after: str | None = None
        self._seq = 0
        self.top = tk.Toplevel(entry)
        self.top.overrideredirect(True)
        self.top.withdraw()
        self.listbox = tk.Listbox(
            self.top,
            bg=PANEL,
            fg=FG,
            selectbackground=ACCENT,
            selectforeground="white",
            highlightthickness=1,
            highlightbackground=ACCENT,
            borderwidth=0,
            activestyle="none",
            font=("Segoe UI", 10),
            height=8,
        )
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<ButtonRelease-1>", lambda e: self.pick())
        entry.bind("<KeyRelease>", self._key)
        entry.bind("<Down>", lambda e: self.move(1))
        entry.bind("<Up>", lambda e: self.move(-1))
        entry.bind("<Escape>", lambda e: self.hide())
        entry.bind("<FocusOut>", lambda e: entry.after(250, self.hide))

    def _key(self, event: Any) -> None:
        if event.keysym in ("Down", "Up", "Return", "Escape", "Tab"):
            return
        if self._after:
            self.entry.after_cancel(self._after)
        self._after = self.entry.after(250, self.query)

    def query(self) -> None:
        text = self.entry.get().strip()
        if len(text) < 2:
            self.hide()
            return
        self._seq += 1
        seq = self._seq
        self.app.bg(lambda: self.fetch(text), lambda items: self.show(items, seq), lambda e: None)

    def show(self, items: list[Any], seq: int | None = None) -> None:
        if (seq is not None and seq != self._seq) or not items:
            if not items:
                self.hide()
            return
        self.items = items
        self.listbox.delete(0, "end")
        for item in items:
            self.listbox.insert("end", self.label(item))
        self.listbox.configure(height=min(10, len(items)))
        x, y = self.entry.winfo_rootx(), self.entry.winfo_rooty() + self.entry.winfo_height()
        width = max(self.entry.winfo_width(), 320)
        self.top.geometry(f"{width}x{self.listbox.winfo_reqheight()}+{x}+{y}")
        self.top.deiconify()
        self.top.lift()

    @property
    def visible(self) -> bool:
        return self.top.state() != "withdrawn"

    def move(self, delta: int) -> str | None:
        if not self.visible:
            return None
        cur = self.listbox.curselection()
        i = max(0, min(len(self.items) - 1, (cur[0] + delta) if cur else 0))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(i)
        self.listbox.see(i)
        return "break"

    def pick(self) -> bool:
        cur = self.listbox.curselection()
        if not self.visible or not cur:
            return False
        item = self.items[cur[0]]
        self.hide()
        self.on_pick(item)
        return True

    def hide(self) -> None:
        self.top.withdraw()
