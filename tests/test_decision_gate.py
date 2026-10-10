from __future__ import annotations

import io
import json
import re
import tempfile
import urllib.error
from pathlib import Path
from typing import Any

import pytest

import decision_gate
from policy import Action, Policy, Signals, decide

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"

ALL_CLEAR = {name: 0.05 for name in decision_gate.QUESTION_NAMES}


def signals(**overrides: float) -> Signals:
    values = dict.fromkeys(decision_gate.QUESTION_NAMES, 0.0)
    values.update(overrides)
    return Signals(**values)


def answers(**overrides: float) -> dict[str, Any]:
    values = dict(ALL_CLEAR)
    values.update(overrides)
    return {name: {"type": "noul", "noul": value} for name, value in values.items()}


def response(**overrides: float) -> dict[str, Any]:
    return {"model": "jev-1.13.0", "answers": answers(**overrides)}


def payload(tool: str = "bash", **tool_input: Any) -> dict[str, Any]:
    return {
        "session_id": "s-1",
        "cwd": "E:/workspace/muiltilab",
        "tool_name": tool,
        "tool_input": tool_input,
    }


def run_main(monkeypatch: pytest.MonkeyPatch, raw: str, capsys: Any) -> dict[str, Any]:
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    monkeypatch.setenv("DECISION_GATE_LOG", str(Path(tempfile.gettempdir()) / "decision_gate_tests.jsonl"))
    exit_code = decision_gate.main()
    assert exit_code == 0
    return json.loads(capsys.readouterr().out)


@pytest.fixture(autouse=True)
def a_key_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")


# --- policy ---


def test_denies_secret_exposure_at_threshold() -> None:
    decision = decide(signals(secret_exposure=0.5))
    assert decision.action is Action.DENY
    assert decision.rule == "secret_exposure"


def test_denies_destructive_at_threshold() -> None:
    decision = decide(signals(destructive=0.62))
    assert decision.action is Action.DENY
    assert decision.rule == "destructive"


def test_asks_when_state_changes_outside_the_machine() -> None:
    decision = decide(signals(external_irreversible=0.93))
    assert decision.action is Action.ASK
    assert decision.rule == "external_irreversible"


def test_allows_a_read_only_command() -> None:
    decision = decide(signals(read_only=0.97))
    assert decision.action is Action.ALLOW
    assert decision.rule == "read_only"


def test_allows_a_routine_development_step() -> None:
    decision = decide(signals(routine_dev=0.95))
    assert decision.action is Action.ALLOW
    assert decision.rule == "routine_dev"


def test_asks_when_no_signal_is_confident() -> None:
    decision = decide(signals(read_only=0.27, routine_dev=0.31))
    assert decision.action is Action.ASK
    assert decision.rule == "unclear"


def test_danger_outranks_safety_when_both_fire() -> None:
    assert decide(signals(read_only=0.99, routine_dev=0.99, destructive=0.9)).action is Action.DENY


def test_secret_exposure_outranks_destructive() -> None:
    assert decide(signals(destructive=0.99, secret_exposure=0.99)).rule == "secret_exposure"



def test_a_pre_authorized_irreversible_step_is_allowed() -> None:
    decision = decide(signals(external_irreversible=0.93), authorized=True)
    assert decision.action is Action.ALLOW
    assert decision.rule == "authorized_external"


def test_the_same_step_asks_without_the_authorization() -> None:
    decision = decide(signals(external_irreversible=0.93), authorized=False)
    assert decision.action is Action.ASK
    assert decision.rule == "external_irreversible"


def test_authorization_never_launders_a_secret_verdict() -> None:
    decision = decide(signals(secret_exposure=0.87, external_irreversible=0.87), authorized=True)
    assert decision.action is Action.DENY
    assert decision.rule == "secret_exposure"


def test_authorization_never_launders_a_destructive_verdict() -> None:
    decision = decide(signals(destructive=0.65, external_irreversible=0.91), authorized=True)
    assert decision.action is Action.DENY
    assert decision.rule == "destructive"


def test_an_empty_authorization_list_never_matches() -> None:
    assert decision_gate.is_authorized("git push origin main", []) is False


def test_authorization_matches_a_whole_statement() -> None:
    entries = ["git push origin main"]
    assert decision_gate.is_authorized("git push origin main", entries) is True
    assert decision_gate.is_authorized("  git   push   origin main  ", entries) is True
    # wrapped the way a shell call actually arrives -- the case that made
    # whole-command equality unusable in practice
    assert (
        decision_gate.is_authorized(
            "Set-Location 'E:/workspace/x'\ngit push origin main 2>&1 | Select-Object -Last 3",
            entries,
        )
        is True
    )
    assert decision_gate.is_authorized("cd /tmp && git push origin main", entries) is True
    # a different command is still a different command
    assert decision_gate.is_authorized("git push origin main --force", entries) is False
    assert decision_gate.is_authorized("git push origin feature", entries) is False
    assert decision_gate.is_authorized("git pull origin main", entries) is False


def test_authorization_answers_only_about_the_approved_step() -> None:
    # The whitelist answers "may this approved step run", never "is this whole
    # script safe". The dangerous half of a compound command is denied by the
    # secret_exposure / destructive rules before this is ever consulted.
    assert decision_gate.is_authorized("echo hi && git push origin main", ["git push origin main"]) is True
    assert decision_gate.is_authorized("echo hi", ["git push origin main"]) is False
def test_a_weak_read_signal_does_not_allow() -> None:
    assert decide(signals(read_only=0.79)).action is Action.ASK


def test_policy_thresholds_are_overridable() -> None:
    assert decide(signals(read_only=0.97), Policy(read_only=0.99)).action is Action.ASK
    assert decide(signals(read_only=0.97)).action is Action.ALLOW


def test_policy_from_env_reads_every_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECISION_GATE_READ_ONLY", "0.55")
    monkeypatch.setenv("DECISION_GATE_DESTRUCTIVE", "0.4")
    policy = decision_gate.policy_from_env()
    assert policy.read_only == 0.55
    assert policy.destructive == 0.4
    assert policy.routine_dev == Policy().routine_dev


def test_policy_from_env_ignores_junk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECISION_GATE_READ_ONLY", "not-a-number")
    assert decision_gate.policy_from_env().read_only == Policy().read_only


# --- state and answers ---


def test_state_carries_the_raw_tool_call() -> None:
    state = decision_gate.build_state(payload(command="git status --short"))
    assert state["tool_call"] == {"name": "bash", "arguments": {"command": "git status --short"}}
    assert state["session"]["cwd"] == "E:/workspace/muiltilab"


def test_state_reports_a_missing_tool_input_as_empty() -> None:
    state = decision_gate.build_state({"session_id": "s", "cwd": "c", "tool_name": "bash"})
    assert state["tool_call"]["arguments"] == {}


def test_state_clips_an_oversized_argument() -> None:
    command = decision_gate.build_state(payload(command="x" * 20000))["tool_call"]["arguments"]["command"]
    assert len(command) < 20000
    assert "truncated" in command


def test_state_keeps_nested_arguments_intact() -> None:
    state = decision_gate.build_state(payload(command=["a", "b"], nested={"k": "v"}))
    assert state["tool_call"]["arguments"] == {"command": ["a", "b"], "nested": {"k": "v"}}


def test_every_question_is_a_noul_with_both_criteria() -> None:
    for name, question in decision_gate.build_questions().items():
        assert question["type"] == "noul", name
        assert question["instructions"], name
        assert set(question["criteria"]) == {"true", "false"}, name


def test_signals_are_read_from_every_answer() -> None:
    result = decision_gate.to_signals(answers(destructive=0.91, read_only=0.97))
    assert result.destructive == 0.91
    assert result.read_only == 0.97


def test_signals_reject_an_unexpected_answer_shape() -> None:
    broken = answers()
    broken["destructive"] = {"type": "choice", "choice": "yes"}
    with pytest.raises(ValueError, match="destructive"):
        decision_gate.to_signals(broken)


def test_signals_reject_a_missing_answer() -> None:
    broken = answers()
    del broken["read_only"]
    with pytest.raises(ValueError, match="read_only"):
        decision_gate.to_signals(broken)


def test_signals_reject_a_boolean_masquerading_as_a_probability() -> None:
    broken = answers()
    broken["destructive"] = {"type": "noul", "noul": True}
    with pytest.raises(ValueError, match="destructive"):
        decision_gate.to_signals(broken)


# --- the request it makes ---


class FakeHttpResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, *_: Any) -> bool:
        return False


def install_transport(monkeypatch: pytest.MonkeyPatch, outcomes: list[Any]) -> list[Any]:
    sent: list[Any] = []

    def fake_urlopen(request: Any, timeout: float | None = None) -> Any:
        sent.append(request)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeHttpResponse(outcome)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    return sent


def test_judge_posts_to_the_systemone_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = install_transport(monkeypatch, [response()])
    decision_gate.judge({"tool_call": {"name": "bash"}}, "jev-1.13.0")
    assert sent[0].full_url == "https://api.typesafe.ai/v1/systemone"
    assert sent[0].method == "POST"


def test_judge_sends_the_key_as_a_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = install_transport(monkeypatch, [response()])
    decision_gate.judge({"tool_call": {"name": "bash"}}, "jev-1.13.0")
    headers = {key.lower(): value for key, value in sent[0].headers.items()}
    assert headers["Authorization".lower()] == "Bearer test-key"
    assert headers["Content-type".lower()] == "application/json"


def test_judge_sends_the_pinned_model_and_every_question(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = install_transport(monkeypatch, [response()])
    decision_gate.judge({"tool_call": {"name": "bash"}}, "jev-1.13.0")
    body = json.loads(sent[0].data.decode("utf-8"))
    assert body["model"] == "jev-1.13.0"
    assert set(body["questions"]) == set(decision_gate.QUESTION_NAMES)
    assert body["questions"]["destructive"]["type"] == "noul"


def test_judge_retries_a_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    too_many = urllib.error.HTTPError(decision_gate.ENDPOINT, 429, "slow down", {}, None)
    sent = install_transport(monkeypatch, [too_many, response(read_only=0.9)])
    result = decision_gate.judge({"tool_call": {"name": "bash"}}, "jev-1.13.0")
    assert len(sent) == 2
    assert result["answers"]["read_only"]["noul"] == 0.9


def test_judge_does_not_retry_a_rejected_key(monkeypatch: pytest.MonkeyPatch) -> None:
    unauthorized = urllib.error.HTTPError(decision_gate.ENDPOINT, 401, "Unauthorized", {}, None)
    sent = install_transport(monkeypatch, [unauthorized])
    with pytest.raises(RuntimeError, match="401"):
        decision_gate.judge({"tool_call": {"name": "bash"}}, "jev-1.13.0")
    assert len(sent) == 1


def test_judge_gives_up_after_the_retry_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    server_error = urllib.error.HTTPError(decision_gate.ENDPOINT, 503, "unavailable", {}, None)
    sent = install_transport(monkeypatch, [server_error, server_error])
    with pytest.raises(RuntimeError, match="gave up"):
        decision_gate.judge({"tool_call": {"name": "bash"}}, "jev-1.13.0")
    assert len(sent) == decision_gate.MAX_ATTEMPTS


def test_judge_retries_a_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = install_transport(
        monkeypatch, [urllib.error.URLError("connection refused"), response()]
    )
    decision_gate.judge({"tool_call": {"name": "bash"}}, "jev-1.13.0")
    assert len(sent) == 2


def test_judge_refuses_to_call_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decision_gate, "resolve_api_key", lambda: "")
    with pytest.raises(RuntimeError, match="no TypeSafe API key"):
        decision_gate.judge({"tool_call": {"name": "bash"}}, "jev-1.13.0")


# --- the hook process ---


def test_hook_allows_a_safe_command(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(decision_gate, "judge", lambda state, model: response(read_only=0.97))
    output = run_main(monkeypatch, json.dumps(payload(command="git status")), capsys)
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_hook_denies_a_destructive_command(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(decision_gate, "judge", lambda state, model: response(destructive=0.91))
    output = run_main(monkeypatch, json.dumps(payload(command="rm -rf src")), capsys)
    block = output["hookSpecificOutput"]
    assert block["permissionDecision"] == "deny"
    assert "0.91" in block["permissionDecisionReason"]


def test_hook_asks_before_an_irreversible_remote_action(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(
        decision_gate, "judge", lambda state, model: response(external_irreversible=0.93)
    )
    output = run_main(monkeypatch, json.dumps(payload(command="git push --force")), capsys)
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_hook_names_the_event_it_answered(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(decision_gate, "judge", lambda state, model: response(read_only=0.9))
    output = run_main(monkeypatch, json.dumps(payload(command="ls")), capsys)
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


def test_hook_only_ever_emits_the_decisions_dsh_accepts(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    accepted = {"allow", "deny", "ask"}
    for reading in ("read_only", "destructive", "external_irreversible"):
        monkeypatch.setattr(
            decision_gate,
            "judge",
            lambda state, model, reading=reading: response(**{reading: 0.9}),
        )
        output = run_main(monkeypatch, json.dumps(payload(command="x")), capsys)
        assert output["hookSpecificOutput"]["permissionDecision"] in accepted


def test_hook_falls_back_when_the_service_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def boom(state: Any, model: str) -> Any:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(decision_gate, "judge", boom)
    output = run_main(monkeypatch, json.dumps(payload(command="ls")), capsys)
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert "connection refused" in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "connection refused" in output["systemMessage"]


def test_hook_falls_back_when_the_response_has_no_answers(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(decision_gate, "judge", lambda state, model: {"model": "jev-1.13.0"})
    output = run_main(monkeypatch, json.dumps(payload(command="ls")), capsys)
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_hook_falls_back_on_a_malformed_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    output = run_main(monkeypatch, "not json at all", capsys)
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_hook_falls_back_on_a_non_object_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    output = run_main(monkeypatch, "[1, 2, 3]", capsys)
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_fallback_action_is_configurable(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setenv("DECISION_GATE_ON_ERROR", "ask")
    output = run_main(monkeypatch, "not json", capsys)
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_an_unknown_fallback_action_degrades_to_allow(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setenv("DECISION_GATE_ON_ERROR", "explode")
    output = run_main(monkeypatch, "not json", capsys)
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_hook_records_the_judgment_for_later_calibration(
    monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    log = tmp_path / "decisions.jsonl"
    monkeypatch.setenv("DECISION_GATE_LOG", str(log))
    monkeypatch.setattr(decision_gate, "judge", lambda state, model: response(destructive=0.91))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload(command="rm -rf src"))))
    decision_gate.main()
    capsys.readouterr()
    record = json.loads(log.read_text(encoding="utf-8").strip())
    assert record["signals"]["destructive"] == 0.91
    assert record["action"] == "deny"
    assert record["tool"] == "bash"
    assert record["arguments"] == {"command": "rm -rf src"}


# --- the shipped configuration ---


def test_hooks_config_is_valid_json() -> None:
    config = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    assert "PreToolUse" in config["hooks"]


def test_hooks_config_registers_command_hooks_only() -> None:
    config = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    for group in config["hooks"]["PreToolUse"]:
        for hook in group["hooks"]:
            assert hook["type"] == "command"


def test_matcher_covers_the_shell_and_nothing_else() -> None:
    config = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    matcher = re.compile(config["hooks"]["PreToolUse"][0]["matcher"])
    for tool in ("bash", "pwsh", "terminal_open", "terminal_send", "terminal_signal"):
        assert matcher.search(tool), tool
    for tool in (
        "read",
        "write",
        "edit",
        "str_replace_editor",
        "glob",
        "grep",
        "todo_write",
        "web_search",
    ):
        assert not matcher.search(tool), tool


def test_matcher_is_read_as_a_regex_not_a_literal_list() -> None:
    config = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    matcher = config["hooks"]["PreToolUse"][0]["matcher"]
    assert re.fullmatch(r"[A-Za-z0-9_|]+", matcher) is None, (
        "DSH treats a pattern of only word characters and '|' as a literal "
        "pipe-separated list, where 'terminal_' would never match 'terminal_open'"
    )


def test_hooks_config_command_points_at_the_gate_script() -> None:
    config = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    command = config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    resolved = {Path(token).resolve() for token in command.split() if Path(token).exists()}
    assert (HOOKS_DIR / "decision_gate.py").resolve() in resolved
    assert any(path.name.startswith("python") for path in resolved)


def test_hooks_config_leaves_room_for_the_whole_retry_budget() -> None:
    config = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    timeout = config["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"]
    assert timeout > decision_gate.MAX_ATTEMPTS * decision_gate.REQUEST_TIMEOUT_SECONDS


def test_hook_entries_only_use_fields_the_bridge_reads() -> None:
    # The bridge reads `type`, `command`, and `timeout`; every other key is
    # dropped without a diagnostic, so `timeoutSec` would silently mean 600s.
    config = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    for group in config["hooks"]["PreToolUse"]:
        assert set(group) <= {"matcher", "hooks"}
        for hook in group["hooks"]:
            assert set(hook) <= {"type", "command", "timeout"}, hook


def test_log_falls_back_when_the_script_directory_is_not_writable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The hook runs through the harness's sandboxed shell executor, so a gate
    # installed outside the session workspace cannot write beside its own
    # script. Losing the record there is what made a working gate look dead.
    monkeypatch.delenv("DECISION_GATE_LOG", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(decision_gate, "_writable", lambda path: path.parent == tmp_path)
    monkeypatch.setattr(
        decision_gate, "log_candidates", lambda: (decision_gate.DEFAULT_LOG, tmp_path / "decisions.jsonl")
    )
    assert decision_gate.resolve_log_path() == tmp_path / "decisions.jsonl"


def test_explicit_log_path_wins_over_every_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "explicit.jsonl"
    monkeypatch.setenv("DECISION_GATE_LOG", str(target))
    monkeypatch.setattr(decision_gate, "_writable", lambda path: False)
    assert decision_gate.resolve_log_path() == target


def test_log_candidates_prefer_the_script_directory_then_the_session_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    candidates = decision_gate.log_candidates()
    assert candidates[0] == decision_gate.DEFAULT_LOG
    assert candidates[1] == tmp_path / decision_gate.LOG_DIRNAME / decision_gate.LOG_FILENAME
    assert len(candidates) == 2


def test_an_unwritable_log_still_surfaces_the_record_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # Losing the record silently once made a working gate look like a dead one.
    target = tmp_path / "as-a-file"
    target.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("DECISION_GATE_LOG", str(target / "decisions.jsonl"))
    decision_gate.append_log({"tool": "bash", "action": "allow"})
    assert '"action": "allow"' in capsys.readouterr().err
