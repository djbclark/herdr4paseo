"""herdr4paseo: a log view plus prompt box for one Paseo agent, built on the `paseo` CLI.

It owns nothing. The agent keeps running in the Paseo daemon, so quitting never
interrupts it, and the Paseo app can be attached to the same agent at the same time.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option

from rich.text import Text

from .core import (
    BEHAVIORS,
    Agent,
    Permission,
    find_agent,
    logs_argv,
    ls_argv,
    parse_agents,
    parse_permissions,
    permit_argv,
    permit_ls_argv,
    send_argv,
    style_line,
)

STATUS_POLL_SECONDS = 3.0


class PromptArea(TextArea):
    """Enter sends; Ctrl+J or Shift+Enter inserts a newline."""

    class Submitted(Message):
        pass

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
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
    BINDINGS = [Binding("escape", "dismiss_none", "Cancel")]

    def __init__(self, agents: list[Agent]) -> None:
        super().__init__()
        self._agents = agents

    def compose(self) -> ComposeResult:
        yield OptionList(*[Option(a.label, id=a.id) for a in self._agents])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id or "")

    def action_dismiss_none(self) -> None:
        self.dismiss("")


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
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


class Herdr4PaseoApp(App[None]):
    CSS = """
    #log { height: 1fr; }
    #prompt { height: 6; border: round $primary; }
    #permits { height: auto; background: $warning; color: $text; padding: 0 1; }
    #permits.hidden { display: none; }
    PickAgent, ConfirmPermits { align: center middle; }
    #confirm-box { width: 80%; height: auto; border: round $warning; padding: 1 2; background: $surface; }
    PickAgent OptionList { width: 90%; height: 70%; border: round $primary; }
    """
    ENABLE_COMMAND_PALETTE = False  # Ctrl+P is prompt history here
    BINDINGS = [
        Binding("ctrl+t", "toggle_behavior", "steer/interrupt"),
        Binding("ctrl+o", "toggle_tools", "tools only"),
        Binding("ctrl+g", "switch_agent", "agents"),
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
        self._history: list[str] = []
        self._history_pos = 0
        self.permits: list[Permission] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield RichLog(id="log", wrap=True, markup=False, highlight=False, auto_scroll=True)
            yield Static("", id="permits", classes="hidden", markup=False)
            yield PromptArea(id="prompt")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#prompt", PromptArea).focus()
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
        self.title = f"{picked.name} ({picked.short_id})"
        self._update_subtitle(picked.status)
        self._start_stream()
        await self._refresh_permits()

    async def _refresh_status(self) -> None:
        if self.agent is None:
            return
        current = find_agent(await self._list_agents(), self.agent.id)
        if current is not None:
            self._update_subtitle(current.status)
        await self._refresh_permits()

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
        if self.agent is None:
            return
        log = self.query_one("#log", RichLog)
        log.clear()
        proc = await asyncio.create_subprocess_exec(
            *logs_argv(self.agent.id, tail=self._tail, tools_only=self.tools_only),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            assert proc.stdout is not None
            while line := await proc.stdout.readline():
                log.write(style_line(line.decode(errors="replace").rstrip("\n")))
            self._note(f"log stream ended (rc={await proc.wait()}); Ctrl+G to reattach", "dim")
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                await proc.wait()

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
