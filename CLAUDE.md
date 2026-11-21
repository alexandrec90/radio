# Radio

Audio-only Twitch / YouTube radio: mpv + yt-dlp + streamlink with a tkinter picker

**The repository names no game, publisher or store**, in code, tests, docs or commit
messages; it stays generic. Example data in tests uses neutral names.

## Tech Stack

| Layer | Choice |
| --- | --- |
| Language | Python 3.12, standard library only at runtime |
| UI | tkinter (`radio/gui/`) |
| External programs | mpv, yt-dlp, streamlink, found by `radio/tools.py` |
| Tests | pytest; the `local` tier (`scripts/e2e.py`) opens real windows |
| Lint | ruff, mypy |

No Docker stack and no `.env`: nothing here publishes a port.

## Things the code cannot tell you

- **User state is outside the checkout**: `%APPDATA%/radio/radio.json` (`radio/config.py`),
  so a re-clone or a second checkout keeps favorites and the Twitch login. `RADIO_CONFIG`
  overrides the path; every test points it into `tmp_path`.
- **The Twitch token is DPAPI-sealed** for the Windows user (`radio/secret_store.py`). A
  config copied to another user or PC cannot unseal it, and the app drops it and asks to
  reconnect rather than failing.
- **Twitch's follow list needs the user's own `auth-token` cookie**; public follow lists
  are gone. The GraphQL client id in `radio/twitch.py` is Twitch's public web one.
- **A YouTube live check costs ~300 KB per channel** (the `/live` page), so it runs two at
  a time and only on demand or every ten minutes while the filter is on. Keep it that
  way: the app is meant to run beside a latency-sensitive game.
- **`mpv.exe` is a GUI-subsystem program**: a shell does not wait for it and its keys do not
  reach the terminal. The CLI uses `mpv.com` (`Tools.mpv_console`).

## Tooling

### Scripts and the vendored harness

Both are covered by **`.claude/rules/engineering.md`** — script conventions (pure
importable functions, stdlib-only hooks, tests in the same change), the failure-artifact
rule, and how the `.devkit.toml` seam works. That file is vendored from
[devkit](https://github.com/alexandrec90/devkit) and drift-gated, so it is the
authority; this file does not repeat it.

### VS Code tasks

- A task lives in the workspace file and dispatches through devkit's
  `devkit_project.py`, never in `.vscode/tasks.json`; that file's comment says why.
- A script a task runs starts as `python <script>` under the machine's `python`, not
  this project's `.venv`, with no console. It imports only the standard library until
  it has handed itself to the `.venv`, as `scripts/run-tests.py` does, and it cannot
  rely on Ctrl+C: a task that serves until stopped has to watch for its parent going.
- Use `"type": "process"` so VS Code monitors the process directly — that is what
  makes the spinner stop and the exit-code icon appear reliably.
- Set `"close": false` in `presentation` so the terminal stays open for review.
- **Wrap with `notify-wrap.py`** for the completion toast; never call `notify.py`
  from inside a script. Notifications are a task-layer concern only.
- Label convention: `"Domain: Title Case Action"`, and **every task carries a
  `detail`** — that is the second line in the quick-pick, and the only place a
  one-click action can state its cost or blast radius.

### Failure artifacts (fix from a file, not from the terminal)

Any task or script whose failures an agent is expected to act on must persist the
failure to a **parseable artifact file** under `logs/`. Never rely on streamed
terminal output — it scrolls away and buries the signal. Keep the terminal to a
status line plus the artifact path; put everything needed to diagnose in the file.
Write the artifact on failure too, not just success, and overwrite per run.


## Testing

**`.claude/rules/engineering.md`** is the authority: tests ship in the same commit,
every testable unit of logic is covered, regression test first, targeted runs locally
and full runs in CI.

Add this project's specifics *below* — fixtures, isolation rules, markers, what to mock
and where — but do not restate the policy above. It is vendored and drift-gated; a copy
here is a fork that will disagree with it the first time either is edited.

- **No test touches the network, mpv or the real config.** Twitch and YouTube calls take an
  injectable `query` / `opener` / `run`, or are monkeypatched at the module (`twitch.status`);
  `Player` takes a fake `popen`; `conftest.FakePlayer` stands in for it in the GUI.
- **`local` marks tests that open a tkinter window** (`tests/test_gui.py`). `addopts`
  deselects them; `scripts/e2e.py` runs them. They share one session `Tk` root, emptied
  after each test: a fresh `Tk()` per test fails intermittently on Windows.
- **`App.drain()`** finishes all background work and applies it on the test's thread;
  GUI tests call it instead of running a mainloop.

## Guardrails

Baseline guardrails — including the instruction-file feedback loop (**never silently
work around a bad instruction**) — are in `.claude/rules/engineering.md`. Rules for
writing skills and rules themselves are in `.claude/rules/authoring.md`. Cross-reference
this project's own scoped rules here, one line each.
