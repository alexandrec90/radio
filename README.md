# Radio

Audio-only Twitch / YouTube radio: mpv + yt-dlp + streamlink with a tkinter picker.
Background listening that never downloads video: about 30 MB an hour from YouTube,
70 MB from Twitch.

Generated from [devkit](https://github.com/alexandrec90/devkit)'s project
template. The agent harness in `scripts/hooks/` is vendored from there — see
`CLAUDE.md`, "Vendored agent harness".

## Install

```bash
winget install shinchiro.mpv yt-dlp.yt-dlp Streamlink.Streamlink   # the three players/fetchers
uv sync --all-extras                                               # .venv from uv.lock
```

The tools are found on `PATH` first, then at their usual winget install locations
(`radio/tools.py`).

## Use

```bash
.venv/Scripts/radio-gui          # the picker window (no console)
.venv/Scripts/radio              # same window, from a terminal
.venv/Scripts/radio tw           # rotate through live Twitch favorites, then follows
.venv/Scripts/radio tw <name>    # one Twitch channel
.venv/Scripts/radio yt <url> --shuffle   # a video, playlist or a channel's /videos
.venv/Scripts/radio search lofi beats    # top 50 YouTube results, back to back
```

In a terminal, mpv's keys work: space pause, `<` `>` previous/next, `9` `0` volume, `q` quit
(in a Twitch rotation, `q` skips to the next live channel).

**The window.** The Twitch tab lists favorites (★, in your order) and, once you connect
your account, the channels you follow (♥), with live status refreshed every two
minutes. *Auto-switch* plays the next live channel when a stream ends. *Browse
category* autocompletes Twitch category names. The YouTube tab searches (optionally
live-only) and keeps saved channels; *Import subscriptions* reads a Google Takeout
`subscriptions.csv` or a one-off `cookies.txt` export, and *Live only* there shows the
channels streaming now.

**Accounts.** Twitch hides follow lists from anyone not logged in as you, so *Connect
Twitch account* takes the `auth-token` cookie from your browser. It is stored sealed
with Windows DPAPI (`radio/secret_store.py`), readable only by your Windows account.

**State** lives in `%APPDATA%/radio/radio.json`, outside the checkout, so a re-clone
keeps it. `RADIO_CONFIG` points it elsewhere.

## Develop

```bash
uv sync --all-extras
pytest                     # everything a CI runner can do
python scripts/e2e.py      # the `local` tier: opens real tkinter windows
```

In VS Code, `Ctrl+Shift+B` runs the default build task and the task quick-pick
(`Ctrl+Shift+P` → "Run Task") lists everything else, each with a one-line `detail`
explaining what it costs and what it touches.


## Layout

```text
radio/                  application code
tests/                tests
scripts/                 project scripts (Python, each with tests)
scripts/hooks/           vendored agent harness — edit upstream in devkit
.devkit.toml      the per-project harness seam (NOT vendored)
```

## CI

`.github/workflows/pr-gate.yml` runs lint, tests, and the harness drift check on
every PR. The drift check is only meaningful when it can see devkit — if it prints
"nothing to do (skipping)", the gate is inert and the wiring needs fixing. Locally,
where `DEVKIT_DIR` is usually unset, `pre-commit run devkit-drift --all-files` is the
same check against the devkit rev pinned in `.pre-commit-config.yaml`.

`.github/dependabot.yml` opens weekly dependency PRs, and
`.github/workflows/dependabot-automerge.yml` merges every one of them once the gate
passes, majors included: the gate is the review, so keep it covering what you care
about. To hold one bump back, close it or comment `@dependabot ignore this major
version`: a removed `automerge` label comes back on Dependabot's next rebase.

That auto-merge workflow is **vendored** from devkit, so `sync-devkit.py --check`
compares it byte-for-byte and editing it here shows up as drift. Keep the gate's title
`PR Gate`: the auto-merge workflow waits on it by name, and a rename makes the merge job
inert without turning anything red.

`.github/actions/setup-python-env/` is **yours**, by contrast. devkit shipped it through
that same channel for one release and pulled it back out when two projects turned out to
install in ways `uv sync` cannot express, so it now arrives from `templates/` as a
one-shot copy: nothing compares it, and rewriting its steps to match how this project
installs is the supported move rather than drift. What owning it costs is the other
direction — later devkit fixes to that file never reach here.
