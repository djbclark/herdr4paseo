import json

import pytest

from herdr4paseo.core import (
    Agent,
    filter_agents,
    find_agent,
    load_history,
    logs_argv,
    ls_argv,
    parse_agents,
    parse_permissions,
    permit_argv,
    permit_ls_argv,
    save_history,
    send_argv,
    should_alert,
    stop_argv,
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


PERMITS = json.dumps(
    [
        {"id": "req11111-aaaa", "agentId": "agent-a", "agentShortId": "agent-a", "name": "Bash",
         "description": "rm -rf build"},
        {"id": "req22222-bbbb", "agentId": "agent-b", "agentShortId": "agent-b", "name": "Edit",
         "description": "-"},
    ]
)


def test_parse_permissions_filters_to_one_agent():
    permits = parse_permissions(PERMITS, "agent-a")
    assert [p.id for p in permits] == ["req11111-aaaa"]
    assert permits[0].label == "Bash: rm -rf build"
    assert parse_permissions(PERMITS, "agent-b")[0].label == "Edit"  # "-" means no description
    assert parse_permissions(PERMITS, "nobody") == []


def test_parse_permissions_rejects_non_list():
    with pytest.raises(ValueError):
        parse_permissions('{"id": "x"}', "a")


def test_permit_argv_names_one_request_never_blanket():
    assert permit_argv("allow", "agent-a", "req1")[1:] == ["permit", "allow", "agent-a", "req1"]
    assert permit_argv("deny", "agent-a", "req1")[1:] == ["permit", "deny", "agent-a", "req1"]
    assert "--all" not in permit_argv("deny", "agent-a", "req1")
    with pytest.raises(ValueError):
        permit_argv("maybe", "agent-a", "req1")
    assert permit_ls_argv()[1:] == ["permit", "ls", "--json"]


def test_follow_banner_is_dimmed_and_loses_the_ctrl_c_hint():
    banner = style_line("--- Following logs (last 20 entries; Ctrl+C to stop) ---")
    assert banner.plain == "--- following live (last 20 entries) ---"
    assert "dim" in str(banner.style)
    # a different dashed line is left alone
    assert style_line("--- something else ---").plain == "--- something else ---"


def test_filter_agents_matches_every_word_across_fields():
    a = Agent("1", "aaa", "alpha", "claude/x", "running", "~/src/a")
    b = Agent("2", "bbb", "beta", "codex/y", "idle", "~/src/b")
    assert filter_agents([a, b], "") == [a, b]
    assert filter_agents([a, b], "src/b") == [b]
    assert filter_agents([a, b], "IDLE codex") == [b]
    assert filter_agents([a, b], "nothing") == []


def test_should_alert_only_on_transitions():
    assert should_alert("running", "idle", 0, 0) == "agent idle"
    assert should_alert("idle", "idle", 0, 0) is None
    assert should_alert(None, "idle", 0, 0) is None
    assert should_alert("running", "running", 0, 1) == "permission requested"
    assert should_alert("running", "running", 2, 2) is None


def test_history_round_trip_limit_and_bad_files(tmp_path):
    path = tmp_path / "sub" / "h.json"
    assert load_history(path) == []
    save_history(path, ["a", "b", "c"], limit=2)
    assert load_history(path) == ["b", "c"]
    path.write_text("not json")
    assert load_history(path) == []
    path.write_text('{"x": 1}')
    assert load_history(path) == []


def test_stop_argv_targets_one_agent(monkeypatch):
    monkeypatch.setenv("PASEO_BIN", "paseo")
    assert stop_argv("abc") == ["paseo", "stop", "abc"]
