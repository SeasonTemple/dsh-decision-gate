---
title: dsh-decision-gate
---

# dsh-decision-gate

A PreToolUse decision gate for **DSH** (DeepSeek Harness): before every shell tool
call (`bash`, `pwsh`, `terminal_*`) runs, the gate asks a judge five yes/no questions,
maps the answers through calibrated thresholds to **allow / ask / deny**, and appends
every decision to a JSONL log. Swappable judge backend, path-scoped exemption,
pre-authorized list for approved irreversible steps.

## Docs

- [Setup and verification guide (简体中文)](decision-gate-setup.html)
- [Release notes](release-notes/)
- [Changelog (GitHub)](https://github.com/SeasonTemple/dsh-decision-gate/blob/main/CHANGELOG.md)
- [README — English](https://github.com/SeasonTemple/dsh-decision-gate/blob/main/README.md)
- [README — 简体中文](https://github.com/SeasonTemple/dsh-decision-gate/blob/main/README.zh.md)

## Install

```bash
dsh plugin add SeasonTemple/dsh-decision-gate
```

## Verify

```bash
python -m pytest tests -q
node tests/functional.mjs
```
