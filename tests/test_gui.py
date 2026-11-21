"""The real window, driven without mpv or the network. `local`: needs a display."""

from tkinter import simpledialog

import pytest
from conftest import user

from radio import config, twitch, youtube
from radio.gui import app as app_module
from radio.gui import channels as channels_module
from radio.gui.account import ConnectDialog, TwitchAccount
from radio.gui.app import App
from radio.gui.category import CategoryBrowser
from radio.gui.channels import ChannelsPanel
from radio.gui.twitch_tab import TwitchTab
from radio.gui.widgets import Suggest, apply_style, make_tree, selected
from radio.gui.youtube_tab import YouTubeTab

pytestmark = pytest.mark.local


@pytest.fixture
def net(monkeypatch):
    """Fake Twitch: favorites `fav` (live) and `quiet` (offline); follows only with a token."""
    state = {
        "status": {"fav": user("fav", live=True, viewers=5), "quiet": user("quiet")},
        "follows": [user("big", live=True, viewers=900), user("off")],
    }
    monkeypatch.setattr(
        twitch,
        "status",
        lambda logins: {
            k: v for k, v in state["status"].items() if k in {x.lower() for x in logins}
        },
    )
    monkeypatch.setattr(twitch, "follows", lambda token: list(state["follows"]))
    return state


@pytest.fixture
def window(root, cfg, fake_player, net, dialogs):
    cfg["twitch"] = ["fav", "quiet"]
    a = App(root, cfg=cfg, player=fake_player)
    a.drain()
    return a


def rows(tree):
    return list(tree.get_children())


def test_app_builds_and_lists_favorites(window):
    assert isinstance(window.twitch, TwitchTab) and isinstance(window.youtube, YouTubeTab)
    assert rows(window.twitch.tree) == ["fav", "quiet"]
    assert window.twitch.tree.item("fav", "tags") == ("live",)


def test_live_only_filter_and_persistence(window):
    window.twitch.live_only.set(True)
    window.twitch._setting("tw_live_only", window.twitch.live_only)
    assert rows(window.twitch.tree) == ["fav"]
    assert config.load_config()["tw_live_only"] is True


def test_play_selected_and_offline(window, fake_player, dialogs):
    window.twitch.tree.selection_set("fav")
    window.twitch.play_selected()
    assert fake_player.calls[-1][0] == "twitch" and fake_player.calls[-1][1][0] == "fav"
    window.twitch.tree.selection_set("quiet")
    window.twitch.play_selected()
    assert dialogs[-1] == ("showinfo", "quiet is offline.")


def test_rotate_plays_first_live_then_waits_when_it_ends(window, fake_player, net):
    window.twitch.rotate()
    window.drain()
    assert fake_player.calls[-1][1][0] == "fav"
    window.twitch.on_end("twitch", "fav")  # fav is the only live one, and it just ended
    window.drain()
    assert window.waiting_for_live
    assert fake_player.calls[-1] == ("stop", None)
    window.twitch.on_end("youtube", None)  # a YouTube end never rotates
    window.drain()
    assert fake_player.calls[-1] == ("stop", None)


def test_first_live_with_nobody_live_says_so(window, net, dialogs):
    net["status"] = {"fav": user("fav"), "quiet": user("quiet")}  # Twitch returns offline users too
    window.twitch.rotate(user=True)
    window.drain()
    assert "None of your channels" in dialogs[-1][1]


def test_favorites_toggle_move_and_add(window, net):
    tab = window.twitch
    tab.tree.selection_set("quiet")
    tab.move_favorite(-1)
    assert window.cfg["twitch"] == ["quiet", "fav"]
    tab.toggle_favorite()
    assert window.cfg["twitch"] == ["fav"]
    tab.add_entry.insert(0, "https://www.twitch.tv/newone/")
    tab.add_favorite()
    window.drain()
    assert window.cfg["twitch"] == ["fav", "newone"]
    assert config.load_config()["twitch"] == ["fav", "newone"]


def test_connected_account_adds_follows(window, monkeypatch):
    monkeypatch.setattr("radio.secret_store.seal", lambda s: "sealed:" + s)
    account = window.twitch.account
    assert isinstance(account, TwitchAccount)
    assert account.button.cget("text").startswith("Connect Twitch account")
    account.connected({"displayName": "Me"}, "tok")
    window.drain()
    assert window.cfg["twitch_auth"] == "sealed:tok" and "Me" in account.button.cget("text")
    assert rows(window.twitch.tree) == ["fav", "quiet", "big", "off"]
    window.twitch.tree.selection_set("big")
    window.twitch.play_selected()
    assert window.player.calls[-1][1][2] == "tok"
    account.click()  # askyesno is patched to "yes": disconnect
    window.drain()
    assert account.token is None and window.cfg["twitch_auth"] is None
    assert rows(window.twitch.tree) == ["fav", "quiet"]


def test_saved_token_is_unsealed_and_a_bad_one_dropped(
    root, cfg, fake_player, net, dialogs, monkeypatch
):
    monkeypatch.setattr("radio.secret_store.unseal", lambda s: s.removeprefix("sealed:"))
    cfg.update(twitch_auth="sealed:tok", twitch_login="Me")
    assert App(root, cfg=cfg, player=fake_player).twitch.account.token == "tok"

    def foreign(s):
        raise OSError("sealed by another user")

    monkeypatch.setattr("radio.secret_store.unseal", foreign)
    a = App(root, cfg=cfg, player=fake_player)
    assert a.twitch.account.token is None and cfg["twitch_auth"] is None


def test_expired_token_is_forgotten(window, monkeypatch, dialogs):
    window.twitch.account.token = "dead"

    def expired(token):
        raise PermissionError("Twitch login expired.")

    monkeypatch.setattr(twitch, "follows", expired)
    window.twitch.refresh()
    window.drain()
    assert window.twitch.account.token is None and dialogs[-1][0] == "showwarning"


def test_background_errors_reach_the_error_dialog(window, dialogs):
    def boom():
        raise RuntimeError("network down")

    window.bg(boom, lambda r: None)
    window.drain()
    assert dialogs[-1] == ("showerror", "network down")


def test_connect_dialog_verifies_token(window, monkeypatch):
    got = []
    monkeypatch.setattr(twitch, "me", lambda token: {"displayName": "Me", "token": token})
    d = ConnectDialog(window, lambda u, t: got.append((u["displayName"], t)))
    d.entry.insert(0, 'OAuth "abc"')
    d.connect()
    window.drain()
    assert got == [("Me", "abc")]

    def refused(token):
        raise PermissionError("nope")

    monkeypatch.setattr(twitch, "me", refused)
    d2 = ConnectDialog(window, lambda u, t: got.append(t))
    d2.entry.insert(0, "bad")
    d2.connect()
    window.drain()
    assert "nope" in d2.message.cget("text")


def test_category_browser(window, monkeypatch, dialogs):
    streams = [
        {"title": "T", "viewersCount": 7, "broadcaster": {"login": "cat1", "displayName": "Cat1"}}
    ]
    monkeypatch.setattr(
        twitch, "category_streams", lambda name: streams if name == "Chess" else None
    )
    browser = window.twitch.category
    assert isinstance(browser, CategoryBrowser)
    browser.pick({"name": "Chess"})
    window.drain()
    assert rows(browser.tree) == ["cat1"]
    browser.tree.selection_set("cat1")
    browser.play()
    assert window.player.calls[-1][1][0] == "cat1"
    browser.favorite()
    assert "cat1" in window.cfg["twitch"]
    browser.entry.delete(0, "end")
    browser.entry.insert(0, "Nope")
    browser.enter()  # no suggestion highlighted: Enter browses the typed name
    window.drain()
    assert "No Twitch category" in dialogs[-1][1]


def test_suggest_dropdown(window):
    entry = window.twitch.category.entry
    picked = []
    s = Suggest(
        window, entry, lambda text: [{"name": text.upper()}], lambda n: n["name"], picked.append
    )
    entry.delete(0, "end")
    entry.insert(0, "ch")
    s.query()
    window.drain()
    window.root.update()
    assert s.visible and s.listbox.get(0) == "CH"
    assert s.move(1) == "break"
    assert s.pick() and picked == [{"name": "CH"}] and not s.visible
    s.show([])
    assert not s.visible and s.move(1) is None and not s.pick()


def test_widgets(root):
    apply_style(root)
    _frame, tree = make_tree(root, ("A", "B"), (50, 300), 3)
    tree.insert("", "end", iid="x", values=("1", "2"))
    assert selected(tree) is None
    tree.selection_set("x")
    assert selected(tree) == "x"


def test_youtube_search_and_play(window, monkeypatch):
    results = [
        {
            "title": "A",
            "channel": "C",
            "channel_url": "https://www.youtube.com/channel/UC1",
            "duration": 60,
            "url": "https://y/a",
            "live": False,
        },
        {
            "title": "B",
            "channel": "C",
            "channel_url": "",
            "duration": None,
            "url": "https://y/b",
            "live": True,
        },
    ]
    monkeypatch.setattr(youtube, "search", lambda exe, text, live_only=False: results)
    tab = window.youtube
    tab.search("lofi")
    window.drain()
    assert rows(tab.tree) == ["0", "1"] and tab.tree.item("1", "tags") == ("live",)
    tab.tree.selection_set("1")
    tab.play()
    urls, kw = window.player.calls[-1][1]
    assert urls == ["https://y/a", "https://y/b"] and kw["start"] == 1
    tab.tree.selection_set("0")
    tab.save_channel()
    assert window.cfg["bookmarks"][-1]["url"] == "https://www.youtube.com/channel/UC1/videos"


def test_channels_live_filter_and_play(window, monkeypatch):
    panel = window.youtube.channels
    assert isinstance(panel, ChannelsPanel)
    panel.add(
        [
            {"name": "Live one", "url": "https://www.youtube.com/@live/videos", "source": "sub"},
            {"name": "Quiet", "url": "https://www.youtube.com/@quiet/videos", "source": "saved"},
        ]
    )
    monkeypatch.setattr(
        channels_module,
        "check_all",
        lambda urls: {
            urls[0]: {"live": True, "url": "https://y/watch?v=now", "title": "Now"},
            urls[1]: {"live": False},
        },
    )
    panel.live_only.set(True)
    panel.toggle_live()
    window.drain()
    assert rows(panel.tree) == ["0"] and "1 live" in panel.status.cget("text")
    panel.tree.selection_set("0")
    panel.play()
    assert window.player.calls[-1][1][0] == ["https://y/watch?v=now"]
    panel.play(shuffle=True)
    assert window.player.calls[-1][1][1]["whole_list"] is True
    panel.live_only.set(False)
    panel.toggle_live()
    panel.tree.selection_set("1")
    panel.remove()
    assert [b["name"] for b in window.cfg["bookmarks"]] == ["Live one"]


def test_channels_import_and_add_url(window, monkeypatch, dialogs):
    panel = window.youtube.channels
    panel.imported([{"name": "Sub", "url": "https://www.youtube.com/@sub/videos"}])
    assert window.cfg["bookmarks"][-1]["source"] == "sub" and "added 1" in dialogs[-1][1]
    answers = iter(["https://www.youtube.com/@typed", "Typed"])
    monkeypatch.setattr(simpledialog, "askstring", lambda *a, **kw: next(answers))
    panel.add_url()
    assert window.cfg["bookmarks"][-1] == {
        "name": "Typed",
        "url": "https://www.youtube.com/@typed/videos",
        "source": "saved",
    }
    monkeypatch.setattr(youtube, "search", lambda exe, text, live_only=False: [])
    panel.tree.selection_set(str(len(window.cfg["bookmarks"]) - 1))
    panel.browse()
    assert window.youtube.entry.get() == "https://www.youtube.com/@typed/videos"


def test_transport_and_close(window, fake_player, monkeypatch):
    destroyed = []
    monkeypatch.setattr(window.root, "destroy", lambda: destroyed.append(True))
    window.player.kind = "youtube"
    window.next_item()
    assert fake_player.calls[-1] == ("command", ("playlist-next",))
    window.set_volume(33)
    window.stop()
    assert fake_player.calls[-1] == ("stop", None)
    window._show(None)
    assert window.np_title.cget("text") == "Nothing playing"
    window._show({"media-title": "Song", "time-pos": 1})
    assert window.np_title.cget("text") == "Song"
    window.close()
    assert config.load_config()["volume"] == 33
    assert destroyed == [True]


def test_main_opens_the_window(monkeypatch):
    made = []

    class FakeTk:
        def mainloop(self):
            made.append("loop")

    monkeypatch.setattr(app_module.tk, "Tk", FakeTk)
    monkeypatch.setattr(app_module, "App", lambda root: made.append("app"))
    app_module.main()
    assert made == ["app", "loop"]
