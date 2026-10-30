import json
import stat
from pathlib import Path

import pytest
from textual.widgets import RichLog

from fake_daemon import serve
from herdr4paseo.app import Herdr4PaseoApp, PromptArea

FAKE = Path(__file__).with_name("fake_paseo.py")


@pytest.fixture
def calls(tmp_path, monkeypatch):
    FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR)
    path = tmp_path / "calls.jsonl"
    path.touch()
    monkeypatch.setenv("PASEO_BIN", str(FAKE))
    monkeypatch.setenv("FAKE_PASEO_CALLS", str(path))
    monkeypatch.setenv("PASEO_HOME", str(tmp_path / "home"))  # no credential, no real daemon
    monkeypatch.setenv("PASEO_HOST", "127.0.0.1:1")  # refused at once: slash completion stays off
    monkeypatch.delenv("FAKE_PASEO_SEND_FAIL", raising=False)
    return path


def recorded(path: Path) -> list[list[str]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def log_text(app: Herdr4PaseoApp) -> str:
    return "\n".join(line.text for line in app.query_one("#log", RichLog).lines)


async def settle(pilot, app, needle: str) -> None:
    for _ in range(100):
        await pilot.pause(0.05)
        if needle in log_text(app):
            return
    raise AssertionError(f"{needle!r} never appeared; log was:\n{log_text(app)}")


async def test_attach_streams_log_and_status(calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        assert "[User] hello there" in log_text(app)
        assert app.title == "alpha (aaaaaaa)"
        assert "running" in app.sub_title and "steer" in app.sub_title
    logs_call = next(c for c in recorded(calls) if c[0] == "logs")
    assert logs_call[1] == "aaaaaaa1-0000-0000-0000-000000000001"
    assert "5" in logs_call


async def test_enter_sends_with_current_behavior_and_clears(calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        await pilot.press("ctrl+t")  # steer -> interrupt
        await pilot.press(*"hello", "enter")
        await pilot.pause(0.3)
        assert app.query_one("#prompt", PromptArea).text == ""
    send = next(c for c in recorded(calls) if c[0] == "send")
    assert send[-4:] == ["--no-wait", "--behavior", "interrupt", "hello"]


async def test_failed_send_keeps_text_and_reports(calls, monkeypatch):
    monkeypatch.setenv("FAKE_PASEO_SEND_FAIL", "1")
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        await pilot.press(*"keep me", "enter")
        await settle(pilot, app, "send failed")
        assert app.query_one("#prompt", PromptArea).text == "keep me"


async def test_ctrl_j_inserts_newline_instead_of_sending(calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        await pilot.press("a", "ctrl+j", "b")
        assert app.query_one("#prompt", PromptArea).text == "a\nb"
    assert not any(c[0] == "send" for c in recorded(calls))


async def test_tools_only_toggle_restarts_stream_with_filter(calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        await pilot.press("ctrl+o")
        await settle(pilot, app, "[Shell] ls")
        assert "plain assistant line" not in log_text(app)
        assert "tools only" in app.sub_title
    assert any(c[0] == "logs" and "--filter" in c for c in recorded(calls))


async def test_history_recall(calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        await pilot.press(*"first", "enter")
        await pilot.pause(0.3)
        await pilot.press("ctrl+p")
        assert app.query_one("#prompt", PromptArea).text == "first"
        await pilot.press("ctrl+n")
        assert app.query_one("#prompt", PromptArea).text == ""


AGENT_A = "aaaaaaa1-0000-0000-0000-000000000001"
PERMITS = json.dumps(
    [
        {"id": "req11111-aaaa", "agentId": AGENT_A, "agentShortId": "aaaaaaa", "name": "Bash",
         "description": "rm -rf build"},
        {"id": "req22222-bbbb", "agentId": AGENT_A, "agentShortId": "aaaaaaa", "name": "Edit",
         "description": "src/x.py"},
        {"id": "req33333-cccc", "agentId": "bbbbbbb2-0000-0000-0000-000000000002",
         "agentShortId": "bbbbbbb", "name": "Bash", "description": "other agent"},
    ]
)


def permit_calls(path: Path) -> list[list[str]]:
    return [c for c in recorded(path) if c[0] == "permit" and c[1] != "ls"]


async def banner_visible(pilot, app) -> None:
    for _ in range(100):
        await pilot.pause(0.05)
        if not app.query_one("#permits").has_class("hidden"):
            return
    raise AssertionError("permit banner never appeared")


@pytest.fixture
def pending(calls, monkeypatch):
    monkeypatch.setenv("FAKE_PASEO_PERMITS", PERMITS)


async def test_no_pending_means_no_banner_and_prompt_keeps_ctrl_a(calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        assert app.query_one("#permits").has_class("hidden")
        await pilot.press(*"abc", "ctrl+a", "x")  # ctrl+a is the prompt's line-start
        assert app.query_one("#prompt", PromptArea).text == "xabc"
    assert permit_calls(calls) == []


async def test_banner_lists_only_this_agents_requests(pending, calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await banner_visible(pilot, app)
        assert [p.id for p in app.permits] == ["req11111-aaaa", "req22222-bbbb"]


async def test_allow_confirms_then_answers_each_shown_request_by_id(pending, calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await banner_visible(pilot, app)
        await pilot.press("ctrl+a")
        await pilot.pause(0.3)
        assert permit_calls(calls) == []  # nothing answered before confirming
        await pilot.press("y")
        await pilot.pause(0.5)
    assert permit_calls(calls) == [
        ["permit", "allow", AGENT_A, "req11111-aaaa"],
        ["permit", "allow", AGENT_A, "req22222-bbbb"],
    ]


async def test_declining_confirmation_answers_nothing(pending, calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await banner_visible(pilot, app)
        await pilot.press("ctrl+a")
        await pilot.pause(0.3)
        await pilot.press("n")
        await pilot.pause(0.3)
    assert permit_calls(calls) == []


async def test_deny_answers_by_id(pending, calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await banner_visible(pilot, app)
        await pilot.press("ctrl+d")
        await pilot.pause(0.3)
        await pilot.press("y")
        await pilot.pause(0.5)
    assert [c[1] for c in permit_calls(calls)] == ["deny", "deny"]


@pytest.fixture
async def daemon(calls, monkeypatch):
    async with serve() as fake:
        monkeypatch.setenv("PASEO_HOST", f"127.0.0.1:{fake.port}")
        yield fake


def slash_text(app: Herdr4PaseoApp) -> str:
    return str(app.query_one("#slash").render())


async def commands_loaded(pilot, app) -> None:
    for _ in range(100):
        await pilot.pause(0.05)
        if app.commands:
            return
    raise AssertionError("slash commands never loaded")


async def test_typing_slash_suggests_and_tab_completes(daemon):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await commands_loaded(pilot, app)
        assert app.query_one("#slash").has_class("hidden")
        await pilot.press("/", "c", "o")
        assert [c.name for c in app.slash_matches] == ["code-review", "compact", "context"]
        assert "/compact [focus]" in slash_text(app)
        await pilot.press("down", "tab")  # highlight the second match, then accept it
        assert app.query_one("#prompt", PromptArea).text == "/compact "
        assert app.query_one("#slash").has_class("hidden")  # the space ends the command name
    assert daemon.requests[0]["agentId"] == "aaaaaaa1-0000-0000-0000-000000000001"


async def test_enter_sends_a_partial_slash_command_as_typed(daemon, calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await commands_loaded(pilot, app)
        await pilot.press("/", "c", "o", "n", "enter")
        await pilot.pause(0.3)
    send = next(c for c in recorded(calls) if c[0] == "send")
    assert send[-1] == "/con"


async def test_tab_and_arrows_do_nothing_special_without_suggestions(daemon):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await commands_loaded(pilot, app)
        await pilot.press("h", "i")
        assert app.slash_matches == []
        assert app.query_one("#slash").has_class("hidden")


async def test_unreachable_daemon_degrades_to_a_note(calls):
    app = Herdr4PaseoApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "slash completion unavailable")
        await pilot.press("/", "c")
        assert app.slash_matches == []
        await pilot.press("enter")  # typed commands still send
        await pilot.pause(0.3)
    assert any(c[0] == "send" and c[-1] == "/c" for c in recorded(calls))
