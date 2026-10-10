from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import analyze
from policy import Action, Policy, Signals

FIELDS = analyze.THRESHOLDS


def record(command: str, **values: float) -> dict[str, Any]:
    signals = dict.fromkeys(FIELDS, 0.0)
    signals.update(values)
    return {"tool": "bash", "arguments": {"command": command}, "signals": signals, "model": "jev-1.13.0"}


def write_log(path: Path, records: list[dict[str, Any]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_splits_failures_from_judged(tmp_path: Path) -> None:
    log = write_log(
        tmp_path / "d.jsonl",
        [
            record("git status", read_only=0.97),
            {"tool": "bash", "at": "t", "error": "RuntimeError: no key"},
        ],
    )
    judged, failed = analyze.load(log)
    assert len(judged) == 1
    assert len(failed) == 1
    assert "no key" in failed[0]["error"]


def test_load_ignores_blank_lines(tmp_path: Path) -> None:
    log = tmp_path / "d.jsonl"
    log.write_text(
        json.dumps(record("ls", read_only=0.9)) + "\n\n\n", encoding="utf-8"
    )
    judged, _ = analyze.load(log)
    assert len(judged) == 1


def test_load_treats_a_record_without_signals_as_a_failure(tmp_path: Path) -> None:
    log = write_log(tmp_path / "d.jsonl", [{"tool": "bash", "at": "t"}])
    judged, failed = analyze.load(log)
    assert judged == []
    assert len(failed) == 1


def test_label_prefers_the_command() -> None:
    assert analyze.label(record("git status --short", read_only=0.9)) == "git status --short"


def test_label_falls_back_to_the_path_then_to_json() -> None:
    assert analyze.label({"arguments": {"path": "src/a.py"}}) == "src/a.py"
    assert analyze.label({"arguments": {"x": 1}}) == '{"x": 1}'


def test_label_collapses_newlines_and_truncates() -> None:
    text = analyze.label({"arguments": {"command": "echo a\n" + "b" * 200}})
    assert "\n" not in text
    assert len(text) <= 58


def test_replay_follows_the_policy_it_is_given() -> None:
    records = [record("rm -rf build/", destructive=0.41, routine_dev=0.74)]
    assert analyze.replay(records, Policy()) == [Action.ASK.value]
    assert analyze.replay(records, Policy(routine_dev=0.70)) == [Action.ALLOW.value]
    assert analyze.replay(records, Policy(destructive=0.40)) == [Action.DENY.value]


def test_margin_to_flip_finds_the_field_and_distance() -> None:
    records = [record("rm -rf build/", destructive=0.41, routine_dev=0.74)]
    assert analyze.margin_to_flip(records[0], Policy()) == ("routine_dev", pytest.approx(0.01))


def test_margin_to_flip_is_none_when_the_decision_is_settled() -> None:
    records = [record("git status", read_only=0.97)]
    assert analyze.margin_to_flip(records[0], Policy()) is None


def test_margin_to_flip_ignores_a_degenerate_zero_threshold() -> None:
    settled = record("git status", read_only=0.97)
    assert settled["signals"]["secret_exposure"] == 0.0
    assert analyze.margin_to_flip(settled, Policy()) is None


def test_margin_to_flip_reports_a_plausible_shift() -> None:
    records = [record("npm install", read_only=0.03, routine_dev=0.72)]
    margin = analyze.margin_to_flip(records[0], Policy())
    assert margin is not None
    field, distance = margin
    assert field == "routine_dev"
    assert distance <= analyze.MAX_PLAUSIBLE_SHIFT


def test_margin_to_flip_ignores_a_threshold_it_cannot_reach() -> None:
    records = [record("git push", external_irreversible=0.93, routine_dev=0.30)]
    margin = analyze.margin_to_flip(records[0], Policy())
    assert margin is None or margin[1] > 0.30


def test_signals_of_round_trips_a_record() -> None:
    item = record("ls", read_only=0.9, destructive=0.1)
    assert analyze.signals_of(item) == Signals(**item["signals"])


def test_report_sweep_shows_a_flip_when_the_threshold_moves(capsys: Any) -> None:
    records = [record("rm -rf build/", destructive=0.41, routine_dev=0.74)]
    analyze.report_sweep(records)
    out = capsys.readouterr().out
    assert "routine_dev" in out
    assert "rm -rf build/" in out
    assert "ask→allow" in out


def test_report_sweep_marks_the_current_value(capsys: Any) -> None:
    analyze.report_sweep([record("ls", read_only=0.9)])
    assert "←当前" in capsys.readouterr().out


def test_report_summary_counts_every_action(capsys: Any) -> None:
    records = [
        record("git status", read_only=0.97),
        record("git push", external_irreversible=0.93),
        record("rm -rf src", destructive=0.91),
    ]
    analyze.report_summary(records, [])
    out = capsys.readouterr().out
    assert "allow" in out and "ask" in out and "deny" in out


def test_report_summary_warns_when_versions_are_mixed(capsys: Any) -> None:
    records = [record("a", read_only=0.9), {**record("b", read_only=0.9), "model": "jev-1.14.0"}]
    analyze.report_summary(records, [])
    assert "不止一个模型版本" in capsys.readouterr().out


def test_report_summary_says_so_when_the_log_is_empty(capsys: Any) -> None:
    analyze.report_summary([], [])
    assert "还没有可用信号" in capsys.readouterr().out


def test_main_reports_a_missing_log(tmp_path: Path, capsys: Any) -> None:
    assert analyze.main([str(tmp_path / "nope.jsonl")]) == 1
    assert "找不到日志" in capsys.readouterr().out


def test_main_reads_the_log_it_is_given(tmp_path: Path, capsys: Any) -> None:
    log = write_log(tmp_path / "d.jsonl", [record("git status", read_only=0.97)])
    assert analyze.main([str(log)]) == 0
    assert "决策总数 : 1" in capsys.readouterr().out
