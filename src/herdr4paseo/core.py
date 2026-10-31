"""Pure helpers: build `paseo` argv lists, parse agent listings, style log lines.

Nothing here touches the terminal or starts a process, so it is all unit-testable.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text

BEHAVIORS = ("steer", "interrupt")
HISTORY_LIMIT = 200

_TAG = re.compile(r"^\[([^\]]+)\]")
_FOLLOW_BANNER = re.compile(r"^--- Following logs \(last (\d+) entries; Ctrl\+C to stop\) ---$")
_STYLES = {
    "user": "bold cyan",
    "thought": "italic dim",
    "error": "bold red",
}
_TOOL_STYLE = "yellow"


def paseo_bin() -> str:
    """The paseo executable; PASEO_BIN overrides it (tests use a fake)."""
    return os.environ.get("PASEO_BIN", "paseo")


@dataclass(frozen=True)
class Agent:
    id: str
    short_id: str
    name: str
    provider: str
    status: str
    cwd: str

    @property
    def label(self) -> str:
        where = f"  {self.cwd}" if self.cwd else ""
        return f"{self.short_id}  {self.status:<8} {self.name}  ({self.provider}){where}"


def parse_agents(raw: str) -> list[Agent]:
    """Parse `paseo ls --json`; tolerate missing keys, reject non-list output."""
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("expected a JSON array from `paseo ls --json`")
    agents = []
    for item in data:
        agent_id = str(item.get("id", ""))
        agents.append(
            Agent(
                id=agent_id,
                short_id=str(item.get("shortId") or agent_id[:7]),
                name=str(item.get("name", "")),
                provider=str(item.get("provider", "")),
                status=str(item.get("status", "?")),
                cwd=str(item.get("cwd", "")),
            )
        )
    return agents


def find_agent(agents: list[Agent], ident: str) -> Agent | None:
    """Match a full id, a short id, or an unambiguous id prefix."""
    exact = [a for a in agents if ident in (a.id, a.short_id)]
    if exact:
        return exact[0]
    prefixed = [a for a in agents if a.id.startswith(ident)]
    return prefixed[0] if len(prefixed) == 1 else None


def filter_agents(agents: list[Agent], query: str) -> list[Agent]:
    """Agents whose label contains every whitespace-separated word of `query` (case-insensitive)."""
    words = query.lower().split()
    return [a for a in agents if all(w in a.label.lower() for w in words)]


def should_alert(old_status: str | None, new_status: str, old_permits: int, new_permits: int) -> str | None:
    """Why to ring the bell, or None. Only transitions alert, never a steady state."""
    if new_permits > old_permits:
        return "permission requested"
    if old_status == "running" and new_status == "idle":
        return "agent idle"
    return None


def history_path() -> Path:
    """Prompt history file; HERDR4PASEO_HISTORY overrides it (tests)."""
    override = os.environ.get("HERDR4PASEO_HISTORY")
    if override:
        return Path(override)
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "herdr4paseo" / "history.json"


def load_history(path: Path, limit: int = HISTORY_LIMIT) -> list[str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, str)][-limit:]


def save_history(path: Path, history: list[str], limit: int = HISTORY_LIMIT) -> None:
    """Best effort: a history file that cannot be written must never break sending."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(history[-limit:]))
        tmp.replace(path)
    except OSError:
        pass


@dataclass(frozen=True)
class Permission:
    id: str
    agent_id: str
    name: str
    description: str

    @property
    def label(self) -> str:
        return f"{self.name}: {self.description}" if self.description not in ("", "-") else self.name


def parse_permissions(raw: str, agent_id: str) -> list[Permission]:
    """Parse `paseo permit ls --json` (every agent's pending requests); keep one agent's."""
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("expected a JSON array from `paseo permit ls --json`")
    return [
        Permission(
            id=str(item.get("id", "")),
            agent_id=str(item.get("agentId", "")),
            name=str(item.get("name", "?")),
            description=str(item.get("description", "")),
        )
        for item in data
        if item.get("agentId") == agent_id
    ]


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    argument_hint: str
    kind: str  # "command" or "skill"

    @property
    def label(self) -> str:
        hint = f" {self.argument_hint}" if self.argument_hint else ""
        return f"/{self.name}{hint}  {self.description}"


def parse_commands(items: list[object]) -> list[Command]:
    """Parse the `commands` array of a list_commands response; skip malformed entries."""
    commands = []
    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        commands.append(
            Command(
                name=str(item["name"]),
                description=str(item.get("description") or ""),
                argument_hint=str(item.get("argumentHint") or ""),
                kind=str(item.get("kind") or "command"),
            )
        )
    return sorted(commands, key=lambda c: c.name.lower())


def match_commands(commands: list[Command], text: str, limit: int = 8) -> list[Command]:
    """Commands to suggest for a prompt of `/partial`: prefix matches first, then substrings.

    Only a single-line prompt that starts with "/" and has no space yet is a command being typed.
    """
    if not text.startswith("/") or any(ch.isspace() for ch in text):
        return []
    needle = text[1:].lower()
    prefix = [c for c in commands if c.name.lower().startswith(needle)]
    inside = [c for c in commands if needle in c.name.lower() and c not in prefix]
    return (prefix + inside)[:limit]


def permit_ls_argv() -> list[str]:
    return [paseo_bin(), "permit", "ls", "--json"]


def permit_argv(decision: str, agent_id: str, request_id: str) -> list[str]:
    """Answer exactly one request. Never `allow <agent>` alone: that approves everything
    pending, including requests that arrived after the user looked."""
    if decision not in ("allow", "deny"):
        raise ValueError(f"decision must be allow or deny, got {decision!r}")
    return [paseo_bin(), "permit", decision, agent_id, request_id]


def run_argv(prompt: str, provider: str) -> list[str]:
    """Start an agent without waiting; --quiet makes paseo print just the new agent's id.

    `paseo run` errors with "Provider is required" without --provider (seen live 2026-10-30).

    The working directory comes from where the process runs, not a flag.
    """
    if prompt.startswith("-"):
        prompt = " " + prompt  # same flag-lookalike guard as send_argv
    return [paseo_bin(), "run", "--no-wait", "--quiet", "--provider", provider, prompt]


def stop_argv(agent_id: str) -> list[str]:
    return [paseo_bin(), "stop", agent_id]


def ls_argv() -> list[str]:
    # -g: all workspaces; -a: archived too, so an agent you attached to stays findable.
    return [paseo_bin(), "ls", "-g", "-a", "--json"]


def logs_argv(agent: str, *, tail: int, tools_only: bool) -> list[str]:
    argv = [paseo_bin(), "logs", agent, "--no-color", "--tail", str(tail), "-f"]
    if tools_only:
        argv += ["--filter", "tools"]
    return argv


def send_argv(agent: str, text: str, behavior: str) -> list[str]:
    if behavior not in BEHAVIORS:
        raise ValueError(f"behavior must be one of {BEHAVIORS}, got {behavior!r}")
    # A prompt that starts with "-" would be parsed as a flag; a leading space is
    # harmless to the agent and keeps the argv free of a "--" the CLI may not accept.
    if text.startswith("-"):
        text = " " + text
    return [paseo_bin(), "send", agent, "--no-wait", "--behavior", behavior, text]


def style_line(line: str) -> Text:
    """Colour the `[Tag]` prefix `paseo logs` puts on each entry; leave the rest alone.

    The "--- Following logs (...; Ctrl+C to stop) ---" banner `paseo logs -f` prints is
    dimmed and reworded: Ctrl+C is not how you stop anything inside this TUI.
    """
    banner = _FOLLOW_BANNER.match(line)
    if banner:
        return Text(f"--- following live (last {banner.group(1)} entries) ---", style="dim")
    match = _TAG.match(line)
    if not match:
        return Text(line)
    style = _STYLES.get(match.group(1).lower(), _TOOL_STYLE)
    text = Text(line)
    text.stylize(style, 0, match.end())
    return text
