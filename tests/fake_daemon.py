"""A tiny in-process stand-in for the Paseo daemon's WebSocket: hello, then list_commands."""

from __future__ import annotations

import contextlib
import json

import websockets

COMMANDS = [
    {"name": "context", "description": "Show context usage", "argumentHint": "", "kind": "command"},
    {"name": "compact", "description": "Compact the conversation", "argumentHint": "[focus]", "kind": "command"},
    {"name": "steps", "description": "Walk through open items", "argumentHint": "", "kind": "skill"},
    {"name": "code-review", "description": "Review a diff", "argumentHint": "", "kind": "skill"},
    {"bogus": True},  # malformed entries are skipped
]


class FakeDaemon:
    def __init__(self, *, reject: str | None = None, error: str | None = None) -> None:
        self.reject = reject
        self.error = error
        self.hellos: list[dict] = []
        self.requests: list[dict] = []
        self.port = 0

    async def _handle(self, ws) -> None:
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "hello":
                self.hellos.append(msg)
                if self.reject:
                    await ws.send(json.dumps({"type": "hello_rejected", "reason": self.reject}))
                    return
                await ws.send(json.dumps({"type": "session", "message": {"type": "status", "payload": {}}}))
            elif msg["type"] == "session" and msg["message"]["type"] == "list_commands_request":
                request = msg["message"]
                self.requests.append(request)
                payload = {"agentId": request["agentId"], "requestId": request["requestId"],
                           "commands": [] if self.error else COMMANDS, "error": self.error}
                stale = {"agentId": "other", "requestId": "not-ours", "commands": [], "error": None}
                for item in (stale, payload):  # a response for another request must be ignored
                    await ws.send(json.dumps({"type": "session",
                                              "message": {"type": "list_commands_response", "payload": item}}))


@contextlib.asynccontextmanager
async def serve(**kwargs):
    daemon = FakeDaemon(**kwargs)
    async with websockets.serve(daemon._handle, "127.0.0.1", 0) as server:
        daemon.port = server.sockets[0].getsockname()[1]
        yield daemon
