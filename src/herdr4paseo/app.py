"""herdr4paseo: a log view plus prompt box for one Paseo agent, built on the `paseo` CLI.

It owns nothing. The agent keeps running in the Paseo daemon, so quitting never
interrupts it, and the Paseo app can be attached to the same agent at the same time.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from collections.abc import Callable

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option

from rich.text import Text

from .core import (
    BEHAVIORS,
    Agent,
    Command,
    Permission,
    filter_agents,
    find_agent,
    history_path,
    load_history,
    logs_argv,
    ls_argv,
    match_commands,
    parse_agents,
    parse_permissions,
    permit_argv,
    permit_ls_argv,
    save_history,
    send_argv,
    should_alert,
    stop_argv,
    style_line,
)
from .daemon import DaemonError, fetch_commands

STATUS_POLL_SECONDS = 3.0
RECONNECT_SECONDS = 3.0


class PromptArea(TextArea):
    """Enter sends; Ctrl+J or Shift+Enter inserts a newline."""

    class Submitted(Message):
        pass

    # Set by the app: takes Tab/Up/Down, returns True when a slash suggestion consumed the key.
    slash_handler: Callable[[str], bool] | None = None

    async def _on_key(self, event: events.Key) -> None:
        if event.key in ("tab", "up", "down") and self.slash_handler and self.slash_handler(event.key):
            event.prevent_default()
            event.stop()
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted())
        elif event.key in ("ctrl+j", "shift+enter"):
            event.prevent_default()
            event.stop()
            self.insert("\n")
        else:
            await super()._on_key(event)


class PickAgent(ModalScreen[str]):
    """Type to filter (every word must match id, status, name, provider or directory); Enter picks."""

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel")]

    def __init__(self, agents: list[Agent]) -> None:
        super().__init__()
        self._agents = agents

    def compose(self) -> ComposeResult:
        with Vertical(id="pick-box"):
            yield Input(placeholder="filter agents", id="pick-filter")
            yield OptionList(*[Option(a.label, id=a.id) for a in self._agents], id="pick-list")

    def on_input_changed(self, event: Input.Changed) -> None:
        shown = filter_agents(self._agents, event.value)
        options = self.query_one("#pick-list", OptionList)
        options.clear_options()
        options.add_options([Option(a.label, id=a.id) for a in shown])
        if shown:
            options.highlighted = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        options = self.query_one("#pick-list", OptionList)
        if options.highlighted is not None and options.option_count:
            self.dismiss(options.get_option_at_index(options.highlighted).id or "")

    def on_key(self, event: events.Key) -> None:
        if event.key in ("up", "down"):
            options = self.query_one("#pick-list", OptionList)
            event.stop()
            event.prevent_default()
            (options.action_cursor_up if event.key == "up" else options.action_cursor_down)()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id or "")

    def action_dismiss_none(self) -> None:
        self.dismiss("")


class ConfirmStop(ModalScreen[bool]):
    """y stops the agent; n or Escape cancels."""

    BINDINGS = [
        Binding("y", "confirm(True)", "Yes"),
        Binding("n,escape", "confirm(False)", "No"),
    ]

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self._agent = agent

    def compose(self) -> ComposeResult:
        yield Static(
            f"STOP agent {self._agent.name} ({self._agent.short_id}, {self._agent.status})?\n\n[y] yes   [n] no",
            id="confirm-box",
            markup=False,
        )

    def action_confirm(self, answer: bool) -> None:
        self.dismiss(answer)


class ConfirmPermits(ModalScreen[bool]):
    """Lists exactly the requests that will be answered; y confirms, n or Escape cancels."""

    BINDINGS = [
        Binding("y", "confirm(True)", "Yes"),
        Binding("n,escape", "confirm(False)", "No"),
    ]

    def __init__(self, decision: str, permits: list[Permission]) -> None:
        super().__init__()
        self._decision = decision
        self._permits = permits

    def compose(self) -> ComposeResult:
        lines = "\n".join(f"  - {p.label}" for p in self._permits)
        yield Static(
            f"{self._decision.upper()} {len(self._permits)} pending request(s)?\n\n{lines}\n\n[y] yes   [n] no",
            id="confirm-box",
            markup=False,
        )

    def action_confirm(self, answer: bool) -> None:
        self.dismiss(answer)


async def run_paseo(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:  # missing or non-executable paseo: report it like any failed call
        return 127, "", f"cannot run {argv[0]}: {exc.strerror or exc} (set PASEO_BIN to its full path)"
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


class Herdr4PaseoApp(App[None]):
    CSS = """
    #log { height: 1fr; }
    #prompt { height: 6; border: round $primary; }
    #permits { height: auto; background: $warning; color: $text; padding: 0 1; }
    #permits.hidden { display: none; }
    #slash { height: auto; max-height: 9; padding: 0 1; background: $panel; }
    #slash.hidden { display: none; }
    PickAgent, ConfirmPermits, ConfirmStop { align: center middle; }
    #confirm-box { width: 80%; height: auto; border: round $warning; padding: 1 2; background: $surface; }
    #pick-box { width: 90%; height: 70%; border: round $primary; }
    #pick-list { height: 1fr; }
    """
    ENABLE_COMMAND_PALETTE = False  # Ctrl+P is prompt history here
    BINDINGS = [
        Binding("ctrl+t", "toggle_behavior", "steer/interrupt"),
        Binding("ctrl+o", "toggle_tools", "tools only"),
        Binding("ctrl+g", "switch_agent", "agents"),
        # Priority beats the prompt's own Ctrl+X (cut); a confirmation guards the stop.
        Binding("ctrl+x", "stop_agent", "stop agent", priority=True),
        # Priority beats the prompt's own Ctrl+A/Ctrl+D, but check_action only enables
        # these while a request is pending, so the prompt keeps its keys otherwise.
        Binding("ctrl+a", "answer_permits('allow')", "allow", priority=True),
        Binding("ctrl+d", "answer_permits('deny')", "deny", priority=True),
        Binding("ctrl+p", "history_prev", "prev", show=False),
        Binding("ctrl+n", "history_next", "next", show=False),
    ]

    def __init__(self, agent_ident: str | None, *, tail: int, behavior: str) -> None:
        super().__init__()
        self._ident = agent_ident
        self._tail = tail
        self.behavior = behavior
        self.tools_only = False
        self.agent: Agent | None = None
        self._history: list[str] = load_history(history_path())
        self._last_status: str | None = None
        self._history_pos = len(self._history)
        self.permits: list[Permission] = []
        self.commands: list[Command] = []
        self.slash_matches: list[Command] = []
        self._slash_idx = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield RichLog(id="log", wrap=True, markup=False, highlight=False, auto_scroll=True)
            yield Static("", id="permits", classes="hidden", markup=False)
            yield Static("", id="slash", classes="hidden", markup=False)
            yield PromptArea(id="prompt")
        yield Footer()

    async def on_mount(self) -> None:
        prompt = self.query_one("#prompt", PromptArea)
        prompt.slash_handler = self.handle_slash_key
        prompt.focus()
        self.set_interval(STATUS_POLL_SECONDS, self._refresh_status)
        self._choose_agent(self._ident)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "answer_permits":
            return bool(self.permits)
        return True

    # -- agent selection and status -------------------------------------------------

    async def _list_agents(self) -> list[Agent]:
        code, out, err = await run_paseo(ls_argv())
        if code != 0:
            self._note(f"paseo ls failed (rc={code}): {err.strip()}", "bold red")
            return []
        try:
            return parse_agents(out)
        except ValueError as exc:
            self._note(f"could not read agent list: {exc}", "bold red")
            return []

    @work(exclusive=True, group="choose")  # push_screen_wait only runs inside a worker
    async def _choose_agent(self, ident: str | None) -> None:
        agents = await self._list_agents()
        picked = find_agent(agents, ident) if ident else None
        if picked is None and agents:
            choice = await self.push_screen_wait(PickAgent(agents))
            picked = find_agent(agents, choice) if choice else None
        if picked is None:
            self._note("no agent selected; Ctrl+G to pick one", "bold red")
            return
        self.agent = picked
        self._last_status = picked.status
        self.title = f"{picked.name} ({picked.short_id})"
        self._update_subtitle(picked.status)
        self._start_stream()
        self._load_commands(picked.id)
        await self._refresh_permits()

    async def _refresh_status(self) -> None:
        if self.agent is None:
            return
        before = len(self.permits)
        current = find_agent(await self._list_agents(), self.agent.id)
        if current is not None:
            self._update_subtitle(current.status)
        await self._refresh_permits()
        if current is not None:
            reason = should_alert(self._last_status, current.status, before, len(self.permits))
            self._last_status = current.status
            if reason:
                self.bell()
                self._note(f"alert: {reason}", "bold yellow")

    async def _refresh_permits(self) -> None:
        """Poll pending permission requests for the shown agent and update the banner."""
        if self.agent is None:
            return
        code, out, _err = await run_paseo(permit_ls_argv())
        if code != 0:
            return  # keep the last banner; a transient failure must not hide a pending request
        try:
            self.permits = parse_permissions(out, self.agent.id)
        except ValueError:
            return
        self.refresh_bindings()
        banner = self.query_one("#permits", Static)
        if self.permits:
            names = "; ".join(p.label for p in self.permits)
            banner.update(f"{len(self.permits)} pending: {names}  (Ctrl+A allow, Ctrl+D deny)")
            banner.remove_class("hidden")
        else:
            banner.add_class("hidden")

    def _update_subtitle(self, status: str) -> None:
        view = "tools only" if self.tools_only else "full log"
        self.sub_title = f"{status} | send: {self.behavior} | {view}"

    # -- log stream -----------------------------------------------------------------

    def _note(self, message: str, style: str) -> None:
        self.query_one("#log", RichLog).write(Text(message, style=style))

    @work(exclusive=True, group="stream")
    async def _start_stream(self) -> None:
        """Follow the log; when the stream ends on its own, reattach after a pause until replaced."""
        if self.agent is None:
            return
        log = self.query_one("#log", RichLog)
        agent_id, tools_only = self.agent.id, self.tools_only
        while True:
            log.clear()
            proc = await asyncio.create_subprocess_exec(
                *logs_argv(agent_id, tail=self._tail, tools_only=tools_only),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                assert proc.stdout is not None
                while line := await proc.stdout.readline():
                    log.write(style_line(line.decode(errors="replace").rstrip("\n")))
                rc = await proc.wait()
            finally:
                if proc.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        proc.terminate()
                    await proc.wait()
            self._note(f"log stream ended (rc={rc}); reconnecting in {RECONNECT_SECONDS:g}s", "dim")
            await asyncio.sleep(RECONNECT_SECONDS)

    # -- slash commands -------------------------------------------------------------

    @work(exclusive=True, group="commands")
    async def _load_commands(self, agent_id: str) -> None:
        """Fetch the agent's slash commands from the daemon; completion is optional, so failure only notes."""
        self.commands = []
        try:
            self.commands = await fetch_commands(agent_id)
        except DaemonError as exc:
            self._note(f"slash completion unavailable ({exc}); typed /commands still work", "dim")
        self._update_slash()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._update_slash()

    def _update_slash(self) -> None:
        text = self.query_one("#prompt", PromptArea).text
        self.slash_matches = match_commands(self.commands, text)
        self._slash_idx = min(self._slash_idx, max(0, len(self.slash_matches) - 1))
        self._render_slash()

    def _render_slash(self) -> None:
        panel = self.query_one("#slash", Static)
        if not self.slash_matches:
            panel.add_class("hidden")
            return
        lines = [
            f"{'>' if i == self._slash_idx else ' '} {c.label}"[:100] for i, c in enumerate(self.slash_matches)
        ]
        panel.update("\n".join(lines + ["  Tab complete, Up/Down choose, Enter sends as typed"]))
        panel.remove_class("hidden")

    def handle_slash_key(self, key: str) -> bool:
        """Tab/Up/Down while suggestions show; True means the key was used."""
        if not self.slash_matches:
            return False
        if key == "tab":
            prompt = self.query_one("#prompt", PromptArea)
            prompt.text = f"/{self.slash_matches[self._slash_idx].name} "
            prompt.move_cursor(prompt.document.end)
            self._slash_idx = 0
            return True
        step = -1 if key == "up" else 1
        self._slash_idx = (self._slash_idx + step) % len(self.slash_matches)
        self._render_slash()
        return True

    # -- sending --------------------------------------------------------------------

    async def on_prompt_area_submitted(self, message: PromptArea.Submitted) -> None:
        message.stop()
        if self.agent is None:
            self._note("no agent selected; Ctrl+G to pick one", "bold red")
            return
        prompt = self.query_one("#prompt", PromptArea)
        text = prompt.text.strip()
        if not text:
            return
        code, _out, err = await run_paseo(send_argv(self.agent.id, text, self.behavior))
        if code != 0:
            self._note(f"send failed (rc={code}): {err.strip()}", "bold red")
            return  # keep the text so nothing typed is lost
        self._history.append(text)
        self._history_pos = len(self._history)
        save_history(history_path(), self._history)
        prompt.clear()

    # -- actions --------------------------------------------------------------------

    def action_toggle_behavior(self) -> None:
        self.behavior = BEHAVIORS[(BEHAVIORS.index(self.behavior) + 1) % len(BEHAVIORS)]
        self._update_subtitle(self.sub_title.split(" | ")[0])

    def action_toggle_tools(self) -> None:
        self.tools_only = not self.tools_only
        self._update_subtitle(self.sub_title.split(" | ")[0])
        self._start_stream()

    def action_switch_agent(self) -> None:
        self._choose_agent(None)

    @work(exclusive=True, group="permit")  # push_screen_wait only runs inside a worker
    async def action_answer_permits(self, decision: str) -> None:
        if self.agent is None:
            return
        await self._refresh_permits()
        shown = list(self.permits)  # answer exactly what the confirmation lists
        if not shown:
            self._note("no pending permission requests", "dim")
            return
        if not await self.push_screen_wait(ConfirmPermits(decision, shown)):
            return
        for permit in shown:
            code, _out, err = await run_paseo(permit_argv(decision, self.agent.id, permit.id))
            result = "ok" if code == 0 else f"failed (rc={code}): {err.strip()}"
            self._note(f"permit {decision} {permit.label}: {result}", "dim" if code == 0 else "bold red")
        await self._refresh_permits()

    @work(exclusive=True, group="stop")  # push_screen_wait only runs inside a worker
    async def action_stop_agent(self) -> None:
        if self.agent is None:
            return
        if not await self.push_screen_wait(ConfirmStop(self.agent)):
            return
        code, _out, err = await run_paseo(stop_argv(self.agent.id))
        if code == 0:
            self._note(f"stopped {self.agent.name}", "dim")
        else:
            self._note(f"stop failed (rc={code}): {err.strip()}", "bold red")

    def action_history_prev(self) -> None:
        self._recall(-1)

    def action_history_next(self) -> None:
        self._recall(1)

    def _recall(self, step: int) -> None:
        if not self._history:
            return
        self._history_pos = max(0, min(len(self._history), self._history_pos + step))
        prompt = self.query_one("#prompt", PromptArea)
        prompt.text = self._history[self._history_pos] if self._history_pos < len(self._history) else ""


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="herdr4paseo",
        description="Log view and prompt box for one Paseo agent, via the paseo CLI.",
    )
    parser.add_argument("agent", nargs="?", help="agent id, short id or prefix; omit to pick from a list")
    parser.add_argument("--tail", type=int, default=50, help="log entries to show on attach (default 50)")
    parser.add_argument(
        "--behavior",
        choices=BEHAVIORS,
        default="steer",
        help="how sends treat a running turn (default steer; Ctrl+T toggles)",
    )
    args = parser.parse_args()
    Herdr4PaseoApp(args.agent, tail=args.tail, behavior=args.behavior).run()


if __name__ == "__main__":
    main()
