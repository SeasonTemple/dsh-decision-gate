# Changelog

All notable changes to this project are documented here. The project uses
semantic versioning; the version in `package.json` and `dsh.plugin.json` is
authoritative.

## [1.4.0] - 2026-10-10

### Added

- **Pre-authorized irreversible operations** (`authorizedOperations`): a list of
  exact commands whose `external_irreversible` ask is downgraded to allow. It
  exists for one friction the exemption cannot reach — an irreversible step a
  person has already agreed to (`git push origin main` after approving a public
  repo) still asked on every run, because the gate has no notion of context.
  Matched rows log `authorized: true` under the rule `authorized_external`, so
  every waived irreversible step stays auditable. Default `[]`, so behavior is
  unchanged until configured. The Python twin reads the same list from
  `DECISION_GATE_AUTHORIZED_OPERATIONS`.

### Notes

- The whitelist is deliberately narrow, and both limits are load-bearing:
  matching is **whole-command equality** after whitespace normalization (a
  whitelisted string inside `echo hi && git push origin main` never matches, so
  the surrounding text keeps its own verdict — a regex whitelist would be
  widened in practice), and it only ever downgrades the
  `external_irreversible` rule. `secret_exposure` and `destructive` are
  evaluated first, so the whitelist cannot launder a command that also leaks
  secrets or destroys data.
- Verified: `node tests/functional.mjs` 0 failures (22 cases, 4 of them new:
  authorized allows, unlisted still asks, whitelisted string inside a longer
  command does not match, authorization never launders a secret verdict),
  `pytest` 126 passed, `node src/parity.ts` offline sections clean
  (`authorization: 4 decision rules, failures: 0`).

## [1.3.0] - 2026-10-09

### Changed

- **Renamed `dsh-jevgate` → `dsh-decision-gate`.** The old name pinned the
  plugin to one judge (Jev is only the default *model* of the `typesafe`
  backend), which misrepresented what it is: a PreToolUse decision gate whose
  judge is swappable — `dsh-llm` needs no TypeSafe credential at all. Every
  identity moved with it: package name, plugin id (`jev-gate` →
  `decision-gate`), the browser-half module id, logger prefixes, the Python
  twin's module (`hooks/jev_gate.py` → `hooks/decision_gate.py`), its test
  (`tests/test_jev_gate.py` → `tests/test_decision_gate.py`), the setup doc
  (`docs/jev-gate-setup.md` → `docs/decision-gate-setup.md`), and the hook
  twin's `JEV_GATE_*` environment variables → `DECISION_GATE_*`.
- The working directory moved with it: `C:\example\jev-gate` →
  `C:\example\dsh-decision-gate`. The installed junction, the profile's
  `link:` dependency, the `logPath` (the 342-row decision log travelled with the
  directory, so the calibration history is unbroken), and every absolute path
  in the docs now point at the new location.
- **License changed from MIT to Business Source License 1.1** (`BUSL-1.1`).
  Source stays visible and free to copy, modify, and redistribute, and free
  for non-production use; production use needs a commercial license until the
  Change Date (2030-10-10), after which the work is available under Apache 2.0.
  Parameters: Licensor `SeasonTemple`, Additional Use Grant none.

### Docs

- `docs/decision-gate-setup.md` synced to the current state: the
  `typesafeProxy` key and the HTTP 451 region-block diagnosis, the
  "dependency installed ≠ bundle enabled" step (a silent failure mode hit in
  practice), the `undici` runtime dependency, and the 2026-10-09 verification
  record.
- Both READMEs' install sections now say the shipped bundle patch stays
  machine-neutral, with deploy-local values (proxy, logPath, key) belonging in
  the profile's own patch row.

### Notes

- Earlier CHANGELOG entries keep the historical names: they record what those
  releases shipped. `1.1.1` and `1.2.0` were published as `dsh-jevgate`.
- Verified after the rename: `node tests/functional.mjs` 0 failures,
  `python -m pytest tests/test_decision_gate.py tests/test_exempt.py
  tests/test_analyze.py -q` 120 passed, parity offline sections clean
  (`signal drift: 0`). The parity live replay needs `TYPESAFE_API_KEY` **and**
  a reachable endpoint — it uses a bare `fetch`, so a region-blocked network
  gets 26 mismatches from the 451s, not from the rename.

## [1.2.0] - 2026-10-08

### Added

- **Proxy support for the typesafe judge** (`typesafeProxy`): TypeSafe's
  SystemOne endpoint answers HTTP 451 "not available in your region" from a
  region-blocked egress, which fails every call open — indistinguishable from
  a gate that silently allows everything. The backend now routes through an
  explicit proxy URL, then `HTTP_PROXY`/`HTTPS_PROXY` (with `NO_PROXY`
  respected via undici's `EnvHttpProxyAgent`), then direct; agents are cached
  per URL. New runtime dependency: `undici`. This deployment's bundle patch
  per URL. New runtime dependency: `undici`. The shipped bundle patch stays
  machine-neutral; this deployment pins its proxy in the profile's own
  patch row, alongside its logPath.
- `tests/functional.mjs` grew proxy-agent candidate cases (explicit config,
  environment, direct), and `resolveProxyAgent` is exported for them.

### Notes

- The judge default stays `typesafe` (calibrated, sub-second — the scale the
  thresholds were tuned against). The region block is a deployment property,
  solved by the proxy config, not a reason to change the default.

## [1.1.1] - 2026-10-08

### Fixed

- **Documentation — wrong default in both READMEs' config tables.** The
  `judgeProvider` row read `dsh-llm`, while the code (`DEFAULT_JUDGE`), the
  bundle patch, and both READMEs' own prose say `typesafe`. Corrected in
  `README.md` and `README.zh.md`.
- **Documentation — duplicated sentence** in `README.zh.md`'s settings-page
  section (the schemastery line appeared twice).
- **Documentation — overstated log fields.** Both READMEs claimed every
  decision row records `judge`, `provider`, and `model`; `provider` is only
  written on the `dsh-llm` path (`src/index.ts`). Corrected to match.
- **Packaging — `lib/decisions.jsonl` shipped in the tarball.** `files`
  listed the whole `lib` directory, so 45 rows of real decision data
  (commands, session ids, cwds, signals) went into the package. `files` now
  enumerates `lib/index.js` and `lib/index.d.ts`.
- **Packaging — machine-specific path in the shipped bundle patch.**
  `cordis.patch.yml` carried `logPath: 'C:/example/jev-gate/runtime/decisions.jsonl'`;
  the file ships in the tarball, so the line is removed and the log falls back
  to the built-in `<plugin dir>/decisions.jsonl`. Deploy-local paths belong in
  the profile's own patch row, which overrides this row by id — an existing
  install that relied on the bundle's logPath moves its log on next reload
  unless it pins one.
- **Packaging — `docs/` now ships.** `files` includes it, so the deployment and
  calibration record (`docs/jev-gate-setup.md`) travels with the package.

### Docs

- Rewrote `docs/jev-gate-setup.md` against the current package form: plugin
  install through `dsh plugin add` or the desktop app's plugin page (whose
  profile the CLI refuses by design), the bundle-mounted row, the two config
  channels (profile patch row / settings card), the dual judge backends and
  the key resolution chain. The previous text described the pre-package
  layout (`plugins/jev-gate/index.ts`, `insert`-style profile edits,
  `JEV_GATE_*` environment switches). The 2026-09-21 calibration sections
  now sit alongside a 2026-10-08 review of 302 real decisions, which
  concludes all five thresholds stay at their defaults.
- Added `AGENT.md`: the rules for agents working on this repo — the two mirrored
  implementations and the parity gate, thresholds as calibration output, the
  three default-value sites that must agree, the machine-neutral bundle patch,
  and the packaging checks. It points at the READMEs and the setup doc instead
  of duplicating them, and it is deliberately not shipped in the package.

## [1.1.0] - 2026-10-08

### Added

- **Dual judge backends** (`judgeProvider`): `typesafe` (TypeSafe SystemOne,
  calibrated `noul` probabilities, the default) and `dsh-llm` (the session's
  own LLM service via `ctx.llm.stream`, following DSH's configured
  provider/model — no extra credential). Both converge on the same `Signals`,
  thresholds, exemption, and log format.
- **Browser half** (`dsh/client.js`): a settings card in 设置 → 内置插件 and on
  the Plugins page's bundle detail, hand-written in the lazy-CJS bundle
  protocol (no build step). Model/provider pickers read the Host's model
  catalog; a catalog outage degrades the fields to text inputs rather than
  blocking configuration.
- **Config schema** (`export const Config`): every field `.volatile()`, so the
  settings service projects it into a validated form, the editor persists
  edits into the profile patch, and the Loader applies them without a restart.
- **Regression sections in `src/parity.ts`**: offline exemption (30 parser
  cases + 3 downgrade rules), judge-output parser (3 valid + 9 rejected), and
  the Config schema itself (7 accepted + 3 refused shapes — the section that
  caught the startup-failure bug below).

### Changed

- **Config is read through the volatile reference** (`config.field.get()`),
  per call. Reading the reference as a bare value silently dropped every
  configured key to its built-in default — the profile's `logPath`,
  `judgeProvider`, and thresholds were ignored while the gate ran on
  defaults. Functional tests now drive `apply()` with reference-shaped
  config so this cannot regress.
- **The environment-variable layer is gone** (`JEV_GATE_*`): the profile
  entry is the single source of truth, so the card shows what actually runs.
  The Python hook twin under `hooks/` keeps its `JEV_GATE_*` channel — that
  is the hook form's only configuration route and a separate deployment path.
- **The TypeSafe key is configured, not scraped from the environment**
  (`typesafeApiKey`, a `role('secret')` field edited masked in the form and
  held by the credential store; `typesafeApiKeyEnv` names a fallback
  environment variable; the Windows User environment is the last resort).
  Config and environment candidates re-resolve per call, so a rotated key
  takes effect on the next gated call.
- **Judge request budget 10s → 60s**: a general session model (a reasoning
  model in particular) needs tens of seconds; the old budget aborted every
  such call into fail-open, which is indistinguishable from a gate that
  silently allows everything.
- **Install-and-run contract**: the `jev-gate` row now lives in the package's
  own bundle patch, so installing the bundle into any profile (CLI `dsh plugin
  add`, or the desktop app's plugin manager with a local path) mounts the gate
  with zero manual profile edits — the earlier design put the row in the
  profile's root Include, which required a hand edit per profile. The measured
  trade: a bundle-mounted row is not root-Include-owned, so the settings card
  renders read-only on a stock install (it still shows every effective value
  and judge health); a profile-patch row targeting `jev-gate` is both the
  override channel and what restores card writes.
- Registered as an installed package (`dsh plugin --profile web add`); the
  uninstall is one step (`dsh plugin remove dsh-jevgate`) since the row ships
  with the package.

### Fixed

- Schema startup failure: `.required()` inside the `judgeRoute` object
  rejected every config that omitted it, because schemastery validates an
  absent object's inner shape. Inner fields are optional; the runtime pins a
  route only when both are non-empty.

## [1.0.0] - 2026-09-22

### Added

- The gate itself: five `noul` questions (read_only / destructive /
  secret_exposure / external_irreversible / routine_dev), fixed thresholds,
  allow/ask/deny, JSONL decision log.
- **Path-scoped exemption**: a destructive deny downgrades to ask when every
  write target sits inside an exempt prefix (default `.agent-scratch`), so an
  agent is never permanently locked out of its own scratch space. Secret
  exposure never downgrades; one non-exempt target disqualifies the command;
  the parser fails closed on everything it does not understand.
- Fail-open contract: a judge that errors, times out, or answers out of
  protocol lets the call through and logs the reason.
- Python reference implementation (`hooks/`) with a pytest suite, and the
  TypeScript parity harness (`src/parity.ts`) that replays its recorded
  baseline through the plugin.
