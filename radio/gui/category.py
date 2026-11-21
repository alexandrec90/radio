"""Browse who is live in a Twitch category, with the name autocompleted as you type."""

from __future__ import annotations

from tkinter import messagebox, ttk
from typing import Any

from radio import twitch
from radio.gui.widgets import Suggest, make_tree, selected


def category_label(node: dict[str, Any]) -> str:
    return f"{node['name']}   \N{EM DASH}   {node.get('viewersCount') or 0:,} viewers"


class CategoryBrowser:
    def __init__(self, app: Any, parent: ttk.Frame, tab: Any) -> None:
        self.app, self.tab, self.cfg = app, tab, app.cfg
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Label(row, text="Browse category", style="Title.TLabel").pack(side="left")
        self.entry = ttk.Entry(row, width=34)
        self.entry.insert(0, self.cfg.get("category", ""))
        self.entry.pack(side="left", padx=8)
        self.suggest = Suggest(app, self.entry, twitch.search_categories, category_label, self.pick)
        self.entry.bind("<Return>", lambda e: self.enter())
        ttk.Button(row, text="Browse", command=self.browse).pack(side="left")
        ttk.Button(row, text="\N{BLACK STAR} Favorite", command=self.favorite).pack(side="right")
        ttk.Button(
            row,
            text="\N{BLACK RIGHT-POINTING TRIANGLE} Play",
            style="Accent.TButton",
            command=self.play,
        ).pack(side="right", padx=4)
        frame, self.tree = make_tree(parent, ("Channel", "Viewers", "Title"), (140, 70, 520), 7)
        frame.pack(fill="both", expand=True, pady=4)
        self.tree.bind("<Double-1>", lambda e: self.play())

    def enter(self) -> None:
        """Enter takes the highlighted suggestion if there is one, else the typed name."""
        if not self.suggest.pick():
            self.browse()

    def pick(self, node: dict[str, Any]) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, node["name"])
        self.browse()

    def browse(self) -> None:
        self.suggest.hide()
        name = self.entry.get().strip()
        if not name:
            return
        self.cfg["category"] = name
        self.app.save()
        self.app.bg(lambda: twitch.category_streams(name), lambda res: self.show(name, res))

    def show(self, name: str, streams: list[dict[str, Any]] | None) -> None:
        if streams is None:
            messagebox.showinfo(
                "Radio",
                f"No Twitch category named \N{LEFT DOUBLE QUOTATION MARK}{name}"
                "\N{RIGHT DOUBLE QUOTATION MARK}. Pick one from the dropdown.",
                parent=self.app.root,
            )
            return
        self.tree.delete(*self.tree.get_children())
        for node in streams:
            b = node["broadcaster"]
            self.tree.insert(
                "",
                "end",
                iid=b["login"],
                values=(b["displayName"], f"{node['viewersCount']:,}", node["title"]),
            )
            self.tab.info.setdefault(
                b["login"].lower(),
                {
                    "login": b["login"],
                    "displayName": b["displayName"],
                    "stream": {"title": node["title"], "viewersCount": node["viewersCount"]},
                },
            )

    def play(self) -> None:
        login = selected(self.tree)
        if login:
            self.tab.play(login)

    def favorite(self) -> None:
        login = selected(self.tree)
        if login:
            self.tab.add_favorite(login)
