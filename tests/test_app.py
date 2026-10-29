import json
import stat
from pathlib import Path

import pytest
from textual.widgets import RichLog

from paseo_pane.app import PaneApp, PromptArea

FAKE = Path(__file__).with_name("fake_paseo.py")


@pytest.fixture
def calls(tmp_path, monkeypatch):
    FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR)
    path = tmp_path / "calls.jsonl"
    path.touch()
    monkeypatch.setenv("PASEO_BIN", str(FAKE))
    monkeypatch.setenv("FAKE_PASEO_CALLS", str(path))
    monkeypatch.delenv("FAKE_PASEO_SEND_FAIL", raising=False)
    return path


def recorded(path: Path) -> list[list[str]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def log_text(app: PaneApp) -> str:
    return "\n".join(line.text for line in app.query_one("#log", RichLog).lines)


async def settle(pilot, app, needle: str) -> None:
    for _ in range(100):
        await pilot.pause(0.05)
        if needle in log_text(app):
            return
    raise AssertionError(f"{needle!r} never appeared; log was:\n{log_text(app)}")


async def test_attach_streams_log_and_status(calls):
    app = PaneApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        assert "[User] hello there" in log_text(app)
        assert app.title == "alpha (aaaaaaa)"
        assert "running" in app.sub_title and "steer" in app.sub_title
    logs_call = next(c for c in recorded(calls) if c[0] == "logs")
    assert logs_call[1] == "aaaaaaa1-0000-0000-0000-000000000001"
    assert "5" in logs_call


async def test_enter_sends_with_current_behavior_and_clears(calls):
    app = PaneApp("aaaaaaa", tail=5, behavior="steer")
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
    app = PaneApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        await pilot.press(*"keep me", "enter")
        await settle(pilot, app, "send failed")
        assert app.query_one("#prompt", PromptArea).text == "keep me"


async def test_ctrl_j_inserts_newline_instead_of_sending(calls):
    app = PaneApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        await pilot.press("a", "ctrl+j", "b")
        assert app.query_one("#prompt", PromptArea).text == "a\nb"
    assert not any(c[0] == "send" for c in recorded(calls))


async def test_tools_only_toggle_restarts_stream_with_filter(calls):
    app = PaneApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        await pilot.press("ctrl+o")
        await settle(pilot, app, "[Shell] ls")
        assert "plain assistant line" not in log_text(app)
        assert "tools only" in app.sub_title
    assert any(c[0] == "logs" and "--filter" in c for c in recorded(calls))


async def test_history_recall(calls):
    app = PaneApp("aaaaaaa", tail=5, behavior="steer")
    async with app.run_test() as pilot:
        await settle(pilot, app, "plain assistant line")
        await pilot.press(*"first", "enter")
        await pilot.pause(0.3)
        await pilot.press("ctrl+p")
        assert app.query_one("#prompt", PromptArea).text == "first"
        await pilot.press("ctrl+n")
        assert app.query_one("#prompt", PromptArea).text == ""
