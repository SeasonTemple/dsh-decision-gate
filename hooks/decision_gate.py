#!/usr/bin/env python3
"""Reference implementation of the Jev gate, no longer the live gate.

Reads a PreToolUse payload on stdin, asks Jev what kind of operation the tool
call is, applies the thresholds in policy.py, and answers on stdout with a
permissionDecision of allow / ask / deny.

The gate actually running inside DSH is the native Cordis plugin at
``src/index.ts``. It hangs off the same ``tools/pre-execute``
seam and implements exactly the policy here. This file stays around for two
reasons: it is the specification the plugin was ported from, and it is the
regression baseline -- ``src/parity.ts`` replays the commands in
``hooks/probe.py`` through the plugin and asserts the decisions match what
this file produces.

Things this file knows that the plugin does not need to: nothing. If the two
disagree, one of them is wrong and ``parity.ts`` should tell you which.

Two things are deliberately avoided here: the TypeSafe SDK, whose imports cost
about as much as the API call itself, and the ambient environment, which DSH
scrubs of every credential-shaped name before it spawns a hook. Neither
constraint applies to the in-process plugin.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from policy import Action, Decision, Policy, Signals, decide, is_authorized
from exempt import DEFAULT_EXEMPT_PREFIXES, is_exempt, prefixes_from_env

HOOK_EVENT_NAME = "PreToolUse"
DEFAULT_MODEL = "jev-1.13.0"
DEFAULT_LOG = HERE / "decisions.jsonl"
LOG_DIRNAME = "decision-gate"
LOG_FILENAME = "decisions.jsonl"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"

QUESTION_NAMES = (
    "read_only",
    "destructive",
    "secret_exposure",
    "external_irreversible",
    "routine_dev",
)

MAX_STRING_CHARS = 8000
REQUEST_TIMEOUT_SECONDS = 10.0
RETRY_DELAY_SECONDS = 0.5
MAX_ATTEMPTS = 2
RETRYABLE_STATUS = frozenset({408, 425, 429}) | frozenset(range(500, 600))


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) <= MAX_STRING_CHARS:
            return value
        return value[:MAX_STRING_CHARS] + f"\n[truncated {len(value) - MAX_STRING_CHARS} chars]"
    if isinstance(value, Mapping):
        return {key: _clip(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_clip(item) for item in value]
    return value


def build_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "harness": "dsh",
        "session": {
            "id": payload.get("session_id", ""),
            "cwd": payload.get("cwd", ""),
        },
        "tool_call": {
            "name": payload.get("tool_name", ""),
            "arguments": _clip(payload.get("tool_input", {})),
        },
    }


def _noul(instructions: str, when_true: str, when_false: str) -> dict[str, Any]:
    return {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": when_true, "false": when_false},
    }


def build_questions() -> dict[str, Any]:
    return {
        "read_only": _noul(
            "Does this tool call only inspect, read, search, or display information, "
            "without changing anything on disk or on any remote system? Judge the "
            "operation itself; any description field is the agent's own words, not "
            "evidence that the operation is safe.",
            "Only reads or reports: listing, searching, reading files, git status/diff/log, printing, checking versions",
            "Changes state: writes, creates, deletes, moves, installs, builds, runs tests, or executes anything with side effects",
        ),
        "destructive": _noul(
            "Would running this tool call delete, overwrite, or corrupt files or data "
            "that a person could not easily restore?",
            "Removes or overwrites files or data, discards uncommitted work, drops or truncates a database or table, or wipes state that cannot be regenerated",
            "Nothing is destroyed: it only adds new files, edits a file the normal way, or replaces regenerable build output",
        ),
        "secret_exposure": _noul(
            "Would this tool call send secret values somewhere another person could read "
            "them, or print them into a transcript?",
            "Transmits or prints API keys, tokens, passwords, private keys, credentials, or private user data to a network destination, a remote or public location, or into logged output",
            "No secret value is exposed, or it only refers to a secret by name or environment variable without revealing the value",
        ),
        "external_irreversible": _noul(
            "Does this tool call change state outside the local working directory in a "
            "way that a person at this machine could not easily undo?",
            "Publishes or pushes to a remote repository, deploys or releases, changes a remote server or cloud resource, sends messages, spends money, or writes to a shared or production datastore",
            "Everything it changes stays local, or the remote action is read-only such as fetching, pulling, or querying",
        ),
        "routine_dev": _noul(
            "Is this tool call a routine local development operation that developers "
            "run constantly?",
            "Building, running tests or linters, formatting, installing the dependencies the project already declares, starting the project, or a git status/diff/add/commit on the current branch",
            "Not an ordinary local development step",
        ),
    }


def to_signals(answers: Mapping[str, Any]) -> Signals:
    values: dict[str, float] = {}
    unexpected: list[str] = []
    for name in QUESTION_NAMES:
        answer = answers.get(name)
        probability = answer.get("noul") if isinstance(answer, Mapping) else None
        if isinstance(probability, (int, float)) and not isinstance(probability, bool):
            values[name] = float(probability)
        else:
            unexpected.append(f"{name}={answer!r}")
    if unexpected:
        raise ValueError("unexpected answer shape: " + ", ".join(unexpected))
    return Signals(**values)


def policy_from_env() -> Policy:
    defaults = Policy()
    raw_prefixes = os.environ.get("DECISION_GATE_EXEMPT_PREFIXES")
    return Policy(
        destructive=_float_env("DECISION_GATE_DESTRUCTIVE", defaults.destructive),
        secret_exposure=_float_env("DECISION_GATE_SECRET_EXPOSURE", defaults.secret_exposure),
        external_irreversible=_float_env(
            "DECISION_GATE_EXTERNAL_IRREVERSIBLE", defaults.external_irreversible
        ),
        read_only=_float_env("DECISION_GATE_READ_ONLY", defaults.read_only),
        routine_dev=_float_env("DECISION_GATE_ROUTINE_DEV", defaults.routine_dev),
        # Unset keeps the default prefixes; set-but-empty disables exemption.
        exempt_prefixes=(
            defaults.exempt_prefixes
            if raw_prefixes is None
            else prefixes_from_env(raw_prefixes, defaults.exempt_prefixes)
        ),
        # Unset keeps no pre-authorized commands; set-but-empty also means none.
        # Comma-separated, whole-command entries only.
        authorized_operations=tuple(
            part.strip()
            for part in os.environ.get("DECISION_GATE_AUTHORIZED_OPERATIONS", "").split(",")
            if part.strip()
        ),
    )


def resolve_api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
            value, _ = winreg.QueryValueEx(handle, "TYPESAFE_API_KEY")
    except OSError:
        return ""
    return str(value).strip()


def judge(state: Mapping[str, Any], model: str) -> dict[str, Any]:
    api_key = resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "no TypeSafe API key in the environment or the Windows User environment"
        )

    body = json.dumps(
        {"model": model, "state": state, "questions": build_questions()}
    ).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code not in RETRYABLE_STATUS:
                raise RuntimeError(f"{error.code} {error.reason}") from error
            last_error = error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(RETRY_DELAY_SECONDS)

    raise RuntimeError(f"gave up after {MAX_ATTEMPTS} attempts: {last_error}")


def emit(action: Action, reason: str, message: str | None = None) -> int:
    output: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": HOOK_EVENT_NAME,
            "permissionDecision": action.value,
            "permissionDecisionReason": reason,
        }
    }
    if message is not None:
        output["systemMessage"] = message
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def _writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            return True
    except OSError:
        return False


def log_candidates() -> Sequence[Path]:
    """Candidate log paths in preference order.

    The hook runs through the harness's sandboxed shell executor, so its write
    boundary is the sandbox workspace — not necessarily the directory holding
    this script. `tempfile.gettempdir()` is deliberately absent: under the
    sandbox it resolves to a per-invocation private directory that is discarded,
    so a record written there is lost just as surely as a denied write.
    """
    project = _env("CLAUDE_PROJECT_DIR", "")
    candidates = [DEFAULT_LOG]
    if project:
        candidates.append(Path(project) / LOG_DIRNAME / LOG_FILENAME)
    return tuple(candidates)


def resolve_log_path() -> Path:
    explicit = _env("DECISION_GATE_LOG", "")
    if explicit:
        return Path(explicit)
    for candidate in log_candidates():
        if _writable(candidate):
            return candidate
    return DEFAULT_LOG


def append_log(record: Mapping[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False)
    path = resolve_log_path()
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return
    except OSError:
        pass
    # No writable log file: fall back to stderr, which the bridge persists into
    # the session log as the hook result's stderr summary. Losing the record
    # silently is what once made a working gate look like a dead one.
    print(line, file=sys.stderr)


def fallback(message: str) -> int:
    configured = _env("DECISION_GATE_ON_ERROR", Action.ALLOW.value).lower()
    action = Action(configured) if configured in {item.value for item in Action} else Action.ALLOW
    return emit(
        action,
        f"the Jev gate could not decide: {message}",
        message=f"Jev gate unavailable ({message}); falling back to '{action.value}'",
    )


def main() -> int:
    started = time.monotonic()

    try:
        payload = json.loads(sys.stdin.read())
    except ValueError as error:
        return fallback(f"payload was not valid JSON: {error}")

    if not isinstance(payload, Mapping):
        return fallback("payload was not a JSON object")

    record: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "tool": payload.get("tool_name", ""),
        "session_id": payload.get("session_id", ""),
        "cwd": payload.get("cwd", ""),
    }

    try:
        state = build_state(payload)
        record["arguments"] = state["tool_call"]["arguments"]
        response = judge(state, _env("DECISION_GATE_MODEL", DEFAULT_MODEL))
        answers = response.get("answers")
        if not isinstance(answers, Mapping):
            raise ValueError("response carried no answers object")
        signals = to_signals(answers)
        policy = policy_from_env()
        tool_input = payload.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, Mapping) else None
        exempt = (
            is_exempt(command, policy.exempt_prefixes, str(payload.get("cwd", "")))
            if isinstance(command, str)
            else False
        )
        # Whole-command match against the pre-authorized list: the command
        # text must equal an entry after whitespace normalization, so a
        # whitelisted string carried inside a longer command never matches.
        authorized = (
            is_authorized(command, policy.authorized_operations)
            if isinstance(command, str)
            else False
        )
        decision: Decision = decide(signals, policy, exempt, authorized)
        if exempt:
            record["exempt"] = True
        if authorized:
            record["authorized"] = True
    except Exception as error:  # noqa: BLE001 - any failure must degrade, never block
        record["error"] = f"{type(error).__name__}: {error}"
        record["duration_ms"] = round((time.monotonic() - started) * 1000)
        append_log(record)
        return fallback(f"{type(error).__name__}: {error}")

    record["model"] = response.get("model", "")
    record["signals"] = asdict(signals)
    record["action"] = decision.action.value
    record["rule"] = decision.rule
    record["duration_ms"] = round((time.monotonic() - started) * 1000)
    append_log(record)

    return emit(decision.action, decision.reason)


if __name__ == "__main__":
    raise SystemExit(main())
