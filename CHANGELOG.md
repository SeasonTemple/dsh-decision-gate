# Changelog

All notable changes to this project are documented here. The project uses
semantic versioning; the version in `package.json` and `dsh.plugin.json` is
authoritative.

## [Unreleased]

### Docs

- **A docs site, and the discovery basics that go with it.** GitHub Pages now
  serves `docs/` at seasontemple.github.io/dsh-decision-gate (Jekyll, with a
  landing page), and the repo homepage points at it. Topics grew from 11 to 19
  with the long-tail terms this project actually answers to (`llm`,
  `ai-agents`, `shell`, `permissions`, `typesafe`, `deepseek-harness`,
  `hooks`, `safety`), the density the comparable projects use. Both READMEs
  drop the stale static "Tests: 120 passing" badge for a live CI badge, a
  release-version badge, and a docs badge.
  The setup and verification guide now ships in English too:
  `docs/decision-gate-setup.md` is the English twin of
  `docs/decision-gate-setup.zh.md`, and the docs site links both.
  - Both READMEs and both setup guides replace the author's workspace path
    (an absolute path) in install commands and examples with a
    `/path/to/dsh-decision-gate` placeholder — an absolute path is a deploy-local
    value (AGENT.md rule 16), and the docs already use `<you>` placeholders
    elsewhere. Test fixtures and CHANGELOG history keep their paths on purpose:
    the former are synthetic exemption-parser inputs, the latter is history.

## [0.5.1] - 2026-10-19

### Added

- **The supported DSH range is now declared where the harness reads it.**
  `package.json` gains `engines.dsh: ">=0.2.0-rc.1 <0.3.0-0"`. The desktop
  RC's loader (`evaluatePluginCompatibility` in `@deepseek-ai/dsh-app-boot`)
  reads only the bundle's `package.json` — an own `engines.dsh` decides
  alone, otherwise every `@deepseek-ai/dsh*` peer range is checked against
  the runtime — so the range that already lived in `dsh.plugin.json` (a file
  no RC code reads) is now also authoritative for the loader. An
  incompatible DSH skips this bundle with a loud, named error instead of
  loading it; `dsh.plugin.json` keeps the same range for older harnesses.

### Fixed

- **The parity replay runs again.** `src/parity.ts` crashed with
  `ReferenceError: isAuthorizedMatch is not defined` the moment the
  exemption section handed off to the authorization section — the import
  from `./index.ts` never listed the function `authorizedSection` calls, so
  `npm run test:node` (and `npm run check`) have been red since the
  statement-level matching fix (`0f8f1eb`, in the 1.4.0 line). All four
  offline sections now run to completion: 30 exemption parser cases + 3
  downgrade rules, 5 authorization decision rules + 3 match rules, 3 valid
  + 9 rejected judge outputs, 8 accepted + 3 refused config shapes.
- **A cancelled shell call no longer waits out the judge.** The gate is an
  async `tools/pre-execute` listener, and the RC's contract for that seam
  asks async gates to observe `exec.signal`; the judge call previously
  watched only its own 60s budget, so a call the user cancelled sat out the
  full judge before the registry applied the cancellation. Both judge
  backends now abort on caller cancellation first, budget second. A host
  execution without a signal (an older RC, or the functional tests' fake
  exec) keeps the budget alone, exactly as before.

### Changed

- **The ambient host types were refreshed against the desktop RC
  0.2.1-rc.2**, read out of the app archive: `cancel` joined
  `PreToolDecision`, `deny.reason` became required, `ask` gained
  `displayReason`, `ToolExecution` carries the caller `signal`, and
  `finish` gained a `tool-calls` reason. No behavior change — the point is
  that the next host change now fails the typecheck instead of drifting
  silently. What the plugin never touches stays undescribed on purpose.

### Docs

- **Both READMEs open with a version-compatibility note.** Verified
  against `0.2.1-rc.2`: the in-process gate rides the `tools/pre-execute`
  seam every RC since `0.2.0-rc.1` carries; the supported range is declared
  in `engines.dsh`; the `hooks.json` form needs the optional
  `@deepseek-ai/dsh-hooks-claude-code` bridge.
- **`hooks/hooks.json` portability is verified, and its boundary is now
  recorded.** The hook runner shipped inside DeepSeek Harness 0.2.0-rc.2
  (`@deepseek-ai/dsh-hooks-claude-code`, read out of the app archive) settles
  it without a second machine: command hooks spawn with the cwd of the agent
  session's workspace, so the repo-relative `python hooks/decision_gate.py`
  resolves exactly as the 0.4.0 entry assumed. The same source states the two
  conditions the 0.5.0 note never did: the bridge config is process-wide (one
  registered `hooks.json` fires for every session on the machine), and a hook
  that cannot run is logged and skipped while the agent continues. The file is
  therefore correct for sessions whose workspace is this repo — the documented
  install context for this reference implementation — and silently no-ops in
  any other workspace. The setup doc now records this contract, including the
  `${CLAUDE_PLUGIN_ROOT}` escape hatch for a machine-wide install. The
  published file stays machine-neutral, as the 0.4.0 reset intended.
- **The bridge is not in the 0.2.1-rc.2 desktop bundle.** The same check,
  re-run against the current desktop RC, finds
  `@deepseek-ai/dsh-hooks-claude-code` absent from the shipped 295-package
  tree — not bundled, not an optional bundle, not in the on-demand catalog;
  it is still listed in the plugin catalog, so a plugin-market install is
  the route. The live gate never used the hook form (the Python file is the
  reference twin), so nothing regresses — but the portability conclusion
  above describes 0.2.0-rc.2, not this build.

### Notes

- Verified against desktop RC 0.2.1-rc.2
  (`@deepseek-ai/dsh-desktop-runtime`, Electron 44.7.0 / Node 24.21.0) by
  reading the shipped package sources: the `tools/pre-execute` dispatch in
  `dsh-tools`, the bundle-patch and compatibility gates in
  `dsh-plugin-manager` / `dsh-app-boot`, the `llm.stream` service and
  `EpochHeader.config` route in `dsh-llm`, `SessionHeader.cwd`, and the
  settings-card seams (`configForms`, `settings.plugins.tab`,
  `plugins.bundle.config`, `modelCatalog`, `dsh-client-ui-primitives`).
- Still unverified: the hooks bridge under 0.2.1-rc.2 (not bundled); the
  TypeSafe live replay is region-blocked from this machine (HTTP 451), so
  the recorded-baseline replay could not run here — the offline sections
  it gates on are green locally and in CI.

## [0.5.0] - 2026-10-10

### Fixed

- **The settings card renders.** 0.4.0 shipped a card that never appeared, and
  every failure path was silent. Three separate causes, found one at a time:
  the browser half treated `configForms`, `slots`, and `remote` as optional
  inside a scoped inject, so one unresolvable name meant the callback never
  fired and the card never mounted; `remote.session` was not injected, and
  reaching an uninjected service throws before any guard can run — the
  console's `cannot get property "remote.session" without inject` was the
  whole diagnosis; and a failed `require` returned after a single
  `console.error`, which is why a documented settings page could simply be
  absent. All three now fail visibly.

### Docs

- Both READMEs and the setup doc describe the settings card as working, because
  it now is. The 0.4.0 sections that said it did not render — and that
  configuration happened only through `cordis.patch.yml` — are corrected rather
  than left to rot.
- The setup doc records the three silent failure modes and the console line
  that ended the hunt, so the next person does not repeat it.

### Notes

- Still unverified: `hooks/hooks.json` portability. It now reads
  `python hooks/decision_gate.py`, but no second machine has confirmed that
  DSH's hook runner resolves that from the project root.

## [0.4.0] - 2026-10-10

### Changed

- **Version reset from 1.4.0 to 0.4.0.** The 1.x line claimed a maturity this
  project does not have. Concretely, at the moment 1.4.0 was cut: the settings
  card documented in both READMEs did not render at all; the hook form's
  `hooks.json` carried an absolute path into an unrelated workspace's venv; and
  `authorizedOperations` had shipped three bugs that every test passed and that
  broke on the first real command. That is a 0.x project. `1.0.0` on 2026-09-22
  was premature for the same reason, and the numbers in between compounded it.
- Version numbering now follows what is actually verifiable: the gate itself
  works and is covered by CI, but the configuration surface does not, so the
  project is not at 1.0.

### Known broken (recorded so the version means something)

- **The settings card does not render.** Both READMEs promise a form in
  设置 → 内置插件 and on the Plugins page's bundle detail. It does not appear.
  `dsh/client.js` fails silently — one `console.error` and no card — so the
  configuration surface promised in the docs is absent. Until this is fixed,
  configuration happens only through the profile's `cordis.patch.yml`.
- **`hooks/hooks.json` portability is fixed but unverified.** It now reads
  `python hooks/decision_gate.py`; whether DSH's hook runner resolves that from
  the project root has not been confirmed on a second machine.

### Notes

- The `v1.4.0` tag and GitHub Release were deleted once `gh` became reachable
  again. The reset is recorded here so the history stays honest either way.

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
