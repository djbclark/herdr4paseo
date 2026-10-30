import json

import pytest

from herdr4paseo.core import Command, match_commands, parse_commands
from herdr4paseo.daemon import DaemonError, daemon_url, fetch_commands, local_credential

from fake_daemon import COMMANDS, serve


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PASEO_HOME", str(tmp_path))
    monkeypatch.delenv("PASEO_HOST", raising=False)
    (tmp_path / "local-credential").write_text("s3cret\n")
    return tmp_path


def test_daemon_url_prefers_host_then_config_then_default(home, monkeypatch):
    assert daemon_url() == "ws://127.0.0.1:6767/ws"
    (home / "config.json").write_text(json.dumps({"daemon": {"listen": "127.0.0.1:7263"}}))
    assert daemon_url() == "ws://127.0.0.1:7263/ws"
    monkeypatch.setenv("PASEO_HOST", "box.example:6767")
    assert daemon_url() == "ws://box.example:6767/ws"
    monkeypatch.setenv("PASEO_HOST", "https://box.example")
    assert daemon_url() == "wss://box.example/ws"


def test_local_credential_is_never_offered_to_a_remote_daemon(home):
    assert local_credential("ws://127.0.0.1:7263/ws") == "s3cret"
    assert local_credential("ws://localhost:7263/ws") == "s3cret"
    assert local_credential("ws://box.example:6767/ws") is None


def test_parse_and_match_commands():
    commands = parse_commands(COMMANDS)
    assert [c.name for c in commands] == ["code-review", "compact", "context", "steps"]
    assert commands[1] == Command("compact", "Compact the conversation", "[focus]", "command")
    assert [c.name for c in match_commands(commands, "/co")] == ["code-review", "compact", "context"]
    assert [c.name for c in match_commands(commands, "/review")] == ["code-review"]  # substring after prefixes
    assert [c.name for c in match_commands(commands, "/")] == [c.name for c in commands]
    assert match_commands(commands, "/compact now") == []  # a space ends the command name
    assert match_commands(commands, "hello") == []


async def test_fetch_commands_sends_credential_and_ignores_other_requests(home, monkeypatch):
    async with serve() as daemon:
        monkeypatch.setenv("PASEO_HOST", f"127.0.0.1:{daemon.port}")
        commands = await fetch_commands("agent-1", timeout=5)
    assert [c.name for c in commands] == ["code-review", "compact", "context", "steps"]
    assert daemon.hellos[0]["auth"] == {"kind": "localCredential", "token": "s3cret"}
    assert daemon.requests[0]["agentId"] == "agent-1"


async def test_fetch_commands_reports_rejection_error_and_unreachable(home, monkeypatch):
    async with serve(reject="bad credential") as daemon:
        monkeypatch.setenv("PASEO_HOST", f"127.0.0.1:{daemon.port}")
        with pytest.raises(DaemonError, match="bad credential"):
            await fetch_commands("agent-1", timeout=5)
    async with serve(error="agent not found") as daemon:
        monkeypatch.setenv("PASEO_HOST", f"127.0.0.1:{daemon.port}")
        with pytest.raises(DaemonError, match="agent not found"):
            await fetch_commands("agent-1", timeout=5)
    monkeypatch.setenv("PASEO_HOST", "127.0.0.1:1")
    with pytest.raises(DaemonError):
        await fetch_commands("agent-1", timeout=5)
