from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

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
    """Whole-command match against the pre-authorized list.

    The command text must equal an entry after whitespace normalization, so a
    whitelisted string carried inside a longer command (`curl ... && git push`)
    never matches -- the surrounding text keeps its own verdict. Mirrors
    `isAuthorized` in src/index.ts.
    """
    if not entries:
        return False
    normalized = " ".join(command.split())
    return any(" ".join(entry.split()) == normalized for entry in entries)
