"""Pure helpers: build `paseo` argv lists, parse agent listings, style log lines.

Nothing here touches the terminal or starts a process, so it is all unit-testable.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from rich.text import Text

BEHAVIORS = ("steer", "interrupt")

_TAG = re.compile(r"^\[([^\]]+)\]")
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
        return f"{self.short_id}  {self.status:<8} {self.name}  ({self.provider})"


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


def permit_ls_argv() -> list[str]:
    return [paseo_bin(), "permit", "ls", "--json"]


def permit_argv(decision: str, agent_id: str, request_id: str) -> list[str]:
    """Answer exactly one request. Never `allow <agent>` alone: that approves everything
    pending, including requests that arrived after the user looked."""
    if decision not in ("allow", "deny"):
        raise ValueError(f"decision must be allow or deny, got {decision!r}")
    return [paseo_bin(), "permit", decision, agent_id, request_id]


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
    """Colour the `[Tag]` prefix `paseo logs` puts on each entry; leave the rest alone."""
    match = _TAG.match(line)
    if not match:
        return Text(line)
    style = _STYLES.get(match.group(1).lower(), _TOOL_STYLE)
    text = Text(line)
    text.stylize(style, 0, match.end())
    return text
