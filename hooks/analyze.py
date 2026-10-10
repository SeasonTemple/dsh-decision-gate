#!/usr/bin/env python3
"""Read hooks/decisions.jsonl and report where the thresholds should sit.

The log records every signal Jev returned, so a threshold can be re-decided
offline without calling the API again. Nothing here needs a key or a network.

    python hooks/analyze.py                  # summary of the default log
    python hooks/analyze.py other.jsonl
    python hooks/analyze.py --sweep          # add the threshold sweep
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from decision_gate import DEFAULT_LOG, resolve_log_path
from policy import Action, Policy, Signals, decide

FRAGILE_MARGIN = 0.05
MAX_PLAUSIBLE_SHIFT = 0.25
SWEEP_DELTAS = (-0.20, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20)

THRESHOLDS = (
    "secret_exposure",
    "destructive",
    "external_irreversible",
    "read_only",
    "routine_dev",
)


def load(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    judged: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        (failed if "error" in record or "signals" not in record else judged).append(record)
    return judged, failed


def label(record: Mapping[str, Any]) -> str:
    arguments = record.get("arguments") or {}
    text = arguments.get("command") or arguments.get("path") or json.dumps(arguments, ensure_ascii=False)
    return " ".join(str(text).split())[:58]


def signals_of(record: Mapping[str, Any]) -> Signals:
    return Signals(**record["signals"])


def replay(records: Sequence[Mapping[str, Any]], policy: Policy) -> list[str]:
    return [decide(signals_of(record), policy).action.value for record in records]


def rule_of(record: Mapping[str, Any], policy: Policy) -> str:
    return decide(signals_of(record), policy).rule


def margin_to_flip(record: Mapping[str, Any], policy: Policy) -> tuple[str, float] | None:
    """How far the nearest threshold would have to move to change this decision.

    Returns None when no threshold can be shifted by a plausible amount, which
    covers both settled decisions and the degenerate 'set this knob to zero'
    answer that every reading satisfies.
    """
    base = decide(signals_of(record), policy).action
    signals = record["signals"]
    closest: tuple[str, float] | None = None
    for field in THRESHOLDS:
        threshold = getattr(policy, field)
        distance = abs(signals[field] - threshold)
        if distance > MAX_PLAUSIBLE_SHIFT:
            continue
        for direction in (distance, -distance):
            candidate = replace(policy, **{field: round(threshold + direction, 4)})
            if decide(signals_of(record), candidate).action is not base:
                if closest is None or distance < closest[1]:
                    closest = (field, distance)
                break
    return closest


def report_summary(judged: Sequence[Mapping[str, Any]], failed: Sequence[Mapping[str, Any]]) -> None:
    print(f"决策总数 : {len(judged) + len(failed)}  （可用信号 {len(judged)}，失败 {len(failed)}）")

    if failed:
        print("\n失败记录（走了兜底）:")
        for record in failed[-5:]:
            print(f"  {record.get('at', '')[:19]}  {str(record.get('error'))[:70]}")

    if not judged:
        print("\n还没有可用信号。先用一阵 DSH，日志攒起来再看。")
        return

    policy = Policy()
    actions = replay(judged, policy)
    print("\n动作分布:")
    for action in Action:
        count = actions.count(action.value)
        share = count / len(actions) * 100
        print(f"  {action.value:<6} {count:>5}  ({share:4.1f}%)")

    print("\n命中规则:")
    rules: dict[str, int] = {}
    for record in judged:
        rules[rule_of(record, policy)] = rules.get(rule_of(record, policy), 0) + 1
    for rule, count in sorted(rules.items(), key=lambda item: -item[1]):
        print(f"  {rule:<24} {count:>5}")

    durations = [record.get("duration_ms", 0) for record in judged]
    if durations:
        durations.sort()
        print(
            f"\n延迟     : p50 {statistics.median(durations):.0f} ms"
            f"   p95 {durations[int(len(durations) * 0.95)]:.0f} ms"
            f"   max {durations[-1]:.0f} ms"
        )

    models: dict[str, int] = {}
    for record in judged:
        model = record.get("model") or "unknown"
        models[model] = models.get(model, 0) + 1
    if len(models) > 1:
        print("\n⚠ 用了不止一个模型版本，阈值会随版本漂移:")
        for model, count in models.items():
            print(f"  {model:<20} {count:>5}")
    elif models:
        print(f"模型     : {next(iter(models))}")


def report_fragile(judged: Sequence[Mapping[str, Any]], policy: Policy) -> None:
    fragile = []
    for record in judged:
        margin = margin_to_flip(record, policy)
        if margin is not None and margin[1] <= FRAGILE_MARGIN:
            fragile.append((margin[1], margin[0], record))

    print(f"\n贴近阈值的决策（±{FRAGILE_MARGIN} 内，会因微调而翻转）: {len(fragile)} 条")
    for distance, field, record in sorted(fragile)[:15]:
        action = decide(signals_of(record), policy).action.value
        value = record["signals"][field]
        print(
            f"  {field:<22} {value:.2f} vs {getattr(policy, field):.2f}"
            f"  ({distance:.3f})  {action:<6} {label(record)}"
        )
    if len(fragile) > 15:
        print(f"  … 另有 {len(fragile) - 15} 条")


def report_sweep(judged: Sequence[Mapping[str, Any]]) -> None:
    base_policy = Policy()
    base_actions = replay(judged, base_policy)

    for field in THRESHOLDS:
        current = getattr(base_policy, field)
        print(f"\n{'=' * 84}\n{field}   当前 {current:.2f}\n{'=' * 84}")
        print(f"  {'阈值':<7} {'allow':>6} {'ask':>6} {'deny':>6}   相对当前的翻转")

        for delta in SWEEP_DELTAS:
            value = round(current + delta, 3)
            if value <= 0 or value > 1:
                continue
            policy = replace(base_policy, **{field: value})
            actions = replay(judged, policy)
            counts = [actions.count(action.value) for action in Action]
            flips = [
                f"{label(record)} ({old}→{new})"
                for record, old, new in zip(judged, base_actions, actions)
                if old != new
            ]
            marker = "  ←当前" if delta == 0.0 else ""
            detail = "" if not flips else "  " + "; ".join(flips[:3])
            if len(flips) > 3:
                detail += f" … 等 {len(flips)} 条"
            print(
                f"  {value:<7.2f} {counts[0]:>6} {counts[1]:>6} {counts[2]:>6}{marker}{detail}"
            )


def main(argv: list[str]) -> int:
    args = [item for item in argv if not item.startswith("--")]
    sweep = "--sweep" in argv

    path = Path(args[0]) if args else resolve_log_path()
    if not path.exists():
        print(f"找不到日志 {path}。先让 DSH 跑一阵，或指定别的路径。")
        return 1

    judged, failed = load(path)
    report_summary(judged, failed)

    if judged:
        policy = Policy()
        report_fragile(judged, policy)
        if sweep:
            report_sweep(judged)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
