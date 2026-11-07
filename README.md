# herdr4paseo

A terminal UI for one [Paseo](https://paseo.sh) agent: its live log on top, a prompt box underneath. Run it in any terminal pane, including a [Herdr](https://herdr.dev) pane, to watch an agent, steer it, answer its permission requests, use its slash commands, stop it or start a new one, without opening the Paseo app.

The agent keeps running in the Paseo daemon. `herdr4paseo` is only a client. Quitting it never interrupts the agent, and the Paseo desktop or mobile app can be attached to the same agent at the same time.

```text
┌ alpha (7dba08f)  running | send: steer | full log ─────────────────┐
│ [User] fix the failing test                                         │
│ [Thought] The failure is in the date parser...                      │
│ [Shell] pytest tests/test_dates.py                                  │
│ I found the bug: the parser ignores the timezone offset.            │
├─────────────────────────────────────────────────────────────────────┤
│ 1 pending: Bash: rm -rf build  (Ctrl+A allow, Ctrl+D deny)          │
│ > /compact [focus]  Compact the conversation                        │
│   /context          Show context usage                              │
│ ┌ prompt ───────────────────────────────────────────────────────┐   │
│ │ /co                                                           │   │
│ └───────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Why

Paseo agents belong to the Paseo daemon, and `paseo attach` is a read-only stream. If you live in a terminal multiplexer such as Herdr, you want to watch and steer a Paseo agent from a pane without touching its run. See [getpaseo/paseo Discussion #4070](https://github.com/getpaseo/paseo/discussions/4070) for the wider request. This tool is the stopgap for the "Paseo owns the agent, my terminal fronts it" direction. For the opposite direction (Herdr owns the agent, Paseo mirrors it) see [sdananjay/paseo-herdr](https://github.com/sdananjay/paseo-herdr), an alpha plugin for OMP agents.

## Install

Needs Python 3.11+ and the `paseo` CLI on `PATH`, with the Paseo daemon running.

```sh
uv tool install git+https://github.com/djbclark/herdr4paseo
```

To work on it, clone the repo and run `uv tool install --editable .`.

## Quick start

```sh
herdr4paseo              # pick an agent from a list
herdr4paseo 7dba08f      # attach by id, short id or unambiguous prefix
herdr4paseo --tail 200 --behavior interrupt 7dba08f
```

Find an agent id with `paseo ls -g -a`. Type a prompt and press Enter to send it. Type `/` to see slash commands.

| Option | Default | Meaning |
| --- | --- | --- |
| `agent` | pick from a list | Agent id, short id or unambiguous id prefix |
| `--tail N` | 50 | Log entries to show when attaching |
| `--behavior steer\|interrupt` | `steer` | How a send treats a turn that is still running. `interrupt` stops the turn and redirects it; `steer` steers the running turn and, per Paseo, falls back to interrupting it if steering is unavailable. |

## Keys

| Key | Action |
| --- | --- |
| Enter | Send the prompt |
| Ctrl+J, Shift+Enter | Newline in the prompt |
| `/`, then Tab, Up, Down | Slash-command suggestions: Tab completes the highlighted command, Up and Down choose, Enter sends exactly what you typed |
| Ctrl+T | Toggle send behaviour: `steer` or `interrupt` |
| Ctrl+O | Toggle a tools-only log view |
| Ctrl+G | Switch agent: type to filter by id, status, name, provider or directory, then Enter |
| Ctrl+P, Ctrl+N | Prompt history, previous and next (kept between runs) |
| Ctrl+R | Start a new agent (`paseo run --no-wait`): prompt, directory, provider (prefilled from the current agent); then attaches to it |
| Ctrl+X | Stop the agent (`paseo stop`), after a y/n confirmation |
| Ctrl+A, Ctrl+D | Allow or deny the agent's pending permission requests (only active while some are pending; asks to confirm) |
| Ctrl+Q | Quit (the agent keeps running) |

The header shows the agent's status (polled every 3 s), the send behaviour and the log view. A failed send keeps your text in the box and prints the error in the log.

The terminal bell rings, with a yellow `alert:` line in the log, when the shown agent goes from running to idle or a new permission request appears. If the log stream ends (for example the daemon restarts), it reattaches by itself every 3 s.

## Environment

| Variable | Effect |
| --- | --- |
| `PASEO_HOST`, `PASEO_HOME` | Select a daemon, exactly as for the `paseo` CLI. They also tell the slash-command lookup where to connect. |
| `HERDR4PASEO_HISTORY` | Path of the prompt-history file (default `~/.local/state/herdr4paseo/history.json`, the last 200 prompts, shared by all agents). |
| `PASEO_BIN` | Path to the `paseo` executable to run (default `paseo`). The tests point it at a fake. |

## Limits

1. It is a log view, not the agent's own TUI: no PTY features. Slash commands work because `paseo send` passes `/context`, `/compact` and skills such as `/steps` through to the provider. The Paseo app's own commands (for example `/exit`) are client-side in Paseo and do not exist here.
2. Permission requests: a banner lists the shown agent's pending requests (polled every 3 s). Ctrl+A or Ctrl+D opens a confirmation listing them; `y` answers each listed request by id with `paseo permit allow|deny`, so a request that arrives after you looked is never approved blind. While none are pending, Ctrl+A and Ctrl+D keep their prompt-editing meaning (line start, delete).
3. Slash suggestions come from the daemon's `list_commands_request`, the one request the `paseo` CLI does not expose, over its local WebSocket. It is read-only. The daemon's local credential is read from `$PASEO_HOME/local-credential` and sent only to a loopback daemon. A remote daemon that needs a password gets no suggestions; typed commands still send.
4. Log entries are coloured by the `[Tag]` prefix `paseo logs` prints; untagged continuation lines are plain.
5. `paseo send` text beginning with `-` gets one leading space so the CLI does not read it as a flag.
6. Ctrl+R needs a provider because `paseo run` refuses to start without one; it is prefilled from the current agent. Worktrees, models and output schemas are not offered: use the `paseo` CLI.
7. Checked against a live daemon on 2026-10-30: the `paseo` calls for `permit allow|deny`, `run`, `stop` and `ls`. The TUI's new keys (Ctrl+R, Ctrl+X, the bell, reconnect, the picker filter) are covered by tests against fakes only.

## More documentation

1. [docs/usage.md](docs/usage.md): walkthroughs for the common jobs, and troubleshooting.
2. [docs/architecture.md](docs/architecture.md): which `paseo` commands it runs, the one WebSocket request, the security notes, the code layout and how to test.

## Development

```sh
uv run --group dev pytest -q
```

The tests drive the app with a fake `paseo` executable (`tests/fake_paseo.py`, selected through `PASEO_BIN`) and a fake daemon WebSocket (`tests/fake_daemon.py`), so they never touch a real daemon.


## Upstream artifacts

1. [getpaseo/paseo Discussion #4070](https://github.com/getpaseo/paseo/discussions/4070) — request for a terminal front-end while Paseo owns the agent.


## Related djbclark Herdr repos

| Repo | Role |
| --- | --- |
| [djbclark/herdr](https://github.com/djbclark/herdr) | Fork of [herdrdev/herdr](https://github.com/herdrdev/herdr) |
| [herdr-plain-line](https://github.com/djbclark/herdr-plain-line) | Local plugin: plain-English popup for tab/workspace rename and create |
| [herdr-sleeper](https://github.com/djbclark/herdr-sleeper) | Plugin: sleep idle agent panes, wake later |
| [herdr4paseo](https://github.com/djbclark/herdr4paseo) | Terminal UI to watch/steer a Paseo agent from a pane |
| [paseo4herdr](https://github.com/djbclark/paseo4herdr) | Paseo plugin mirroring OMP agents that run in Herdr |


## License

MIT
