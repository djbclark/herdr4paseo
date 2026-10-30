# herdr4paseo

A small terminal UI that shows one [Paseo](https://paseo.sh) agent's log with a prompt box under it. It is built entirely on the `paseo` CLI (`paseo logs -f` for output, `paseo send` for input), so it works anywhere a terminal does, including a [Herdr](https://herdr.dev) pane.

The agent keeps running in the Paseo daemon. `herdr4paseo` is only a client: quitting it never interrupts the agent, and the Paseo desktop or mobile app can be attached to the same agent at the same time.

## Why

Paseo agents belong to the Paseo daemon, and `paseo attach` is a read-only stream. If you live in a terminal multiplexer such as Herdr, you want to watch and steer a Paseo agent from a pane without leaving it or touching the agent's run. See [getpaseo/paseo Discussion #4070](https://github.com/getpaseo/paseo/discussions/4070) for the wider request. This tool is the stopgap for the "Paseo owns the agent, my terminal fronts it" direction. For the opposite direction (Herdr owns the agent, Paseo mirrors it) see [sdananjay/paseo-herdr](https://github.com/sdananjay/paseo-herdr), an alpha plugin for OMP agents.

## Install

Needs Python 3.11+ and the `paseo` CLI on `PATH`.

```sh
uv tool install git+https://github.com/djbclark/herdr4paseo
```

## Use

```sh
herdr4paseo              # pick an agent from a list
herdr4paseo 7dba08f      # attach to an agent by id, short id or unambiguous prefix
herdr4paseo --tail 200 --behavior interrupt 7dba08f
```

| Key | Action |
| --- | --- |
| Enter | Send the prompt |
| Ctrl+J, Shift+Enter | Newline in the prompt |
| Ctrl+T | Toggle send behaviour: `steer` (default) or `interrupt` |
| Ctrl+O | Toggle a tools-only log view (`paseo logs --filter tools`) |
| Ctrl+G | Switch agent |
| Ctrl+P, Ctrl+N | Prompt history, previous and next |
| Ctrl+A, Ctrl+D | Allow or deny the agent's pending permission requests (only active while some are pending; asks to confirm) |
| Ctrl+Q | Quit (the agent keeps running) |

The header shows the agent's status (polled every 3 s), the send behaviour and the log view. A failed send keeps your text in the box and prints the error in the log.

To talk to a remote daemon, set `PASEO_HOST` (or `PASEO_HOME`) as you would for the `paseo` CLI.

## Limits

1. It is a log view, not the agent's own TUI: no slash commands, no PTY features.
2. Permission requests: a banner lists the shown agent's pending requests (polled every 3 s). Ctrl+A or Ctrl+D opens a confirmation listing them; `y` answers each listed request by id with `paseo permit allow|deny`, so a request that arrives after you looked is never approved blind. While none are pending, Ctrl+A and Ctrl+D keep their prompt-editing meaning (line start, delete).
3. Log entries are coloured by the `[Tag]` prefix `paseo logs` prints; untagged continuation lines are plain.
4. `paseo send` text beginning with `-` gets one leading space so the CLI does not read it as a flag.

## Development

```sh
uv run --group dev pytest -q
```

The tests drive the app with a fake `paseo` executable (`tests/fake_paseo.py`, selected through `PASEO_BIN`), so they never touch a real daemon.

## License

MIT
