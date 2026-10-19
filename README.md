<div align="center">

# dsh-decision-gate

**A PreToolUse decision gate for DSH — asks five yes/no questions about every shell tool call, then allows, asks, or denies it, with a swappable judge backend.**

<sub>Calibrated thresholds, a path-scoped exemption, and a JSONL decision log — because a gate that cannot reach its judge must never become the thing that blocks the harness. <a href="#how-it-works">How it works →</a></sub>

[![CI](https://github.com/SeasonTemple/dsh-decision-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/SeasonTemple/dsh-decision-gate/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/SeasonTemple/dsh-decision-gate)](https://github.com/SeasonTemple/dsh-decision-gate/releases)
[![Docs](https://img.shields.io/badge/docs-github%20pages-blue)](https://seasontemple.github.io/dsh-decision-gate/)
[![License: BUSL-1.1](https://img.shields.io/badge/License-BUSL_1.1-blue.svg)](LICENSE)
[![Node >=20](https://img.shields.io/badge/node-%3E%3D20-brightgreen.svg)](https://nodejs.org/)

[English](README.md) · [简体中文](README.zh.md) · [How it works](#how-it-works) · [Judge backends](#judge-backends) · [Install](#install) · [Verify](#verify) · [Changelog](CHANGELOG.md)

</div>

---

A DSH (DeepSeek Harness) PreToolUse gate. Before every shell tool call
(`bash`, `pwsh`, `terminal_*`) runs, the plugin asks a judge five yes/no
questions about the operation, maps the answers through fixed thresholds to
**allow / ask / deny**, and appends every decision to a JSONL log so the
thresholds can be calibrated later against real data.

The gate has no power to escalate anything. Its one job is to stop the session
from silently doing something a person would not have wanted — and to stay out
of the way otherwise.

**Version compatibility.** Verified against DeepSeek Harness
`0.2.1-rc.2` (the desktop RC): the in-process gate rides the
`tools/pre-execute` seam that every RC since `0.2.0-rc.1` carries, and the
supported range (`>=0.2.0-rc.1 <0.3.0-0`) is now declared in `package.json`
`engines.dsh` — the field the harness's own plugin-compatibility gate
reads, so an incompatible DSH skips this bundle loudly instead of loading
it. The `hooks.json` form in this repo is the reference/regression twin,
not the live gate; running it needs the optional
`@deepseek-ai/dsh-hooks-claude-code` bridge, which the `0.2.1-rc.2`
desktop build does not bundle (install it from the plugin market if you
want that form). Requires Node >= 20.

---

## How it works

For each gated tool call the plugin sends the tool name and arguments (clipped
at 8000 chars per string) to TypeSafe's SystemOne endpoint with five `noul`
questions:

| signal | what it asks |
| --- | --- |
| `read_only` | does this only inspect/read/display, changing nothing? |
| `destructive` | would this delete/overwrite data a person could not restore? |
| `secret_exposure` | would this send or print secret values anywhere? |
| `external_irreversible` | would this change state outside this machine irreversibly? |
| `routine_dev` | is this a routine local development step? |

The first rule that fires wins, in this order:

1. `secret_exposure >= 0.50` → **deny**
2. `destructive >= 0.50` → **ask** when exempt, otherwise **deny**
3. `external_irreversible >= 0.50` → **ask**
4. `read_only >= 0.80` → **allow**
5. `routine_dev >= 0.75` → **allow**
6. otherwise → **ask** (`unclear`)

Every failure path — no API key, timeout, non-JSON answer, wrong answer shape
— degrades to `next()` and logs the error. **A gate that cannot reach its
judge must never become the thing that blocks the harness.**

## Path-scoped exemption

The gate has no notion of context, so `rm scratch-note.txt` and `rm -rf /`
score identically: destructive, deny, no approval channel. That leaves the
agent permanently unable to clean up its own scratch files, because a deny
cannot be overridden from inside the session.

Exemption fixes exactly that one case: when **every** path a command writes to
lives inside an exempt prefix (default `['.agent-scratch']`), the destructive
deny is downgraded to an **ask** — a person still sees it, but the agent is
not locked out. The parser is deliberately shallow and **fails closed**:

- `secret_exposure` denies are never downgraded.
- one non-exempt target disqualifies the whole command.
- unknown verbs, unparseable quoting, `cd` then `rm`, `find -delete`,
  `xargs rm`, symlink escapes — all keep the original deny.
- a write verb followed by more statements on later lines: a bare newline is
  whitespace, not a command separator, so the following tokens join the verb's
  argument list as extra targets — extra targets can only ever make a command
  *less* exempt, so this too fails closed. Keep destructive commands to a
  single statement when you want the exemption to apply.

```
rm -rf .agent-scratch/old-logs    # ask   (exempt_destructive)
rm -rf src                        # deny  (destructive)
cat .agent-scratch/keys.txt       # deny  (secret never downgrades)
rm .agent-scratch/a src/b         # deny  (one target outside the prefix)
```

## Judge backends

The gate needs a model that answers five yes/no questions with probabilities.
Two backends, chosen by the `judgeProvider` config key:

- **`typesafe` (default)** — TypeSafe's SystemOne endpoint with calibrated
  `noul` probability questions: sub-second answers, and the thresholds mean
  what they say on that calibrated scale. Needs `TYPESAFE_API_KEY`, and **some
  networks cannot reach it**: a region-blocked egress gets HTTP 451 "not
  available in your region", which fails every call open. Configure
  `typesafeProxy` (or `HTTP_PROXY`/`HTTPS_PROXY`) to route around that.
- **`dsh-llm`** — the same five questions go through the session's own LLM
  service, following the provider/model the DSH profile configures: no extra
  credential, no endpoint of its own, so no region or proxy question at all.
  The cost: every gated call waits for that model (pin a fast one via `model` /
  `judgeRoute`), and its self-reported probabilities are not on the calibrated
  scale the thresholds were tuned against.

Both backends converge on the same `Signals` object, so thresholds,
exemption, and log format are identical whichever judge answers. A judge that
errors, times out, or answers out of protocol fails open — the gate logs the
reason and lets the call through.

## Configuration

Config keys (profile `cordis.patch.yml`), all optional:

| key | default |
| --- | --- |
| `judgeProvider` | `typesafe` |
| `matcher` | `^(bash\|pwsh\|terminal_)` |
| `model` | backend-relative: `jev-1.13.0` on `typesafe`; unset on `dsh-llm` means follow the session route |
| `judgeRoute` | unset: follow the session's live provider/model; set `{provider, model}` to pin both |
| `logPath` | `<plugin dir>/decisions.jsonl` |
| `typesafeApiKey` | unset: a `role('secret')` field, edited masked in the form and held by the credential store |
| `typesafeApiKeyEnv` | `TYPESAFE_API_KEY` — the environment variable read when no key is configured |
| `typesafeProxy` | unset: proxy URL for the typesafe endpoint (region-block workaround); empty reads `HTTP_PROXY`/`HTTPS_PROXY`, then connects directly |
| `destructive` | `0.50` |
| `secretExposure` | `0.50` |
| `externalIrreversible` | `0.50` |
| `readOnly` | `0.80` |
| `routineDev` | `0.75` |
| `exemptPrefixes` | `['.agent-scratch']` |
| `authorizedOperations` | `[]` — commands whose external-irreversible ask is downgraded to allow, matched per statement |

Auth: the `dsh-llm` backend needs no extra credential — it rides on the
credentials DSH already resolved for the session's provider. The `typesafe`
backend resolves its key by candidates, profile config first:
`typesafeApiKey` (a `role('secret')` field — masked in the form, held by the
credential store, never echoed) → the environment variable named by
`typesafeApiKeyEnv` (`TYPESAFE_API_KEY` by default) → the Windows User
environment (a legacy fallback, read once and cached). Configuring the key in
the form is the intended path; the environment variable is the candidate for
scripted deployments.

Every decision row records its `judge` backend and `model`; `dsh-llm` rows also record `provider`. A log that spans a backend switch stays interpretable.

## Settings page

The plugin declares a schemastery `Config` schema, which the DSH settings
service projects into this profile's configuration form (`ctx.settings`):
**the judge backend, pinned provider/model, matcher, log path, all five
thresholds, the exempt prefixes, and the pre-authorized operations are editable
as a form**, validated on write, persisted into the profile patch, and applied by
the Loader without a restart. The same keys keep working in `cordis.patch.yml`
for scripted setups.

The card appears on the Plugins page's bundle detail, between the description
and the component list.


The profile entry is the single source of truth: there is deliberately **no
environment-variable layer**, so what the card shows is what runs — no second
truth to drift. (The Python hook twin under `hooks/` still reads `DECISION_GATE_*`
environment variables; that is the hook form's only configuration channel and
a separate deployment path.)

The schema needs `@deepseek-ai/schemastery` at runtime, resolved from the
plugin's own location like any bare import (Node walks up from the module
file). A normal `npm install` — including the one `dsh plugin add` performed
into the profile — provides it.

## Install

One command into any profile — the bundle's own patch mounts the gate, so
there is no manual profile edit:

```bash
dsh plugin --profile web add C:/example/dsh-decision-gate
```

On the desktop app (whose profile the CLI refuses by design), use the same
source through the in-app Plugins page: **添加插件 → 本地路径 →
`C:/example/dsh-decision-gate`**. Both routes link the package into the profile and
select the bundle; the runtime dependencies `@deepseek-ai/schemastery` and
`undici` resolve from npm.

Restart DSH (or the desktop app) and the gate is live with the defaults: the
calibrated TypeSafe judge (`TYPESAFE_API_KEY` — from the card's secret field,
an environment variable, or the Windows User environment), shell tools only,
thresholds as below, `.agent-scratch` exemption. A region-blocked network (this
one's direct egress gets HTTP 451 from `api.typesafe.ai`) additionally pins
`typesafeProxy` **in the profile's own patch row** — the shipped bundle patch
stays machine-neutral.

## Configure

Every key has a default, so the zero-config install works. To override, add a
row that targets `decision-gate` in the profile's `cordis.patch.yml`:

```yaml
- id: decision-gate
  config:
    judgeProvider: 'dsh-llm'
    destructive: 0.4
```

Because the row is mounted by the bundle, the settings card renders
**read-only** on a stock install — it still shows every effective value and
judge health, which is the point of the card. A profile-patch row like the
one above is both the configuration channel and what makes the card writable
again.

## Uninstall

```bash
dsh plugin --profile web remove dsh-decision-gate
```

One step — the row lives in the package, so removing the bundle removes the
gate. Rolling back to the hook form instead: the hook version is the files
under `hooks/`, registered through `hooks/hooks.json`.

## Layout

```
lib/index.js          built host half (one runtime dependency: schemastery)
src/index.ts          plugin source
src/parity.ts         Python↔TypeScript decision parity harness
hooks/                Python twin (specification and regression baseline)
tests/                pytest suite for the Python twin + hook config
docs/decision-gate-setup.md  deployment and calibration record
AGENT.md              rules for agents working on this repo (not shipped)
examples/             probe payloads used by the live-path tests
```

The Python twin in `hooks/` is the reference implementation the plugin was
ported from; `src/parity.ts` replays its recorded baseline through the
TypeScript side and asserts the decisions still match. `hooks/exempt.py` and
the exemption code in `src/index.ts` mirror each other token for token, held
to the same expectations by `tests/test_exempt.py` and the offline section of
`parity.ts` — the two sides cannot drift apart silently.

`tests/test_policy.py`, `tests/test_triage.py` and `tests/test_live_path.py`
(plus `examples/`) are inherited from the workspace this package was extracted
from: they test the sibling noul-triage feature and import its `muiltilab`
package. `npm run test:py` deliberately runs only the gate's own three test
modules; run the full suite from a checkout that has the triage package
importable.

## Verify

```bash
node tests/functional.mjs   # 14 fake-context cases: both backends, fail-open, log
node src/parity.ts          # 26 recorded decisions + 30 exemption cases + 3 downgrade
                            # rules + 12 judge-output parses + 10 config shapes
python -m pytest tests -q   # Python twin + hook config
```

The offline sections of parity need no API key; the recorded-decision replay
needs `TYPESAFE_API_KEY`.

During the calibration watch period, `node tools/observe.mjs` prints the
decision distribution, judge error rate, near-miss allows (a dangerous signal
below its threshold), and recent denials for false-deny review.

The deployment and calibration record — install paths, both config channels,
the probe tables, and the periodic threshold reviews — lives in
`docs/decision-gate-setup.md`.

## License

Business Source License 1.1 — see [`LICENSE`](LICENSE). Source is visible and
free to copy, modify, and redistribute, and free for non-production use;
production use requires a commercial license until the Change Date
(2030-10-10), after which the work is available under Apache 2.0.
