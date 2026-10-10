"""Path-scoped exemption for the destructive rule.

The gate has no notion of context, so `rm scratch-note.txt` and `rm -rf /`
score the same: destructive, deny, no approval channel. That leaves the agent
permanently unable to clean up its own scratch files, because a deny cannot be
overridden from inside the session.

This module answers one question: does every path this command would write to
live inside an exempt prefix? When the answer is yes, `decide` downgrades a
destructive deny to an ask -- a person still sees it, but the agent is not
locked out. Nothing is ever upgraded: secret-exposure denies are never
downgraded, and a single non-exempt target disqualifies the whole command.

The parser is deliberately shallow. It knows a handful of write verbs and
redirection, and fails closed on everything else: an unparseable command, an
unknown verb, or an absolute path outside the session cwd is simply not
exempt, which keeps the original deny. Shell state (`cd` into the exempt
directory first) is not tracked -- again, that only ever fails closed.

`src/index.ts` mirrors this file token for token;
`src/parity.ts` and `tests/test_exempt.py` hold both sides to
the same expectations.
"""

from __future__ import annotations

import posixpath
import re
import shlex
from typing import Sequence

DEFAULT_EXEMPT_PREFIXES: tuple[str, ...] = (".agent-scratch",)

# A Windows drive path ("C:/example/x") is absolute even though posixpath disagrees.
_DRIVE = re.compile(r"^[A-Za-z]:")

# Verbs whose non-flag arguments are paths the command writes to. Kept short
# on purpose: a verb not listed here yields no targets, and a command with no
# targets is never exempt.
WRITE_VERBS = frozenset({"rm", "shred", "truncate", "mv"})

# Verbs where only the final argument is a write target (the destination).
# Everything before it is a source being read, which cannot destroy anything.
DESTINATION_ONLY_VERBS = frozenset({"cp"})

# Flags that consume the following token as a value, so it is not a path.
VALUE_FLAGS = frozenset({"-s"})

REDIRECT_TOKENS = frozenset({">", ">>"})

# The null device absorbs whatever is written to it; it is never data at risk,
# so a `2>/dev/null` on an otherwise exempt command must not break exemption.
NULL_DEVICES = frozenset({"/dev/null", "nul"})

_PUNCTUATION = "(){};&|<>"

# A file-descriptor-prefixed redirect, e.g. `2>` or `1>>`.
_FD_REDIRECT = re.compile(r"\d+>>?")


def _is_operator(token: str) -> bool:
    if token != "" and all(character in _PUNCTUATION for character in token):
        return True
    # A merged fd redirect ("2>") ends a verb's argument list like any operator.
    return _FD_REDIRECT.fullmatch(token) is not None


def _tokenize(command: str) -> list[str] | None:
    """Split like a POSIX shell would, or None if the command does not parse."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _targets_of(verb: str, args: Sequence[str]) -> list[str]:
    targets: list[str] = []
    skip_next = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg.startswith("-"):
            if arg in VALUE_FLAGS:
                skip_next = True
            continue
        if verb in DESTINATION_ONLY_VERBS and index != len(args) - 1:
            continue
        targets.append(arg)
    return targets


def _merge_fd_redirects(tokens: list[str]) -> list[str]:
    """Join `2 > /dev/null` into `2>`, so the fd number is not read as a path."""
    merged: list[str] = []
    index = 0
    while index < len(tokens):
        if (
            index + 1 < len(tokens)
            and tokens[index].isdigit()
            and tokens[index + 1] in REDIRECT_TOKENS
        ):
            merged.append(tokens[index] + tokens[index + 1])
            index += 2
            continue
        merged.append(tokens[index])
        index += 1
    return merged


def write_targets(command: str) -> list[str]:
    """Every path the command would create, overwrite, move, or delete."""
    tokens = _tokenize(command)
    if tokens is None:
        return []
    tokens = _merge_fd_redirects(tokens)
    targets: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in WRITE_VERBS:
            index += 1
            args: list[str] = []
            while index < len(tokens) and not _is_operator(tokens[index]):
                args.append(tokens[index])
                index += 1
            targets.extend(_targets_of(token, args))
            continue
        if token in REDIRECT_TOKENS or _FD_REDIRECT.fullmatch(token):
            index += 1
            if index < len(tokens) and not _is_operator(tokens[index]):
                target = tokens[index]
                if target.lower() not in NULL_DEVICES:
                    targets.append(target)
                index += 1
            continue
        index += 1
    return targets


def _repo_relative(target: str, cwd: str) -> str | None:
    """Normalize a target to a repo-relative path, or None if it escapes."""
    path = target.replace("\\", "/").strip()
    if path == "" or path.startswith("~"):
        return None
    # A Windows drive path is absolute even though posixpath does not think so.
    if posixpath.isabs(path) or _DRIVE.match(path):
        base = cwd.replace("\\", "/").rstrip("/")
        if base == "":
            return None
        normalized = posixpath.normpath(path)
        if normalized == base:
            return "."
        prefix = base + "/"
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
        return None
    return posixpath.normpath(path)


def _under_prefix(relative: str, prefix: str) -> bool:
    normalized = prefix.replace("\\", "/").strip().rstrip("/")
    if normalized == "":
        return False
    return relative == normalized or relative.startswith(normalized + "/")


def is_exempt(command: str, prefixes: Sequence[str], cwd: str = "") -> bool:
    """True only when every write target of the command sits inside a prefix."""
    targets = write_targets(command)
    if not targets:
        return False
    for target in targets:
        relative = _repo_relative(target, cwd)
        if relative is None:
            return False
        if not any(_under_prefix(relative, prefix) for prefix in prefixes):
            return False
    return True


def prefixes_from_env(raw: str, default: Sequence[str] = DEFAULT_EXEMPT_PREFIXES) -> tuple[str, ...]:
    """Parse a comma-separated prefix list; an empty value disables exemption."""
    if raw.strip() == "":
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip()) or tuple(default)
