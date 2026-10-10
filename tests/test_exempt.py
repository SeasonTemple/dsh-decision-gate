"""Tests for the path-scoped exemption: hooks/exempt.py, the `exempt` parameter
of policy.decide, and the wiring in decision_gate.main.

The exemption table here is the same one `src/parity.ts` asserts
against the TypeScript side, so the two implementations cannot drift apart
without one of these failing.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

import decision_gate
from exempt import DEFAULT_EXEMPT_PREFIXES, is_exempt, prefixes_from_env, write_targets
from policy import Policy, Signals, decide
from test_decision_gate import payload, response, run_main

CWD = "C:/example/app"


# --- the parser ---

@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("rm -rf .agent-scratch/", True),
        ("rm .agent-scratch/notes/a.txt .agent-scratch/notes/b.txt", True),
        ("shred .agent-scratch/old.key", True),
        ("mv .agent-scratch/a.tmp .agent-scratch/b.tmp", True),
        ("echo done > .agent-scratch/log.txt", True),
        ("echo done >> .agent-scratch/log.txt", True),
        ("truncate -s 0 .agent-scratch/log.txt", True),
        ("rm ./.agent-scratch/x", True),
        ("rm .agent-scratch/./x", True),
        ("rm .agent-scratch", True),
        ('rm ".agent-scratch\\x"', True),
        ('rm ".agent-scratch/x"', True),
        ("rm .agent-scratch\\x", False),
        ("rm -rf .agent-scratch/x 2>/dev/null", True),
        ("rm -rf .agent-scratch/x > /dev/null", True),
        ("rm -rf src 2>/dev/null", False),
        ("rm -rf .agent-scratch/x > out.txt", False),
        ("rm C:/example/app/.agent-scratch/x", True),
        ("rm .agent-scratch/a.txt src/app.py", False),
        ("rm -rf .agent-scratch/../src", False),
        ("rm .agent-scratchx", False),
        ("rm -rf .", False),
        ("rm -rf src", False),
        ("git clean -fdx", False),
        ("cat .env", False),
        ("rm /etc/hosts", False),
        ("rm ~/.agent-scratch/x", False),
        ("cd .agent-scratch && rm foo", False),
        ("rm 'unterminated", False),
        ("rm C:/example/other/x", False),
    ],
)
def test_only_a_fully_confined_command_is_exempt(command: str, expected: bool) -> None:
    cwd = CWD if command.startswith("rm C:/example/") else ""
    assert is_exempt(command, DEFAULT_EXEMPT_PREFIXES, cwd) is expected


def test_absolute_paths_are_resolved_against_the_session_cwd() -> None:
    inside = "rm C:/example/app/.agent-scratch/x"
    outside = "rm C:/example/other/x"
    assert is_exempt(inside, DEFAULT_EXEMPT_PREFIXES, CWD) is True
    assert is_exempt(outside, DEFAULT_EXEMPT_PREFIXES, CWD) is False
    # Without a cwd an absolute target can never be shown to be inside.
    assert is_exempt(inside, DEFAULT_EXEMPT_PREFIXES, "") is False


def test_a_prefix_boundary_is_not_a_prefix() -> None:
    assert write_targets("rm .agent-scratchx") == [".agent-scratchx"]
    assert is_exempt("rm .agent-scratchx", DEFAULT_EXEMPT_PREFIXES) is False


def test_custom_prefixes_replace_the_default() -> None:
    assert is_exempt("rm tmp/x", (".agent-scratch",)) is False
    assert is_exempt("rm tmp/x", ("tmp",)) is True


def test_no_prefixes_means_never_exempt() -> None:
    assert is_exempt("rm .agent-scratch/x", ()) is False


# --- the downgrade ---

def test_an_exempt_destructive_deny_is_downgraded_to_ask() -> None:
    decision = decide(Signals(0.01, 0.90, 0.02, 0.03, 0.08), Policy(), exempt=True)
    assert decision.action.value == "ask"
    assert decision.rule == "exempt_destructive"
    assert "0.90" in decision.reason


def test_a_non_exempt_destructive_deny_is_untouched() -> None:
    decision = decide(Signals(0.01, 0.90, 0.02, 0.03, 0.08), Policy(), exempt=False)
    assert decision.action.value == "deny"
    assert decision.rule == "destructive"


def test_exemption_never_downgrades_a_secret_deny() -> None:
    decision = decide(Signals(0.98, 0.02, 0.71, 0.02, 0.31), Policy(), exempt=True)
    assert decision.action.value == "deny"
    assert decision.rule == "secret_exposure"


def test_exemption_never_upgrades_an_allow_or_ask() -> None:
    safe = Signals(0.97, 0.01, 0.04, 0.02, 0.96)
    assert decide(safe, Policy(), exempt=True).action.value == "allow"
    unclear = Signals(0.02, 0.28, 0.08, 0.26, 0.63)
    assert decide(unclear, Policy(), exempt=True).action.value == "ask"


def test_default_policy_carries_the_default_prefixes() -> None:
    assert Policy().exempt_prefixes == DEFAULT_EXEMPT_PREFIXES


# --- configuration ---

def test_prefixes_from_env_parses_a_comma_separated_list() -> None:
    assert prefixes_from_env(".agent-scratch/, tmp/", DEFAULT_EXEMPT_PREFIXES) == (
        ".agent-scratch/",
        "tmp/",
    )


def test_prefixes_from_env_empty_disables_exemption() -> None:
    assert prefixes_from_env("", DEFAULT_EXEMPT_PREFIXES) == ()
    assert prefixes_from_env("  ", DEFAULT_EXEMPT_PREFIXES) == ()


def test_policy_from_env_reads_the_prefix_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECISION_GATE_EXEMPT_PREFIXES", "build,tmp")
    assert decision_gate.policy_from_env().exempt_prefixes == ("build", "tmp")


def test_policy_from_env_can_disable_exemption(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECISION_GATE_EXEMPT_PREFIXES", "")
    assert decision_gate.policy_from_env().exempt_prefixes == ()


# --- the hook end to end ---


def test_hook_asks_instead_of_denying_a_confined_deletion(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(decision_gate, "judge", lambda state, model: response(destructive=0.91))
    output = run_main(
        monkeypatch,
        json.dumps(payload(command="rm -rf .agent-scratch/old-logs")),
        capsys,
    )
    block = output["hookSpecificOutput"]
    assert block["permissionDecision"] == "ask"
    assert "0.91" in block["permissionDecisionReason"]


def test_hook_still_denies_a_deletion_that_leaves_the_prefix(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(decision_gate, "judge", lambda state, model: response(destructive=0.91))
    output = run_main(
        monkeypatch,
        json.dumps(payload(command="rm -rf .agent-scratch/../src")),
        capsys,
    )
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_still_denies_a_secret_command_inside_the_prefix(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(
        decision_gate, "judge", lambda state, model: response(secret_exposure=0.71)
    )
    output = run_main(
        monkeypatch,
        json.dumps(payload(command="cat .agent-scratch/keys.txt")),
        capsys,
    )
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_ignores_the_prefix_list_when_it_is_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setenv("DECISION_GATE_EXEMPT_PREFIXES", "")
    monkeypatch.setattr(decision_gate, "judge", lambda state, model: response(destructive=0.91))
    output = run_main(
        monkeypatch,
        json.dumps(payload(command="rm -rf .agent-scratch/old-logs")),
        capsys,
    )
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_exempt_flag_reaches_the_log(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(decision_gate, "judge", lambda state, model: response(destructive=0.91))
    run_main(
        monkeypatch,
        json.dumps(payload(command="rm -rf .agent-scratch/old-logs")),
        capsys,
    )
    # run_main pins DECISION_GATE_LOG to this temp file for every case.
    log = Path(tempfile.gettempdir()) / "decision_gate_tests.jsonl"
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert record["action"] == "ask"
    assert record["rule"] == "exempt_destructive"
    assert record["exempt"] is True
