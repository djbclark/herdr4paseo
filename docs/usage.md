# Using herdr4paseo

This page walks through the jobs the tool is for. For the key table and options see the [README](../README.md).

## 1. Watch an agent from a Herdr pane

1. Start or find an agent in Paseo. `paseo ls -g -a` lists every agent, archived ones included, with its short id.
2. In a Herdr pane, run `herdr4paseo 7dba08f` (your id). The last 50 log entries appear, then new entries stream in live.
3. The header shows the agent's status. It refreshes every 3 seconds.
4. Quit with Ctrl+Q, or type `/quit` or `/exit` and press Enter (these are handled by herdr4paseo and never sent to the agent). You return to the shell you launched it from, and the agent is not touched. Run the command again, or press Ctrl+L inside it, to reattach.

Use `--tail 300` to see more history on attach. Press Ctrl+O to show only tool calls, which makes a long run easier to skim; press it again to return to the full log.

## 2. Steer or interrupt a running agent

Type a message and press Enter. What happens depends on the send behaviour shown in the header:

| Behaviour | Effect on a running turn |
| --- | --- |
| `steer` (default here) | Steers the running turn. Paseo's CLI docs: if steering is unavailable, the running turn is interrupted and replaced. (Plain `paseo send` defaults to interrupt; this tool defaults to steer.) |
| `interrupt` | The current turn is stopped and your text is what the agent does instead (Paseo: "stop and do this instead"). |

Ctrl+T switches between them. Start in `interrupt` with `--behavior interrupt`. If the send fails, your text stays in the box and the error is printed in the log, so nothing you typed is lost.

Use Ctrl+J or Shift+Enter for a multi-line prompt. Ctrl+P and Ctrl+N recall earlier prompts. History is saved (last 200) in `~/.local/state/herdr4paseo/history.json`, shared by all agents; `HERDR4PASEO_HISTORY` overrides the path.

## 3. Answer permission requests

When the agent asks for permission, a yellow banner appears above the prompt listing the pending requests for the agent you are viewing.

1. Press Ctrl+A to allow or Ctrl+D to deny.
2. A confirmation lists exactly the requests that will be answered. Press `y` to confirm or `n` or Escape to cancel.
3. Each listed request is answered by its own id. A request that arrives after you opened the confirmation is not answered; it shows up in the banner and you decide again.

While nothing is pending, Ctrl+A and Ctrl+D behave as normal text editing keys in the prompt (start of line, delete).

## 4. Use slash commands

Type `/` at the start of the prompt. A panel lists the commands and skills the agent offers, filtered as you type.

1. Tab completes the highlighted entry and adds a space so you can type arguments.
2. Up and Down move the highlight.
3. Enter sends exactly what is in the box, so a partial `/con` goes through as `/con`.

For a Claude agent this includes built-in commands such as `/compact` and `/context` and your installed skills, for example `/steps`. The Paseo app's own client commands, such as `/exit`, are not available through this tool.

If the command list cannot be loaded, the log shows `slash completion unavailable (...)` once. You can still type any command and send it.

## 5. Switch agents

Press Ctrl+L (Ctrl+G is macOS's Gemini shortcut, so it is not used), type to filter (every word must match the id, status, name, provider or directory), pick with the arrow keys and Enter (Escape cancels). Each row shows the agent's directory. The log and slash commands switch to the new agent. The previous agent keeps running.

## 6. Use a different daemon

Set `PASEO_HOST` or `PASEO_HOME` the way you would for the `paseo` CLI:

```sh
PASEO_HOST=studio.example:6767 herdr4paseo
```

Slash suggestions connect to the same daemon. The local credential file is only used for a daemon on this machine, so a remote daemon that requires a password will not offer suggestions, but everything else works.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `paseo ls failed (rc=...)` in the log | The `paseo` CLI could not reach the daemon. Check `paseo ls` works in the same shell and that `PASEO_HOST` and `PASEO_HOME` match. |
| `no agent selected; Ctrl+L to pick one` | The id you gave matched nothing or matched more than one agent. Use a longer prefix or pick from the list. |
| `log stream ended (rc=...); reconnecting in 3s` | `paseo logs -f` exited, for example the daemon restarted. It reattaches by itself every 3 s, clearing the view and re-reading the last `--tail` entries. |
| `send failed (rc=...)` | The `paseo send` error is printed after it. Your text is still in the box. |
| `slash completion unavailable (...)` | The WebSocket lookup failed; the reason is in the brackets. Typed commands still send. |
| Ctrl+A or Ctrl+D does nothing special | They only act on permissions while a request is pending. |
| A key does nothing inside Herdr | The multiplexer may capture it before the app sees it. Check Herdr's own key settings. |

If the `paseo` executable is not on `PATH`, set `PASEO_BIN` to its full path.

## Colours

The log is coloured by meaning, on your terminal's own background, which herdr4paseo never repaints (the way herdr leaves its sidebar background alone). The text colours are the dark shades of herdr's built-in `kanagawa` palette, not the terminal's ANSI colours, which many palettes render as a bright orange and red. The widgets (permits banner, dialogs, borders) use the same shades.

| What | Style |
| --- | --- |
| `[User]` tag and its text, including continuation lines | bold blue tag, blue text |
| `[Thought]` lines | italic grey |
| Tool calls (`[Shell]`, `[Read]`, MCP tool names, ...) | bold dull-gold tag, off-white summary, with paths and URLs underlined |
| `[Error]` | bold deep-red tag, deep-red text |
| `[Tasks]` list | `- [x]` items green, `- [ ]` items plain |
| `[Compacted]`, `[Reconnected; ...]`, `[Timeline replaced; ...]`, the follow banner, reconnect notes | grey |
| Assistant text (no tag) | terminal default, with markdown headings (bold teal), list markers and inline code (muted purple), quotes (italic grey) and `[text](url)` links (underlined blue) |
| Fenced code in assistant text | `diff` and `patch` fences: green `+`, red `-`, bold blue `@@`, grey context; other fences are highlighted with Pygments' Nord style by the fence's language (Pygments has no Kanagawa), keeping your terminal's own foreground and background |
| herdr4paseo's own notes | deep red for failures, green for started and permit answered, purple for stopped, grey for information, bold dull gold for `alert:` |
| Agent status (header and picker) | running yellow, idle green, error red, closed or archived grey (the same mapping as herdr) |

Limits: `paseo logs` prints no tag for assistant text, so a multi-line `[User]` prompt followed directly by assistant text shows that text in the user colour until the next tag. It also prints no tool output or diffs, so only diffs the assistant writes in a fenced block are coloured. Colouring is per line, so a multi-line string inside a code fence may be highlighted imperfectly. Lines already shown keep their colours when the terminal theme changes; Ctrl+O twice re-reads the log.

`NO_COLOR` turns colour off but keeps bold and italic, so tags, `+`/`-` diff lines and the thought/assistant difference stay readable. Textual treats an empty `NO_COLOR=` as set as well (the [spec](https://no-color.org) says only a non-empty value counts), so `unset NO_COLOR` rather than blanking it.

`TEXTUAL_COLOR_SYSTEM` forces the depth: `standard` (16 colours), `256` or `truecolor`; the default is `auto`. The palette is hex: Rich downgrades it to the nearest 256 or 16 colours on a terminal that cannot show it, which is brighter at 16.

herdr4paseo always runs `paseo logs --no-color` and does the colouring itself, so paseo's own colour setting does not matter.

## Stopping an agent and alerts

Ctrl+X asks for confirmation (y or n), then runs `paseo stop <id>` for the shown agent. Unlike quitting, this ends the agent's work.

The terminal bell rings, and a yellow `alert:` line is logged, when the shown agent goes from running to idle or a new permission request appears. Only changes alert, not a steady state. Whether a bell becomes a Herdr notification depends on your terminal and Herdr settings.

## Starting a new agent

Ctrl+R opens a small form: a prompt (required), a directory (starts as the directory herdr4paseo runs in) and a provider, prefilled with the current agent's (`paseo run` refuses to start without one; `provider/model` also works, and `paseo provider ls` lists them). Enter runs `paseo run --no-wait --quiet --provider P <prompt>` in that directory, then attaches to the new agent by the id Paseo prints. A bare `paseo run` creates a local workspace for the directory; worktrees, models and output schemas are not offered here, use the `paseo` CLI for those.
