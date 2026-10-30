"""Read-only WebSocket client for the one daemon request the `paseo` CLI does not expose.

`list_commands_request` returns an agent's slash commands and skills (the Paseo app
fills its `/` menu from it). Everything else herdr4paseo does still goes through the
`paseo` CLI. This module only reads: it never sends prompts or answers permissions.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import websockets

from .core import Command, parse_commands

DEFAULT_LISTEN = "127.0.0.1:6767"
LOOPBACK = ("127.0.0.1", "localhost", "::1")


class DaemonError(Exception):
    """The daemon could not be reached or refused the request."""


def paseo_home() -> Path:
    return Path(os.environ.get("PASEO_HOME") or Path.home() / ".paseo")


def daemon_url() -> str:
    """ws:// URL of the daemon: PASEO_HOST, else the home's config.json listen address."""
    host = os.environ.get("PASEO_HOST")
    if not host:
        try:
            host = json.loads((paseo_home() / "config.json").read_text())["daemon"]["listen"]
        except (OSError, ValueError, KeyError, TypeError):
            host = DEFAULT_LISTEN
    if "://" not in host:
        host = f"ws://{host}"
    parts = urlsplit(host)
    scheme = {"http": "ws", "https": "wss"}.get(parts.scheme, parts.scheme)
    return f"{scheme}://{parts.netloc}{parts.path or '/ws'}"


def local_credential(url: str) -> str | None:
    """The daemon's local credential, only ever for a loopback daemon: never sent to a remote host."""
    if urlsplit(url).hostname not in LOOPBACK:
        return None
    try:
        return (paseo_home() / "local-credential").read_text().strip() or None
    except OSError:
        return None


async def fetch_commands(agent_id: str, *, timeout: float = 30.0) -> list[Command]:
    url = daemon_url()
    hello: dict[str, object] = {
        "type": "hello",
        "clientId": "herdr4paseo",
        "clientType": "cli",
        "protocolVersion": 1,
    }
    token = local_credential(url)
    if token:
        hello["auth"] = {"kind": "localCredential", "token": token}
    request_id = str(uuid.uuid4())
    request = {
        "type": "session",
        "message": {"type": "list_commands_request", "agentId": agent_id, "requestId": request_id},
    }
    try:
        async with asyncio.timeout(timeout), websockets.connect(url, open_timeout=timeout) as ws:
            await ws.send(json.dumps(hello))
            await ws.send(json.dumps(request))
            async for raw in ws:
                message = json.loads(raw)
                if message.get("type") == "hello_rejected":
                    raise DaemonError(f"daemon rejected the connection: {message.get('reason', 'unknown')}")
                inner = message.get("message") if message.get("type") == "session" else None
                if not isinstance(inner, dict) or inner.get("type") != "list_commands_response":
                    continue
                payload = inner.get("payload") or {}
                if payload.get("requestId") != request_id:
                    continue
                if payload.get("error"):
                    raise DaemonError(str(payload["error"]))
                return parse_commands(payload.get("commands") or [])
    except DaemonError:
        raise
    except (OSError, TimeoutError, ValueError, websockets.WebSocketException) as exc:
        raise DaemonError(f"{type(exc).__name__}: {exc}") from exc
    raise DaemonError("daemon closed the connection before answering")
