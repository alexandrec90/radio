import json
from pathlib import Path

from radio import config


def test_config_path_env_override():
    assert config.config_path({"RADIO_CONFIG": "/x/y.json"}) == Path("/x/y.json")


def test_config_path_under_appdata():
    assert config.config_path({"APPDATA": "/appdata"}) == Path("/appdata/radio/radio.json")


def test_config_path_falls_back_to_home_config():
    p = config.config_path({})
    assert p.parts[-3:] == (".config", "radio", "radio.json")


def test_missing_file_gives_defaults(isolated_config):
    cfg = config.load_config()
    assert cfg == config.DEFAULTS
    cfg["twitch"].append("x")
    assert config.DEFAULTS["twitch"] == []  # defaults are copied, not shared


def test_round_trip(isolated_config):
    cfg = config.load_config()
    cfg["twitch"] = ["a", "b"]
    cfg["volume"] = 40
    config.save_config(cfg)
    assert config.load_config()["twitch"] == ["a", "b"]
    assert config.load_config()["volume"] == 40


def test_save_creates_parent_dir(tmp_path):
    target = tmp_path / "deep" / "dir" / "radio.json"
    config.save_config({"volume": 1}, target)
    assert json.loads(target.read_text())["volume"] == 1


def test_corrupt_file_gives_defaults(isolated_config):
    isolated_config.write_text("{not json")
    assert config.load_config()["volume"] == 70


def test_non_object_json_gives_defaults(isolated_config):
    isolated_config.write_text("[1, 2]")
    assert config.load_config()["twitch"] == []


def test_old_bookmarks_get_a_source(isolated_config):
    isolated_config.write_text(json.dumps({"bookmarks": [{"name": "n", "url": "u"}]}))
    assert config.load_config()["bookmarks"][0]["source"] == "saved"
