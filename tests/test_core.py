import json

import pytest
from rich.color import ColorSystem
from rich.style import Style
from rich.text import Text

from herdr4paseo.core import (
    META_TAGS,
    THEME,
    Agent,
    LogStyler,
    agent_label_text,
    filter_agents,
    find_agent,
    load_history,
    logs_argv,
    ls_argv,
    parse_agents,
    parse_permissions,
    permit_argv,
    permit_ls_argv,
    run_argv,
    save_history,
    send_argv,
    should_alert,
    status_style,
    stop_argv,
    style_for,
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


def style_at(text: Text, index: int) -> Style:
    """The combined style of the character at `index` (base style, then spans in order)."""
    styles = [Style.parse(str(text.style))] if text.style else []
    for span in text.spans:
        if span.start <= index < span.end:
            styles.append(span.style if isinstance(span.style, Style) else Style.parse(span.style))
    return Style.combine(styles) if styles else Style.null()


def tok(name: str) -> Style:
    return Style.parse(THEME[name])


def lines(*raw: str) -> list[Text]:
    styler = LogStyler()
    return [styler.style(line) for line in raw]


def test_style_line_colours_tag_and_body_by_token():
    user = style_line("[User] hi")
    assert user.plain == "[User] hi"
    assert style_at(user, 0) == tok("user.tag")
    assert style_at(user, 7) == tok("user.text")
    assert style_line("no tag here").spans == []
    assert str(style_line("[Error] bad").spans[0].style) == THEME["error.tag"]


def test_every_theme_value_parses():
    for token, value in THEME.items():
        Style.parse(value)  # raises StyleSyntaxError on a typo
    with pytest.raises(KeyError):
        style_for("no.such.token")


def test_tag_styling_by_kind():
    user, shell, error, reconnect, compacted, banner = lines(
        "[User] hi",
        "[Shell] ls /tmp/x",
        "[Error] boom",
        "[Reconnected; replaying]",
        "[Compacted]",
        "--- Following logs (last 20 entries; Ctrl+C to stop) ---",
    )
    assert (style_at(user, 1), style_at(user, 8)) == (tok("user.tag"), tok("user.text"))
    assert style_at(shell, 1) == tok("tool.tag")
    assert style_at(shell, 8).color == tok("tool.detail").color
    assert style_at(shell, 12).underline  # the path in the summary
    assert not style_at(shell, 8).underline
    assert (style_at(error, 1), style_at(error, 9)) == (tok("error.tag"), tok("error.text"))
    for meta in (reconnect, compacted, banner):
        assert style_at(meta, 1) == tok("meta")
    assert "compacted" in META_TAGS
    assert style_line("[Timeline replaced; x]").spans[0].style == THEME["meta"]
    assert style_line("[Earlier chat history omitted]").spans[0].style == THEME["meta"]


def test_markdown_link_at_line_start_is_not_a_tag():
    link = style_line("[foo](http://x) rest")
    assert style_at(link, 1) == tok("md.link") and style_at(link, 3) == tok("md.link")  # the label
    assert style_at(link, 0) == Style.null() and style_at(link, 4) == Style.null()  # the brackets
    assert style_at(link, 7) == Style.null() and style_at(link, 14) == Style.null()  # the URL
    assert style_at(link, 17) == Style.null()
    assert style_line("[foo]bar").spans == []  # not followed by whitespace either


def test_continuation_lines_inherit_user_and_thought_but_not_tool_lines():
    _head, cont = lines("[Thought] a", "b")
    assert style_at(cont, 0).italic  # italic, not colour alone, survives NO_COLOR
    _head, cont = lines("[User] a", "b")
    assert style_at(cont, 0) == tok("user.text")
    _head, prose = lines("[Shell] ls", "prose")
    assert prose.spans == []
    _head, _prose, tagged = lines("[Thought] a", "b", "[Shell] ls")
    assert style_at(tagged, 1) == tok("tool.tag")  # a new tag ends the block


def test_diff_fence_colours_added_removed_and_hunk_lines():
    fence, hunk, add, remove, context, close, after = lines(
        "```diff", "@@ -1 +1 @@", "+x", "-x", " same", "```", "+not a diff"
    )
    assert style_at(fence, 0) == tok("md.fence")
    assert style_at(hunk, 0) == tok("diff.hunk")
    assert style_at(add, 0) == tok("diff.add")
    assert style_at(remove, 0) == tok("diff.remove")
    assert style_at(context, 1) == tok("diff.context")
    assert style_at(close, 0) == tok("md.fence")
    assert after.spans == []  # state reset after the closing fence
    assert [t.plain for t in (add, remove)] == ["+x", "-x"]  # the +/- survive without colour


def test_code_fence_uses_pygments_and_resets():
    fence, code, close, after = lines("```python", "def f(): return 1", "```", "def f(): return 1")
    assert style_at(fence, 0) == tok("md.fence")
    assert code.spans and code.plain == "def f(): return 1"
    assert after.spans == []
    unknown = lines("```no-such-language", "def f(): return 1")[1]
    assert unknown.spans == []


def test_assistant_markdown_is_styled_per_line():
    heading, bullet, quote, inline = lines("# Title", "- item", "> said", "use `code` here")
    assert style_at(heading, 2) == tok("md.heading")
    assert style_at(bullet, 0) == tok("md.bullet") and style_at(bullet, 3) == Style.null()
    assert style_at(quote, 3) == tok("md.quote")
    assert style_at(inline, 5) == tok("md.code") and style_at(inline, 0) == Style.null()


def test_task_list_marks_done_items_only():
    _tasks, done, todo, after = lines("[Tasks]", "- [x] done", "- [ ] todo", "prose")
    assert style_at(done, 3) == tok("success")
    assert todo.spans == []
    assert after.spans == []


def test_monochrome_legibility_needs_more_than_colour():
    plain = Style.parse(THEME["assistant.text"]).without_color
    for token in ("user.tag", "thought"):
        assert Style.parse(THEME[token]).without_color != plain, token


def test_sixteen_colour_distinctness():
    downgraded = {
        token: Style.parse(THEME[token]).color.downgrade(ColorSystem.STANDARD)
        for token in ("user.tag", "tool.tag", "error.tag", "success")
    }
    assert len(set(downgraded.values())) == 4, downgraded


def test_status_style_and_picker_label():
    assert status_style("running") == THEME["status.running"]
    assert status_style("idle") == THEME["status.idle"]
    assert status_style("error") == THEME["status.error"]
    assert status_style("archived") == THEME["status.closed"]
    assert status_style("???") == ""
    label = agent_label_text(Agent("i", "abc", "my agent", "codex/x", "idle", "/"))
    assert label.plain.startswith("abc  idle")
    assert style_at(label, 5).color == tok("status.idle").color and style_at(label, 0) == Style.null()


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
    assert banner.style == THEME["meta"]
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


def test_run_argv_is_quiet_nowait_and_guards_leading_dash(monkeypatch):
    monkeypatch.setenv("PASEO_BIN", "paseo")
    assert run_argv("do it", "claude") == ["paseo", "run", "--no-wait", "--quiet", "--provider", "claude", "do it"]
    assert run_argv("-x", "codex") == ["paseo", "run", "--no-wait", "--quiet", "--provider", "codex", " -x"]
