# How herdr4paseo works

herdr4paseo owns nothing. The agent, its history and its permissions live in the Paseo daemon; this tool is a client that runs `paseo` commands and renders their output.

## Commands it runs

| Purpose | Command | When |
| --- | --- | --- |
| Stop the agent (Ctrl+X, after confirmation) | `paseo stop <id>` | On request |
| List agents, for the picker and the status line | `paseo ls -g -a --json` | On start, on Ctrl+L, every 3 s |
| Stream the log | `paseo logs <id> --no-color --tail N -f` (plus `--filter tools` in tools-only view) | On attach; restarted by Ctrl+O |
| Send a prompt | `paseo send <id> --no-wait --behavior steer\|interrupt "<text>"` | On Enter |
| Find pending permission requests | `paseo permit ls --json` | Every 3 s; filtered to the shown agent |
| Answer one request | `paseo permit allow\|deny <agent> <request-id>` | After you confirm; one call per listed request |

It never runs `paseo permit allow <agent>` without a request id, because that form approves everything pending, including requests that arrived after you looked.

A prompt that starts with `-` gets one leading space so the CLI does not read it as a flag.

## The one WebSocket request

The `paseo` CLI has no command that lists an agent's slash commands, but the daemon has the request the Paseo app's `/` menu uses: `list_commands_request`. `src/herdr4paseo/daemon.py` makes exactly that request and nothing else.

1. Connect to the daemon's WebSocket. The address is `PASEO_HOST` if set, otherwise `daemon.listen` from `$PASEO_HOME/config.json`, otherwise `127.0.0.1:6767`. `$PASEO_HOME` defaults to `~/.paseo`.
2. Send a `hello` (client id `herdr4paseo`, client type `cli`, protocol version 1).
3. Send a `session` message wrapping `{type: "list_commands_request", agentId, requestId}`.
4. Read until the `list_commands_response` whose `requestId` matches. Responses for other requests are ignored. A `hello_rejected`, an error in the payload, a timeout (30 s) or a closed connection ends the lookup with a note in the log.

The response lists `name`, `description`, `argumentHint` and `kind` (`command` or `skill`) for each entry. The protocol is defined in the [getpaseo/paseo](https://github.com/getpaseo/paseo) repository (`packages/protocol`, and `listCommands` in `packages/client`). Recheck it if Paseo changes its protocol version.

## Styling

All colour decisions are in `core.py`.

1. `THEME` maps semantic tokens (`user.tag`, `thought`, `tool.tag`, `error.text`, `diff.add`, `md.heading`, `status.running`, ...) to Rich style strings. `style_for(token)` looks one up and raises `KeyError` for an unknown token, so a typo in a call site fails in tests instead of rendering unstyled. The colours are the dark shades of herdr's `kanagawa` palette (`KANAGAWA` in `core.py`) in hex, not the 16 ANSI names, which many terminal palettes render as bright orange and red. `app.py` registers its own Textual theme (`APP_THEME`): an ANSI theme, so the background and plain text are the terminal's own and are never repainted, with the accents (`$primary`, `$warning`, `$error`, `$success`) set to the same shades. Each token that must stay meaningful without colour carries bold or italic, which Textual's `NO_COLOR` filter keeps.
2. `LogStyler` styles one line at a time and keeps two pieces of state: the kind of the last tagged block (`user`, `thought`, `tasks` or `assistant`) and the language of the open code fence. A tagged line sets the block and clears the fence; an untagged line continues `user`, `thought` or `tasks`, and otherwise is assistant text, which gets a cheap markdown pass, diff colouring in `diff` fences and `rich.syntax.Syntax` (Pygments' `nord` style, with its background and default text colour dropped) in other fences. `app.py` makes a new `LogStyler` each time it clears the log. `style_line(line)` is the stateless one-line form.
3. A tag is `^[Name]` followed by whitespace or end of line, so `[text](url)` is not one. `[Compacted]`, `[Earlier chat history omitted]`, `[Reconnected; ...]` and `[Timeline replaced; ...]` are `meta`, not tool calls.
4. `_note(message, token)` in `app.py` takes a token, never a raw style. `status_style(status)` colours the header status (via `format_title`) and the picker rows.
5. Attribution: the token vocabulary is adapted from pi's theme tokens ([earendil-works/pi](https://github.com/earendil-works/pi), MIT, (c) 2025 Mario Zechner); the status colours follow herdr's `status_color` ([herdrdev/herdr](https://github.com/herdrdev/herdr), Apache-2.0). No code was copied from either, and none from projects under non-MIT-compatible licences.
6. Not built: a user theme file (a `HERDR4PASEO_THEME` override of `THEME`) and re-resolving tokens from Textual's theme variables when the theme changes.

## Security notes

1. The daemon's local credential is read from `$PASEO_HOME/local-credential`, the file the `paseo` CLI itself uses on this machine. It goes into the `hello` message only when the daemon address is loopback (`127.0.0.1`, `localhost` or `::1`). It is never sent to a remote host, printed or logged.
2. The WebSocket client is read-only. Sending prompts, stopping agents and answering permissions all still go through the `paseo` CLI.
3. Permission answers are always confirmed by the user and always name the request id shown in the confirmation.

## Code layout

| File | Role |
| --- | --- |
| `src/herdr4paseo/core.py` | Pure helpers: argv builders, parsing of agent, permission and command listings, command matching, the style token table (`THEME`) and `LogStyler`. No I/O. |
| `src/herdr4paseo/daemon.py` | The WebSocket client for `list_commands_request`. |
| `src/herdr4paseo/app.py` | The Textual UI: log, prompt, picker, permission banner and confirmation, slash panel, key bindings, `main()`. |
| `tests/fake_paseo.py` | A fake `paseo` executable that records its argv, selected with `PASEO_BIN`. |
| `tests/fake_daemon.py` | An in-process WebSocket server that answers `hello` and `list_commands_request`. |

Textual details worth knowing: `push_screen_wait` only works inside a worker, so the agent picker and permission confirmation run as `@work` workers in separate groups so they do not cancel each other or the log stream. Ctrl+A and Ctrl+D are priority bindings gated by `check_action`, so they only take over from the prompt's own keys while a request is pending. The command palette is disabled because Ctrl+P is prompt history.

## Testing

```sh
uv run --group dev pytest -q
```

The suite drives the real app through Textual's pilot against the fake executable and the fake daemon, so it never touches a real daemon or sends to a live agent. Tests set `PASEO_HOME` to a temporary directory and `PASEO_HOST` to a refused port so an accidental real connection is impossible.

Two things are only checked against the real daemon by hand: the exact output formats of `paseo logs` and `paseo ls --json` (read on 2026-10-28), and `paseo permit allow|deny` on a real pending request, which has not been exercised live yet.
