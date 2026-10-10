from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from enum import Enum
import re
from exempt import DEFAULT_EXEMPT_PREFIXES


class Action(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class Signals:
    read_only: float
    destructive: float
    secret_exposure: float
    external_irreversible: float
    routine_dev: float


@dataclass(frozen=True)
class Policy:
    destructive: float = 0.50
    secret_exposure: float = 0.50
    external_irreversible: float = 0.50
    read_only: float = 0.80
    routine_dev: float = 0.75
    # Path prefixes where a destructive verdict is downgraded to ask instead of
    # denied. See hooks/exempt.py for why this exists at all.
    exempt_prefixes: tuple[str, ...] = field(default=DEFAULT_EXEMPT_PREFIXES)
    # Exact commands whose external-irreversible ask is downgraded to allow.
    # See hooks/policy.py::decide for why this cannot launder anything.
    authorized_operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    action: Action
    rule: str
    reason: str


def decide(
    signals: Signals,
    policy: Policy = Policy(),
    exempt: bool = False,
    authorized: bool = False,
) -> Decision:
    if signals.secret_exposure >= policy.secret_exposure:
        return Decision(
            Action.DENY,
            "secret_exposure",
            f"looks like it would expose secrets (p={signals.secret_exposure:.2f})",
        )
    if signals.destructive >= policy.destructive:
        if exempt:
            # Every path this command writes to is inside an exempt prefix, so
            # the data at risk is scratch data. A person should still see it,
            # but the agent must not be permanently locked out of its own
            # scratch space -- a deny cannot be overridden from inside the
            # session. Secret exposure is never downgraded, and neither is a
            # destructive command with even one target outside the prefix.
            return Decision(
                Action.ASK,
                "exempt_destructive",
                f"destructive but confined to an exempt path (p={signals.destructive:.2f}); a person should still see it",
            )
        return Decision(
            Action.DENY,
            "destructive",
            f"looks like it would destroy data that cannot be restored (p={signals.destructive:.2f})",
        )
    if signals.external_irreversible >= policy.external_irreversible:
        # A pre-authorized command skips only this one question. The checks
        # above have already run, so a command that also exposes secrets or
        # destroys data was denied before reaching here -- the whitelist
        # cannot launder it, and a whitelisted string that is not the whole
        # command simply never matches.
        if authorized:
            return Decision(
                Action.ALLOW,
                "authorized_external",
                f"changes state outside this machine, but the command is pre-authorized (p={signals.external_irreversible:.2f})",
            )
        return Decision(
            Action.ASK,
            "external_irreversible",
            f"looks like it changes state outside this machine (p={signals.external_irreversible:.2f})",
        )
    if signals.read_only >= policy.read_only:
        return Decision(
            Action.ALLOW,
            "read_only",
            f"reads only (p={signals.read_only:.2f})",
        )
    if signals.routine_dev >= policy.routine_dev:
        return Decision(
            Action.ALLOW,
            "routine_dev",
            f"routine local development step (p={signals.routine_dev:.2f})",
        )
    return Decision(
        Action.ASK,
        "unclear",
        "not clearly safe or dangerous, so a person should look",
    )


def is_authorized(command: str, entries: tuple[str, ...] | list[str]) -> bool:
    """Statement-level match against the pre-authorized list.

    Not whole-command equality: a shell call always arrives wrapped --
    `Set-Location`, `git -C`, a trailing `| Select-Object` -- and the person
    pre-authorizing `git push origin main` cannot predict that wrapper, so
    equality made the list unmatchable in practice. Split on statement
    separators and let any complete statement stand for itself.

    Safety does not rest on this: `secret_exposure` and `destructive` are still
    judged on the whole command first, and the gate documents that it is not a
    defence against an adversarial agent. Mirrors `isAuthorized` in
    src/index.ts.
    """
    if not entries:
        return False
    statements = [
        " ".join(part.split())
        for part in re.split(r"\s*(?:;|&&|\|\||\n)\s*", command)
        if part.strip()
    ]
    # A statement arrives with its own redirections and pipes attached
    # (`git push origin main 2>&1 | Select-Object -Last 3`); drop those tails so
    # the command itself is what gets compared.
    statements = [
        # Pipe first, then strip the redirection tail off what remains: in
        # `git push origin main 2>&1 | Select-Object -Last 3` the redirection sits
        # before the pipe, so stripping the tail first leaves `... 2>&1` behind.
        statement.split("|")[0].strip()
        for statement in statements
    ]
    statements = [
        re.sub(r"\s*\d*>>?\s*\S*\s*$", "", statement)
        for statement in statements
    ]
    # Drop the tokens that only say where to run, not what to run.
    statements = [_strip_locators(statement) for statement in statements]
    wanted = [_strip_locators(entry) for entry in entries]
    return any(statement in wanted for statement in statements)


def _strip_locators(statement: str) -> str:
    """Remove the tokens that only say *where* to run, not *what* to run.

    `cd /repo`, `Set-Location 'E:/x'` and `git -C /repo push` all name the same
    action, and a person pre-authorizing `git push origin main` cannot know which
    wrapper a shell call will arrive in. Mirrors `stripLocators` in
    src/index.ts.
    """
    words = statement.split()
    out: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        if not out and word in ("cd", "Set-Location", "sl"):
            index += 2
            continue
        if word in ("-C", "--git-dir", "--work-tree"):
            index += 2
            continue
        out.append(word)
        index += 1
    return " ".join(out)
