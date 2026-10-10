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


@dataclass(frozen=True)
class Decision:
    action: Action
    rule: str
    reason: str


def decide(signals: Signals, policy: Policy = Policy(), exempt: bool = False) -> Decision:
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
