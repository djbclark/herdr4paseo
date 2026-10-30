# Using herdr4paseo

This page walks through the jobs the tool is for. For the key table and options see the [README](../README.md).

## 1. Watch an agent from a Herdr pane

1. Start or find an agent in Paseo. `paseo ls -g -a` lists every agent, archived ones included, with its short id.
2. In a Herdr pane, run `herdr4paseo 7dba08f` (your id). The last 50 log entries appear, then new entries stream in live.
3. The header shows the agent's status. It refreshes every 3 seconds.
4. Quit with Ctrl+Q. The agent is not touched. Run the command again, or press Ctrl+G inside it, to reattach.

Use `--tail 300` to see more history on attach. Press Ctrl+O to show only tool calls, which makes a long run easier to skim; press it again to return to the full log.

## 2. Steer or interrupt a running agent

Type a message and press Enter. What happens depends on the send behaviour shown in the header:

| Behaviour | Effect on a running turn |
| --- | --- |
| `steer` (default) | The text is queued for the agent as guidance. The current turn is not cut short. |
| `interrupt` | The current turn is stopped and your text becomes the next instruction. |

Ctrl+T switches between them. Start in `interrupt` with `--behavior interrupt`. If the send fails, your text stays in the box and the error is printed in the log, so nothing you typed is lost.

Use Ctrl+J or Shift+Enter for a multi-line prompt. Ctrl+P and Ctrl+N recall earlier prompts from this session.

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

Press Ctrl+G, pick an agent with the arrow keys and Enter (Escape cancels). The log and slash commands switch to the new agent. The previous agent keeps running.

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
| `no agent selected; Ctrl+G to pick one` | The id you gave matched nothing or matched more than one agent. Use a longer prefix or pick from the list. |
| `log stream ended (rc=...); Ctrl+G to reattach` | `paseo logs -f` exited, for example the daemon restarted. Press Ctrl+G and choose the agent again. |
| `send failed (rc=...)` | The `paseo send` error is printed after it. Your text is still in the box. |
| `slash completion unavailable (...)` | The WebSocket lookup failed; the reason is in the brackets. Typed commands still send. |
| Ctrl+A or Ctrl+D does nothing special | They only act on permissions while a request is pending. |
| A key does nothing inside Herdr | The multiplexer may capture it before the app sees it. Check Herdr's own key settings. |

If the `paseo` executable is not on `PATH`, set `PASEO_BIN` to its full path.
