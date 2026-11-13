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

# A tag is `[Name]` at the start of a line followed by whitespace or the end of the line, so a
# markdown link such as `[docs](https://x)` is not mistaken for one.
_TAG = re.compile(r"^\[([^\]\n]+)\](?=\s|$)")
_FOLLOW_BANNER = re.compile(r"^--- Following logs \(last (\d+) entries; Ctrl\+C to stop\) ---$")

# Semantic style tokens. The vocabulary (user message, thinking text, tool title/output,
# diff added/removed/context, markdown, syntax) is adapted from pi's theme tokens
# (https://github.com/earendil-works/pi, MIT, (c) 2025 Mario Zechner,
# packages/coding-agent/src/modes/interactive/theme/theme-tokens.ts). The values are Rich style
# strings using the 16 ANSI colour names, so they follow the terminal's own palette and are exact
# on 16-colour terminals. Meaning must also survive NO_COLOR: tags stay in the text, diff lines
# keep their +/-, and the tag/thought tokens carry bold/italic/dim, which Textual's NO_COLOR
# filter keeps.
# The `status.*` tokens mirror herdr's agent-state colours (https://github.com/herdrdev/herdr,
# Apache-2.0, src/client/shell.rs `status_color`), so both tools agree visually.
THEME: dict[str, str] = {
    "user.tag": "bold cyan",
    "user.text": "cyan",
    "assistant.text": "",  # terminal default
    "thought": "italic dim",
    "tool.tag": "bold yellow",
    "tool.detail": "yellow",
    "tool.result": "dim",
    "tool.failed": "bold red",  # reserved for a structured stream; `paseo logs` prints no results
    "permission": "bold black on yellow",
    "error.tag": "bold red",
    "error.text": "red",
    "success": "green",
    "status": "magenta",
    "meta": "dim",
    "diff.add": "green",
    "diff.remove": "red",
    "diff.hunk": "bold cyan",
    "diff.context": "dim",
    "md.heading": "bold yellow",
    "md.code": "magenta",
    "md.fence": "dim",
    "md.bullet": "magenta",
    "md.quote": "italic dim",
    "md.link": "underline blue",
    "status.running": "yellow",
    "status.idle": "green",
    "status.error": "red",
    "status.closed": "dim",
}
# Pygments theme for lines inside a fenced code block (rich.syntax.ANSISyntaxTheme: ANSI names only).
CODE_THEME = "ansi_dark"

# Bracketed lines `paseo logs` prints that are not tool calls. `Reconnected; ...` and
# `Timeline replaced; ...` carry detail after a semicolon, so they match by prefix.
META_TAGS = frozenset({"compacted", "earlier chat history omitted"})
_META_PREFIXES = ("reconnected;", "timeline replaced;")

_STATUS_TOKENS = {
    "running": "status.running",
    "idle": "status.idle",
    "error": "status.error",
    "closed": "status.closed",
    "archived": "status.closed",
    "stopped": "status.closed",
}


def style_for(token: str) -> str:
    """The Rich style string for a token; an unknown token is a bug and raises KeyError."""
    return THEME[token]


def status_style(status: str) -> str:
    """Style for an agent status word (running yellow, idle green, error red, closed dim)."""
    token = _STATUS_TOKENS.get(status.lower())
    return style_for(token) if token else ""


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


_HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])(?=\s)")
_QUOTE = re.compile(r"^\s*>")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_LINK = re.compile(r"\[[^\]\n]+\]\([^)\s]+\)")
_FENCE = re.compile(r"^\s*```\s*([\w+#.-]*)")
_TASK = re.compile(r"^\s*- \[[ xX]\]")
_TASK_DONE = re.compile(r"^\s*- \[[xX]\]")
_PATH_OR_URL = re.compile(r"https?://[^\s)\]>\"']+|(?<![\w/.])(?:~|\.{1,2})?/[\w.@+\-/]+")
_DIFF_LANGS = frozenset({"diff", "patch", "udiff"})


def _style(text: Text, token: str, start: int = 0, end: int | None = None) -> None:
    style = style_for(token)
    if style:
        text.stylize(style, start, len(text) if end is None else end)


class LogStyler:
    """Colour `paseo logs` lines one at a time, remembering what the previous line was.

    `paseo logs` tags only user, thought and tool entries; assistant prose has no tag. So the
    state is the kind of the last tagged block (continuation lines of a `[User]` or `[Thought]`
    entry carry no tag) plus the language of the open code fence, if any. One styler per
    stream: make a new one whenever the log view is cleared.

    A multi-line `[User]` prompt followed directly by untagged assistant text cannot be told
    apart, so that text keeps the user colour until the next tag.
    """

    def __init__(self) -> None:
        self.block = "assistant"  # user, thought, tasks or assistant
        self.fence_lang: str | None = None  # None outside a fence; "" for a fence without a language
        self._syntax = None

    def style(self, line: str) -> Text:
        banner = _FOLLOW_BANNER.match(line)
        if banner:
            return Text(f"--- following live (last {banner.group(1)} entries) ---", style=style_for("meta"))
        tag = _TAG.match(line)
        if tag:
            return self._tagged(line, tag)
        return self._untagged(line)

    # -- tagged entries -------------------------------------------------------------

    def _tagged(self, line: str, tag: re.Match[str]) -> Text:
        name = tag.group(1).lower()
        text = Text(line)
        end = tag.end()
        self.fence_lang = None
        self._syntax = None
        if name in META_TAGS or name.startswith(_META_PREFIXES):
            self.block = "assistant"
            _style(text, "meta")
        elif name == "user":
            self.block = "user"
            _style(text, "user.tag", 0, end)
            _style(text, "user.text", end)
        elif name == "thought":
            self.block = "thought"
            _style(text, "thought")
        elif name == "error":
            self.block = "assistant"
            _style(text, "error.tag", 0, end)
            _style(text, "error.text", end)
        elif name == "tasks":
            self.block = "tasks"
            _style(text, "tool.tag", 0, end)
            _style(text, "tool.detail", end)
        else:  # a tool call: Shell, Read, Edit, an MCP tool name, ...
            self.block = "assistant"  # tool entries are one line
            _style(text, "tool.tag", 0, end)
            _style(text, "tool.detail", end)
            for found in _PATH_OR_URL.finditer(line, end):
                text.stylize("underline", found.start(), found.end())
        return text

    # -- continuation and assistant lines -------------------------------------------

    def _untagged(self, line: str) -> Text:
        text = Text(line)
        if self.block == "user":
            _style(text, "user.text")
            return text
        if self.block == "thought":
            _style(text, "thought")
            return text
        if self.block == "tasks":
            if _TASK.match(line):
                if _TASK_DONE.match(line):
                    _style(text, "success")
                return text
            self.block = "assistant"
        return self._assistant(line, text)

    def _assistant(self, line: str, text: Text) -> Text:
        fence = _FENCE.match(line)
        if fence:
            if self.fence_lang is None:
                self.fence_lang = fence.group(1).lower()
                self._syntax = None
            else:
                self.fence_lang = None
                self._syntax = None
            _style(text, "md.fence")
            return text
        if self.fence_lang is not None:
            return self._in_fence(line, text)
        _style(text, "assistant.text")
        if _HEADING.match(line):
            _style(text, "md.heading")
        elif _QUOTE.match(line):
            _style(text, "md.quote")
        else:
            bullet = _BULLET.match(line)
            if bullet:
                _style(text, "md.bullet", 0, bullet.end())
        text.highlight_regex(_INLINE_CODE, style_for("md.code"))
        text.highlight_regex(_LINK, style_for("md.link"))
        return text

    def _in_fence(self, line: str, text: Text) -> Text:
        lang = self.fence_lang or ""
        if lang in _DIFF_LANGS:
            if line.startswith("@@"):
                _style(text, "diff.hunk")
            elif line.startswith(("+++", "---")):
                _style(text, "diff.hunk")
            elif line.startswith("+"):
                _style(text, "diff.add")
            elif line.startswith("-"):
                _style(text, "diff.remove")
            else:
                _style(text, "diff.context")
            return text
        if lang:
            if self._syntax is None:
                from rich.syntax import Syntax

                self._syntax = Syntax("", lang, theme=CODE_THEME)
            for span in self._syntax.highlight(line).spans:
                if span.start < len(line):
                    text.stylize(span.style, span.start, min(span.end, len(line)))
        return text


def style_line(line: str) -> Text:
    """Style one log line with no memory of earlier lines (see LogStyler for the stateful form)."""
    return LogStyler().style(line)


def agent_label_text(agent: Agent) -> Text:
    """The picker row for an agent, with the status word coloured like the header."""
    text = Text(agent.label)
    start = len(agent.short_id) + 2
    style = status_style(agent.status)
    if style:
        text.stylize(style, start, start + len(agent.status))
    return text
