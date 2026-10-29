import json

import pytest

from paseo_pane.core import (
    Agent,
    find_agent,
    logs_argv,
    ls_argv,
    parse_agents,
    send_argv,
    style_line,
)

LS = json.dumps(
    [
        {"id": "7dba08f1-49d5", "shortId": "7dba08f", "name": "one", "provider": "codex/x",
         "status": "running", "cwd": "~/src/a"},
        {"id": "7dbb0000-0000", "name": "two", "status": "idle"},
    ]
)


def test_parse_agents_tolerates_missing_keys():
    agents = parse_agents(LS)
    assert [a.short_id for a in agents] == ["7dba08f", "7dbb000"]
    assert agents[1].provider == ""


def test_parse_agents_rejects_non_list():
    with pytest.raises(ValueError):
        parse_agents('{"id": "x"}')


def test_find_agent_by_short_id_prefix_and_ambiguity():
    agents = parse_agents(LS)
    assert find_agent(agents, "7dba08f") == agents[0]
    assert find_agent(agents, "7dba08f1-49") == agents[0]
    assert find_agent(agents, "7db") is None  # ambiguous prefix
    assert find_agent(agents, "zzz") is None


def test_agent_label_has_short_id_status_name():
    label = Agent("i", "abc", "my agent", "codex/x", "idle", "/").label
    assert label.startswith("abc") and "idle" in label and "my agent" in label


def test_logs_argv_flags():
    base = logs_argv("abc", tail=20, tools_only=False)
    assert base[1:] == ["logs", "abc", "--no-color", "--tail", "20", "-f"]
    assert logs_argv("abc", tail=20, tools_only=True)[-2:] == ["--filter", "tools"]


def test_send_argv_never_waits_and_sets_behavior():
    argv = send_argv("abc", "do it", "interrupt")
    assert argv[1:] == ["send", "abc", "--no-wait", "--behavior", "interrupt", "do it"]


def test_send_argv_protects_leading_dash():
    assert send_argv("abc", "-rf thing", "steer")[-1] == " -rf thing"


def test_send_argv_rejects_unknown_behavior():
    with pytest.raises(ValueError):
        send_argv("abc", "x", "yolo")


def test_ls_argv_asks_for_json():
    assert ls_argv()[1:] == ["ls", "-g", "-a", "--json"]


def test_style_line_colours_only_the_tag():
    user = style_line("[User] hi")
    assert user.plain == "[User] hi"
    assert [(s.start, s.end) for s in user.spans] == [(0, 6)]
    assert style_line("no tag here").spans == []
    assert "red" in str(style_line("[Error] bad").spans[0].style)
