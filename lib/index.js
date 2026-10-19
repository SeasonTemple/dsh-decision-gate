/**
 * DSH PreToolUse gate: asks a judge model what kind of operation a tool call
 * is, applies the thresholds in the plugin config, and allows, asks, or denies.
 *
 * This is the in-process form of `hooks/decision_gate.py`. Same state shape, same
 * questions, same thresholds, same fail-open contract — the only difference is
 * that it runs inside the harness process instead of as a spawned shell
 * command, which removes roughly 3s of process-launch cost per gated call.
 *
 * Two judge backends, chosen by the `judgeProvider` config key:
 *
 * - `dsh-llm` (default): sends the same five questions through the session's
 *   own LLM service (`ctx.llm.stream`), following the provider/model the DSH
 *   profile configures for the current request. No extra credential, no extra
 *   endpoint, and switching the judge model is a DSH config change.
 * - `typesafe`: the original TypeSafe SystemOne endpoint with calibrated
 *   `noul` probability questions; needs TYPESAFE_API_KEY.
 *
 * Both backends converge on the same `Signals` object, so `decide`, the
 * thresholds, the exemption, and the log format are identical whichever judge
 * answered. Every failure path degrades to `next()`: a gate that cannot reach
 * its judge must never become the thing that blocks the harness.
 *
 * @module decision-gate
 */
import { appendFileSync, mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { EnvHttpProxyAgent, ProxyAgent, fetch as proxiedFetch } from 'undici';
import z from '@deepseek-ai/schemastery';
const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));
const DEFAULT_LOG = join(PLUGIN_DIR, 'decisions.jsonl');
const ENDPOINT = 'https://api.typesafe.ai/v1/systemone';
const DEFAULT_MATCHER = '^(bash|pwsh|terminal_)';
/**
 * Default judge: TypeSafe's SystemOne endpoint — calibrated `noul`
 * probabilities, sub-second, and the scale the thresholds were tuned against
 * (see the 2026-10-08 review of 302 real decisions in
 * docs/decision-gate-setup.md). A region-blocked network gets HTTP 451 from it and
 * fails every call open; that deployment configures `typesafeProxy` (or
 * `HTTP_PROXY`/`HTTPS_PROXY`). `dsh-llm` is the fallback with no endpoint of
 * its own, at the cost of latency and an uncalibrated probability scale.
 */
export const DEFAULT_JUDGE = 'typesafe';
/** Model id the `typesafe` backend falls back to when none is configured. */
export const DEFAULT_TYPESAFE_MODEL = 'jev-1.13.0';
/** Mirrors `MAX_STRING_CHARS` in the Python gate. */
const MAX_STRING_CHARS = 8000;
/**
 * Judge request budget. The TypeSafe endpoint answers the five noul questions
 * in well under a second; a general session model (a reasoning model in
 * particular) can take tens of seconds, and a budget tuned for the endpoint
 * aborts every such call into fail-open — which looks exactly like a gate
 * that silently allows everything.
 */
const REQUEST_TIMEOUT_MS = 60_000;
const RETRY_DELAY_MS = 500;
const MAX_ATTEMPTS = 2;
const RETRYABLE_STATUS = new Set([408, 425, 429, 500, 502, 503, 504]);
/** Mirrors `DEFAULT_EXEMPT_PREFIXES` in hooks/exempt.py. */
export const DEFAULT_EXEMPT_PREFIXES = ['.agent-scratch'];
export const DEFAULT_POLICY = {
    destructive: 0.50,
    secret_exposure: 0.50,
    external_irreversible: 0.50,
    read_only: 0.80,
    routine_dev: 0.75,
    exemptPrefixes: DEFAULT_EXEMPT_PREFIXES,
    authorizedOperations: [],
};
/** Ordered exactly as `decide` in policy.py, so the first match wins the same way. */
export function decide(signals, policy = DEFAULT_POLICY, exempt = false, authorized = false) {
    const at = (value) => value.toFixed(2);
    if (signals.secret_exposure >= policy.secret_exposure) {
        return {
            action: 'deny',
            rule: 'secret_exposure',
            reason: `looks like it would expose secrets (p=${at(signals.secret_exposure)})`,
        };
    }
    if (signals.destructive >= policy.destructive) {
        if (exempt) {
            // Every path this command writes to is inside an exempt prefix, so the
            // data at risk is scratch data. A person should still see it, but the
            // agent must not be permanently locked out of its own scratch space --
            // a deny cannot be overridden from inside the session. Secret exposure
            // is never downgraded, and neither is a destructive command with even
            // one target outside the prefix.
            return {
                action: 'ask',
                rule: 'exempt_destructive',
                reason: `destructive but confined to an exempt path (p=${at(signals.destructive)}); a person should still see it`,
            };
        }
        return {
            action: 'deny',
            rule: 'destructive',
            reason: `looks like it would destroy data that cannot be restored (p=${at(signals.destructive)})`,
        };
    }
    if (signals.external_irreversible >= policy.external_irreversible) {
        // A pre-authorized command skips only this one question. The checks above
        // have already run, so a command that also exposes secrets or destroys data
        // was denied before reaching here -- the whitelist cannot launder it, and a
        // whitelisted string that is not the whole command simply never matches.
        if (authorized) {
            return {
                action: 'allow',
                rule: 'authorized_external',
                reason: `changes state outside this machine, but the command is pre-authorized (p=${at(signals.external_irreversible)})`,
            };
        }
        return {
            action: 'ask',
            rule: 'external_irreversible',
            reason: `looks like it changes state outside this machine (p=${at(signals.external_irreversible)})`,
        };
    }
    if (signals.read_only >= policy.read_only) {
        return {
            action: 'allow',
            rule: 'read_only',
            reason: `reads only (p=${at(signals.read_only)})`,
        };
    }
    if (signals.routine_dev >= policy.routine_dev) {
        return {
            action: 'allow',
            rule: 'routine_dev',
            reason: `routine local development step (p=${at(signals.routine_dev)})`,
        };
    }
    return {
        action: 'ask',
        rule: 'unclear',
        reason: 'not clearly safe or dangerous, so a person should look',
    };
}
/*
 * Path-scoped exemption, mirroring hooks/exempt.py token for token.
 *
 * The gate has no notion of context, so `rm scratch-note.txt` and `rm -rf /`
 * score the same: destructive, deny, no approval channel. `isExempt` asks
 * whether every path a command writes to lives inside an exempt prefix; when
 * it does, `decide` downgrades the destructive deny to an ask. The parser is
 * deliberately shallow and fails closed: anything it cannot parse, any verb
 * it does not know, and any absolute path outside the session cwd simply is
 * not exempt, which keeps the original deny.
 */
const WRITE_VERBS = new Set(['rm', 'shred', 'truncate', 'mv']);
const DESTINATION_ONLY_VERBS = new Set(['cp']);
const VALUE_FLAGS = new Set(['-s']);
const REDIRECT_TOKENS = new Set(['>', '>>']);
const NULL_DEVICES = new Set(['/dev/null', 'nul']);
const PUNCTUATION = '(){};&|<>';
function isOperator(token) {
    if (token !== '' && [...token].every(character => PUNCTUATION.includes(character)))
        return true;
    // A merged fd redirect ("2>") ends a verb's argument list like any operator.
    return /^\d+>>?$/.test(token);
}
/**
 * Split like a POSIX shell would, or null if the command does not parse.
 * Approximates Python's `shlex` with `punctuation_chars=True`; backslash
 * escapes inside quotes are not interpreted, which only ever fails closed.
 */
function tokenize(command) {
    const tokens = [];
    let current = '';
    let started = false;
    let quote = null;
    const push = () => {
        if (started) {
            tokens.push(current);
            current = '';
            started = false;
        }
    };
    for (let index = 0; index < command.length; index += 1) {
        const character = command[index];
        if (quote !== null) {
            if (character === quote)
                quote = null;
            else
                current += character;
            continue;
        }
        if (character === '"' || character === "'") {
            quote = character;
            started = true;
            continue;
        }
        if (character === ' ' || character === '\t' || character === '\n' || character === '\r') {
            push();
            continue;
        }
        // Outside quotes a backslash escapes the next character, exactly as a
        // POSIX shell (and Python's shlex in posix mode) treats it.
        if (character === '\\' && index + 1 < command.length) {
            current += command[index + 1];
            started = true;
            index += 1;
            continue;
        }
        if (PUNCTUATION.includes(character)) {
            push();
            let run = character;
            while (index + 1 < command.length && PUNCTUATION.includes(command[index + 1])) {
                run += command[index + 1];
                index += 1;
            }
            tokens.push(run);
            continue;
        }
        current += character;
        started = true;
    }
    push();
    if (quote !== null)
        return null;
    return tokens;
}
function targetsOf(verb, args) {
    const targets = [];
    let skipNext = false;
    args.forEach((arg, index) => {
        if (skipNext) {
            skipNext = false;
            return;
        }
        if (arg.startsWith('-')) {
            if (VALUE_FLAGS.has(arg))
                skipNext = true;
            return;
        }
        if (DESTINATION_ONLY_VERBS.has(verb) && index !== args.length - 1)
            return;
        targets.push(arg);
    });
    return targets;
}
/** Join `2 > /dev/null` into `2>`, so the fd number is not read as a path. */
function mergeFdRedirects(tokens) {
    const merged = [];
    let index = 0;
    while (index < tokens.length) {
        if (index + 1 < tokens.length
            && /^\d+$/.test(tokens[index])
            && REDIRECT_TOKENS.has(tokens[index + 1])) {
            merged.push(tokens[index] + tokens[index + 1]);
            index += 2;
            continue;
        }
        merged.push(tokens[index]);
        index += 1;
    }
    return merged;
}
/** Every path the command would create, overwrite, move, or delete. */
export function writeTargets(command) {
    const tokens = tokenize(command);
    if (tokens === null)
        return [];
    const merged = mergeFdRedirects(tokens);
    const targets = [];
    let index = 0;
    while (index < merged.length) {
        const token = merged[index];
        if (WRITE_VERBS.has(token)) {
            index += 1;
            const args = [];
            while (index < merged.length && !isOperator(merged[index])) {
                args.push(merged[index]);
                index += 1;
            }
            targets.push(...targetsOf(token, args));
            continue;
        }
        if (REDIRECT_TOKENS.has(token) || /^\d+>>?$/.test(token)) {
            index += 1;
            if (index < merged.length && !isOperator(merged[index])) {
                // The null device absorbs writes; it is never data at risk.
                if (!NULL_DEVICES.has(merged[index].toLowerCase()))
                    targets.push(merged[index]);
                index += 1;
            }
            continue;
        }
        index += 1;
    }
    return targets;
}
/** Mirrors `posixpath.normpath` for the relative and absolute POSIX paths a shell command can name. */
function normalizePath(path) {
    const isAbs = path.startsWith('/');
    const out = [];
    for (const part of path.split('/')) {
        if (part === '' || part === '.')
            continue;
        if (part === '..') {
            if (out.length > 0 && out[out.length - 1] !== '..')
                out.pop();
            else if (!isAbs)
                out.push('..');
            continue;
        }
        out.push(part);
    }
    if (out.length === 0)
        return isAbs ? '/' : '.';
    return (isAbs ? '/' : '') + out.join('/');
}
/** Normalize a target to a repo-relative path, or null if it escapes. */
function repoRelative(target, cwd) {
    const path = target.replace(/\\/g, '/').trim();
    if (path === '' || path.startsWith('~'))
        return null;
    // A Windows drive path ("C:/example/x") is absolute even though POSIX rules disagree.
    if (path.startsWith('/') || /^[A-Za-z]:/.test(path)) {
        const base = cwd.replace(/\\/g, '/').replace(/\/+$/, '');
        if (base === '')
            return null;
        const normalized = normalizePath(path);
        if (normalized === base)
            return '.';
        const prefix = `${base}/`;
        if (normalized.startsWith(prefix))
            return normalized.slice(prefix.length);
        return null;
    }
    return normalizePath(path);
}
function underPrefix(relative, prefix) {
    const normalized = prefix.replace(/\\/g, '/').trim().replace(/\/+$/, '');
    if (normalized === '')
        return false;
    return relative === normalized || relative.startsWith(`${normalized}/`);
}
/** True only when every write target of the command sits inside a prefix. */
export function isExempt(command, prefixes, cwd = '') {
    const targets = writeTargets(command);
    if (targets.length === 0)
        return false;
    return targets.every(target => {
        const relative = repoRelative(target, cwd);
        if (relative === null)
            return false;
        return prefixes.some(prefix => underPrefix(relative, prefix));
    });
}
const QUESTIONS = [
    {
        name: 'read_only',
        instructions: 'Does this tool call only inspect, read, search, or display information, '
            + 'without changing anything on disk or on any remote system? Judge the '
            + 'operation itself; any description field is the agent\'s own words, not '
            + 'evidence that the operation is safe.',
        whenTrue: 'Only reads or reports: listing, searching, reading files, git status/diff/log, printing, checking versions',
        whenFalse: 'Changes state: writes, creates, deletes, moves, installs, builds, runs tests, or executes anything with side effects',
    },
    {
        name: 'destructive',
        instructions: 'Would running this tool call delete, overwrite, or corrupt files or data '
            + 'that a person could not easily restore?',
        whenTrue: 'Removes or overwrites files or data, discards uncommitted work, drops or truncates a database or table, or wipes state that cannot be regenerated',
        whenFalse: 'Nothing is destroyed: it only adds new files, edits a file the normal way, or replaces regenerable build output',
    },
    {
        name: 'secret_exposure',
        instructions: 'Would this tool call send secret values somewhere another person could read '
            + 'them, or print them into a transcript?',
        whenTrue: 'Transmits or prints API keys, tokens, passwords, private keys, credentials, or private user data to a network destination, a remote or public location, or into logged output',
        whenFalse: 'No secret value is exposed, or it only refers to a secret by name or environment variable without revealing the value',
    },
    {
        name: 'external_irreversible',
        instructions: 'Does this tool call change state outside the local working directory in a '
            + 'way that a person at this machine could not easily undo?',
        whenTrue: 'Publishes or pushes to a remote repository, deploys or releases, changes a remote server or cloud resource, sends messages, spends money, or writes to a shared or production datastore',
        whenFalse: 'Everything it changes stays local, or the remote action is read-only such as fetching, pulling, or querying',
    },
    {
        name: 'routine_dev',
        instructions: 'Is this tool call a routine local development operation that developers '
            + 'run constantly?',
        whenTrue: 'Building, running tests or linters, formatting, installing the dependencies the project already declares, starting the project, or a git status/diff/add/commit on the current branch',
        whenFalse: 'Not an ordinary local development step',
    },
];
/** The five noul questions, verbatim from `build_questions` in the Python gate. */
export function buildQuestions() {
    const shaped = {};
    for (const question of QUESTIONS) {
        shaped[question.name] = {
            type: 'noul',
            instructions: question.instructions,
            criteria: { true: question.whenTrue, false: question.whenFalse },
        };
    }
    return shaped;
}
/**
 * Fixed system prompt for the `dsh-llm` judge. The model sees one pending tool
 * call and must answer each of the five questions with a probability. The
 * questions themselves (instructions and criteria) are the same strings the
 * `typesafe` backend sends as `noul` questions — see {@link QUESTIONS}.
 */
export const JUDGE_SYSTEM_PROMPT = `You are the safety judge for exactly one pending tool call in a coding harness. Your answers are combined with fixed thresholds to allow, ask, or deny the call. This review prompt exists for this single call only.

Answer every one of the five questions with a probability from 0.00 to 1.00 that the answer is yes, judging the operation itself and never the tool's name, the description field, or any claimed intention.

Return exactly one JSON object and no other text, with exactly these five members and no others:
{"read_only":0.00,"destructive":0.00,"secret_exposure":0.00,"external_irreversible":0.00,"routine_dev":0.00}
Every value must be a number between 0 and 1. Do not add members, explanations, labels, Markdown, or surrounding prose. Stop immediately after the closing brace.`;
/** Render the same five questions and the pending state as the judge's user turn. */
export function buildJudgePrompt(state) {
    const questions = QUESTIONS.map(question => [
        `${question.name}: ${question.instructions}`,
        `  Answer yes (high probability) when: ${question.whenTrue}`,
        `  Answer no (high probability) when: ${question.whenFalse}`,
    ].join('\n')).join('\n\n');
    return `Pending tool call:\n${JSON.stringify(state, null, 2)}\n\nAnswer these five questions:\n\n${questions}`;
}
const SIGNAL_NAMES = [
    'read_only',
    'destructive',
    'secret_exposure',
    'external_irreversible',
    'routine_dev',
];
/**
 * Count top-level object members without a JSON parser, so a response that
 * repeats a member is rejected instead of silently keeping the last value.
 */
function topLevelMemberCount(text) {
    let depth = 0;
    let inString = false;
    let escaped = false;
    let count = 0;
    for (let index = 0; index < text.length; index += 1) {
        const character = text[index];
        if (inString) {
            if (escaped)
                escaped = false;
            else if (character === '\\')
                escaped = true;
            else if (character === '"')
                inString = false;
            continue;
        }
        if (character === '"') {
            inString = true;
            // A key is a string at depth 1 followed by a colon; a value string is
            // followed by a comma, brace, or bracket instead.
            let lookahead = index + 1;
            while (lookahead < text.length && text[lookahead] !== '"')
                lookahead += 1;
            if (depth === 1 && lookahead + 1 < text.length && text[lookahead + 1] === ':')
                count += 1;
            continue;
        }
        if (character === '{' || character === '[')
            depth += 1;
        else if (character === '}' || character === ']')
            depth -= 1;
    }
    return count;
}
/**
 * Parse one `dsh-llm` judge answer into signals. Strict on purpose: the object
 * must carry exactly the five names as numbers in [0, 1], and anything else
 * throws so the caller can fail open and log the reason.
 */
export function parseSignals(text) {
    let body = text.trim();
    if (body.startsWith('```')) {
        const lines = body.split('\n');
        const stripped = lines.filter((line, index) => !(line.trimStart().startsWith('```') && (index === 0 || index === lines.length - 1)));
        body = stripped.join('\n').trim();
    }
    const value = JSON.parse(body);
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
        throw new Error('judge output must be one JSON object');
    }
    if (topLevelMemberCount(body) !== SIGNAL_NAMES.length) {
        throw new Error('judge output must carry exactly the five signal members, once each');
    }
    const record = value;
    const invalid = [];
    const signals = {};
    for (const name of SIGNAL_NAMES) {
        const answer = record[name];
        if (typeof answer !== 'number' || !Number.isFinite(answer) || answer < 0 || answer > 1) {
            invalid.push(`${name}=${JSON.stringify(answer)}`);
            continue;
        }
        signals[name] = answer;
    }
    if (invalid.length > 0) {
        throw new Error(`judge output has non-probability members: ${invalid.join(', ')}`);
    }
    return signals;
}
/** Recursively cap every string, mirroring `_clip` in the Python gate. */
function clip(value) {
    if (typeof value === 'string') {
        return value.length <= MAX_STRING_CHARS
            ? value
            : `${value.slice(0, MAX_STRING_CHARS)}\n[truncated ${value.length - MAX_STRING_CHARS} chars]`;
    }
    if (Array.isArray(value))
        return value.map(clip);
    if (value !== null && typeof value === 'object') {
        const out = {};
        for (const [key, item] of Object.entries(value))
            out[key] = clip(item);
        return out;
    }
    return value;
}
/**
 * The session identity lives on `Agent.id` (`SessionId`), not on a
 * `sessionId` property -- the runtime Agent face only augments `id`,
 * `session`, `options`, `inbox`, `status`, `ctx` and the lifecycle methods.
 * Reading `agent.sessionId` silently yields `undefined`, which is how the
 * first release shipped an empty `session_id` in every log record.
 */
function sessionIdOf(exec) {
    const agent = exec.agent;
    return typeof agent?.id === 'string' && agent.id !== '' ? agent.id : '';
}
function sessionCwd(exec) {
    const session = exec.agent?.session;
    for (const candidate of [session?.cwd, session?.header?.cwd]) {
        if (typeof candidate === 'string' && candidate !== '')
            return candidate;
    }
    return process.cwd();
}
function buildState(exec) {
    return {
        harness: 'dsh',
        session: {
            id: sessionIdOf(exec),
            cwd: sessionCwd(exec),
        },
        tool_call: {
            name: exec.name,
            arguments: clip(exec.arguments ?? {}),
        },
    };
}
/** Jev answers must be exactly five noul numbers; anything else is a fault. */
export function toSignals(answers) {
    if (answers === null || typeof answers !== 'object') {
        throw new Error('response carried no answers object');
    }
    const source = answers;
    const unexpected = [];
    const values = {};
    for (const name of SIGNAL_NAMES) {
        const answer = source[name];
        const probability = answer !== null && typeof answer === 'object'
            ? answer.noul
            : undefined;
        if (typeof probability === 'number' && Number.isFinite(probability)) {
            values[name] = probability;
        }
        else {
            unexpected.push(`${name}=${JSON.stringify(answer)}`);
        }
    }
    if (unexpected.length > 0) {
        throw new Error(`unexpected answer shape: ${unexpected.join(', ')}`);
    }
    return values;
}
let cachedRegistryKey;
/** The Windows User environment, read at most once (a ~165ms registry query). */
function readRegistryKey(envName) {
    if (cachedRegistryKey !== undefined)
        return cachedRegistryKey;
    if (process.platform !== 'win32')
        return '';
    try {
        const out = execFileSync('reg', ['query', 'HKCU\\Environment', '/v', envName], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
        const match = /REG_SZ\s+(\S+)/.exec(out);
        if (match !== null) {
            return (cachedRegistryKey = match[1].trim());
        }
    }
    catch {
        // fall through to the empty key below
    }
    return '';
}
/**
 * Resolve the TypeSafe key by candidates, in order:
 *
 * 1. the configured key (`typesafeApiKey`, a `role('secret')` field — the
 *    settings form edits it masked and the platform's credential store holds
 *    it, exactly like a provider key in the model catalog);
 * 2. the environment variable named by `typesafeApiKeyEnv` (default
 *    `TYPESAFE_API_KEY`);
 * 3. the Windows User environment (last resort for this machine's legacy
 *    setup; read once and cached).
 *
 * Config and environment reads are O(1) and re-resolved per call, so a key
 * rotated in the settings form takes effect on the next gated call. The
 * harness's subprocess layer scrubs credential-shaped names before spawning
 * a hook, which is why the environment variable is a candidate, not the
 * primary: the profile form is.
 */
export function resolveApiKey(configured = () => '', envName = 'TYPESAFE_API_KEY') {
    const fromConfig = configured().trim();
    if (fromConfig !== '')
        return fromConfig;
    const fromEnv = (process.env[envName] ?? '').trim();
    if (fromEnv !== '')
        return fromEnv;
    return readRegistryKey(envName);
}
/**
 * The provider/model route the session currently uses. DSH's request header
 * carries the live route: whichever provider and model the profile config
 * picked for this request, which is exactly the "model source DSH already
 * has configured" this plugin wants to follow.
 */
function sessionRoute(exec) {
    const session = exec.agent?.session;
    const header = session?.requestHeader?.();
    const provider = header?.config?.provider;
    const model = header?.config?.model;
    if (typeof provider !== 'string' || provider === '')
        return null;
    if (typeof model !== 'string' || model === '')
        return null;
    return { provider, model };
}
/** Raised for an HTTP status the Python gate also refuses to retry. */
class NonRetryable extends Error {
}
/**
 * The proxy dispatcher for the typesafe backend, or null for a direct
 * connection. Candidates, in order:
 *
 * 1. `typesafeProxy` — an explicit proxy URL (e.g. `http://proxy.example:8080`),
 *    which is how a region-blocked network (TypeSafe answers 451 "not
 *    available in your region" from some egress IPs) reaches the endpoint;
 * 2. the standard `HTTP_PROXY` / `HTTPS_PROXY` environment variables, with
 *    `NO_PROXY` respected, via undici's EnvHttpProxyAgent;
 * 3. nothing — a direct connection.
 *
 * Agents are cached per URL: each one pools its own connections, and the judge
 * runs on every gated call.
 */
let cachedAgent;
export function resolveProxyAgent(configured = '') {
    const url = configured.trim();
    if (url !== '') {
        if (cachedAgent?.url !== url)
            cachedAgent = { url, agent: new ProxyAgent(url) };
        return cachedAgent.agent;
    }
    const fromEnv = (process.env.HTTPS_PROXY ?? process.env.HTTP_PROXY ?? '').trim();
    if (fromEnv !== '') {
        if (cachedAgent?.url !== fromEnv)
            cachedAgent = { url: fromEnv, agent: new EnvHttpProxyAgent() };
        return cachedAgent.agent;
    }
    return null;
}
/**
 * Caller cancellation first, the request budget second: whichever fires
 * first aborts the judge call. The RC's pre-execute contract asks async
 * gates to observe `exec.signal` — a shell call the user cancelled must
 * not wait out a 60s judge. A host that hands the gate an execution
 * without a signal (an older RC, or the functional tests' fake exec)
 * gets the budget alone, exactly as before.
 */
function judgeSignal(caller) {
    const controller = new AbortController();
    const budget = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
    const forward = (source) => controller.abort(source.reason);
    if (caller !== undefined) {
        if (caller.aborted)
            forward(caller);
        else
            caller.addEventListener('abort', () => forward(caller), { once: true });
    }
    if (budget.aborted)
        forward(budget);
    else
        budget.addEventListener('abort', () => forward(budget), { once: true });
    return controller.signal;
}
/** Ask TypeSafe's SystemOne endpoint; the calibrated `noul` baseline. */
async function judgeTypesafe(state, model, apiKey, agent, caller) {
    if (apiKey === '') {
        throw new Error('no TypeSafe API key configured or in the environment');
    }
    const body = JSON.stringify({ model, state, questions: buildQuestions() });
    const headers = {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
    };
    let lastError = null;
    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
        try {
            const response = await proxiedFetch(ENDPOINT, {
                method: 'POST',
                headers,
                body,
                signal: judgeSignal(caller),
                ...agent === null ? {} : { dispatcher: agent },
            });
            if (response.ok)
                return await response.json();
            const message = `${response.status} ${response.statusText}`;
            if (!RETRYABLE_STATUS.has(response.status))
                throw new NonRetryable(message);
            lastError = new Error(message);
        }
        catch (error) {
            if (error instanceof NonRetryable)
                throw error;
            lastError = error;
        }
        if (attempt < MAX_ATTEMPTS - 1) {
            await new Promise(resolve => setTimeout(resolve, RETRY_DELAY_MS));
        }
    }
    throw new Error(`gave up after ${MAX_ATTEMPTS} attempts: ${String(lastError)}`);
}
/**
 * Ask the session's own LLM service. The request follows the live route (or a
 * pinned one from config), reuses the credentials DSH already resolved for
 * that provider, and parses the same five questions out of one JSON object.
 */
async function judgeDshLlm(ctx, state, route, caller) {
    const options = {
        provider: route.provider,
        model: route.model,
        system: JUDGE_SYSTEM_PROMPT,
        messages: [{
                role: 'user',
                content: [{ type: 'text', text: buildJudgePrompt(state) }],
            }],
        temperature: 0,
        signal: judgeSignal(caller),
    };
    let text = '';
    let finished = false;
    for await (const chunk of ctx.llm.stream(options)) {
        if (finished)
            throw new Error('judge emitted data after its terminal finish');
        if (chunk.type === 'text-delta') {
            text += chunk.text;
            continue;
        }
        if (chunk.type === 'finish') {
            finished = true;
            if (chunk.reason.kind === 'error' || chunk.reason.kind === 'aborted') {
                const failure = 'failure' in chunk.reason ? chunk.reason.failure : undefined;
                throw new Error(`judge ended with ${chunk.reason.kind} ${failure?.code ?? 'unknown'}: ${failure?.message ?? ''}`);
            }
            if (chunk.reason.kind !== 'stop') {
                throw new Error(`judge ended with ${chunk.reason.kind}`);
            }
        }
    }
    if (!finished)
        throw new Error('judge emitted no terminal finish');
    return parseSignals(text);
}
function appendLog(record, path) {
    try {
        mkdirSync(dirname(path), { recursive: true });
        appendFileSync(path, `${JSON.stringify(record)}\n`, 'utf8');
    }
    catch {
        // A gate that cannot log must still gate.
    }
}
/**
 * Statement-level match against the pre-authorized list.
 *
 * Not whole-command equality: a shell call always arrives wrapped --
 * `Set-Location`, `git -C`, a trailing `| Select-Object` -- and the person
 * pre-authorizing `git push origin main` cannot predict that wrapper, so
 * equality made the list unmatchable in practice. Split on statement
 * separators and let any complete statement stand for itself.
 *
 * Safety does not rest on this: `secret_exposure` and `destructive` are still
 * judged on the whole command first, and the gate documents that it is not a
 * defence against an adversarial agent.
 */
export function isAuthorizedMatch(command, entries) {
    if (entries.length === 0)
        return false;
    const statements = command
        .split(/\s*(?:;|&&|\|\||\n)\s*/)
        // A statement arrives with its own redirections and pipes attached
        // (`git push origin main 2>&1 | Select-Object -Last 3`); drop those tails
        // so the command itself is what gets compared.
        // Pipe first, then strip the redirection tail off what remains: in
        // `git push origin main 2>&1 | Select-Object -Last 3` the redirection sits
        // before the pipe, so stripping the tail first leaves `... 2>&1` behind.
        .map((statement) => statement.split(/\s*\|\s*/)[0])
        .map((statement) => statement.replace(/\s*\d*>>?\s*\S*\s*$/g, '').replace(/\s*\d*>>?\s*$/, ''))
        .map(stripLocators)
        .map((statement) => statement.trim().replace(/\s+/g, ' '))
        .filter((statement) => statement !== '');
    const wanted = entries.map((entry) => stripLocators(entry).trim().replace(/\s+/g, ' '));
    return statements.some((statement) => wanted.includes(statement));
}
/**
 * Remove the tokens that only say *where* to run, not *what* to run.
 *
 * `cd /repo`, `Set-Location 'C:/example/x'` and `git -C /repo push` all name the same
 * action, and a person pre-authorizing `git push origin main` cannot know which
 * wrapper a shell call will arrive in. Locators are dropped from both sides of
 * the comparison, so the action is what gets matched.
 */
function stripLocators(statement) {
    const words = statement.trim().split(/\s+/);
    const out = [];
    for (let index = 0; index < words.length; index += 1) {
        const word = words[index];
        // A leading directory change says where, not what.
        if (out.length === 0 && (word === 'cd' || word === 'Set-Location' || word === 'sl')) {
            index += 1;
            continue;
        }
        // `git -C <path>` and friends name the repository, not the action.
        if (word === '-C' || word === '--git-dir' || word === '--work-tree') {
            index += 1;
            continue;
        }
        out.push(word);
    }
    return out.join(' ');
}
function policyFrom(config) {
    // The profile entry (the settings card writes it) is the only source; an
    // absent key falls back to the built-in default. There is deliberately no
    // environment-variable layer: the card must show what actually runs.
    const pick = (key, fallback) => {
        const fromConfig = config[key];
        return typeof fromConfig === 'number' && Number.isFinite(fromConfig) ? fromConfig : fallback;
    };
    // Same ref-unwrapping as authorizedOperations below: a volatile array may
    // project as an array of refs, and an element that is really a string would
    // then fail the type check and silently drop the whole configured list.
    const fromExempt = configValue(config.exemptPrefixes);
    const exemptPrefixes = Array.isArray(fromExempt)
        ? fromExempt.map((item) => configValue(item)).filter((item) => typeof item === 'string')
        : DEFAULT_EXEMPT_PREFIXES;
    // A volatile array can project as an array of refs rather than an array of
    // strings, so each element is unwrapped before the type check. Without this,
    // an entry that is present and correct still fails `typeof === 'string'` and
    // the whole list silently falls back to empty -- the bug this guards.
    const fromAuthorized = configValue(config.authorizedOperations);
    const authorizedList = Array.isArray(fromAuthorized)
        ? fromAuthorized.map((item) => configValue(item)).filter((item) => typeof item === 'string' && item.trim() !== '')
        : [];
    return {
        destructive: pick('destructive', DEFAULT_POLICY.destructive),
        secret_exposure: pick('secretExposure', DEFAULT_POLICY.secret_exposure),
        external_irreversible: pick('externalIrreversible', DEFAULT_POLICY.external_irreversible),
        read_only: pick('readOnly', DEFAULT_POLICY.read_only),
        routine_dev: pick('routineDev', DEFAULT_POLICY.routine_dev),
        exemptPrefixes,
        authorizedOperations: authorizedList,
    };
}
// No `z<Config>` annotation: `.volatile()` brands the projected value type, so
// an explicit annotation fights the inference. The `Config` interface above
// stays the runtime shape `apply()` reads; first-party volatile plugins
// (web-search-deepseek, pwsh-local) infer the same way.
export const Config = z.object({
    judgeProvider: z.union(['dsh-llm', 'typesafe'])
        .description('The judge. typesafe (default): calibrated probabilities, sub-second, needs TYPESAFE_API_KEY; a region-blocked network needs typesafeProxy (HTTP 451). dsh-llm: the session\'s own configured model source, no endpoint of its own — pick a fast model, every call waits for it.')
        .default('typesafe')
        .volatile(),
    model: z.string()
        .description('Judge model id. Empty follows the backend default: the session\'s live model on dsh-llm, jev-1.13.0 on typesafe.')
        .default('')
        .volatile(),
    // Inner fields stay optional: schemastery validates an absent object's inner
    // shape too, so `.required()` here would reject every config that omits
    // judgeRoute. The runtime pins a route only when both fields are non-empty.
    // Mirrors agent-default-model's provider/model route object.
    judgeRoute: z.object({
        provider: z.string().volatile()
            .description('Provider route to pin, e.g. claude-corp.'),
        model: z.string().volatile()
            .description('Model id to pin, e.g. claude-haiku-4-5-20251001.'),
    }).description('Pin both provider and model for the dsh-llm judge. Unset follows the session\'s live route.'),
    matcher: z.string()
        .description('Tool-name pattern this gate watches.')
        .default(DEFAULT_MATCHER)
        .volatile(),
    logPath: z.string()
        .description('JSONL decision log path; empty means the plugin directory.')
        .default('')
        .volatile(),
    // The TypeSafe key, configured like any provider credential: the settings
    // form edits it masked, the platform credential store holds it, and it
    // never rides a response. `typesafeApiKeyEnv` names a fallback environment
    // variable; the Windows User environment is the last resort.
    typesafeApiKey: z.string().role('secret')
        .description('TypeSafe API key for the typesafe judge. Stored as a secret; leave empty to use the environment variable instead.')
        .volatile(),
    typesafeApiKeyEnv: z.string()
        .description('Environment variable holding the TypeSafe key when none is configured.')
        .default('TYPESAFE_API_KEY')
        .volatile(),
    typesafeProxy: z.string()
        .description('Proxy URL for the typesafe judge (e.g. http://proxy.example:8080), for networks where TypeSafe is region-blocked (HTTP 451). Empty reads HTTP_PROXY/HTTPS_PROXY, then connects directly.')
        .default('')
        .volatile(),
    destructive: z.number().step(0.01).min(0).max(1)
        .description('Destructive threshold; a destructive verdict at or above it is denied, downgraded to ask inside the exempt prefixes.')
        .default(DEFAULT_POLICY.destructive)
        .volatile(),
    secretExposure: z.number().step(0.01).min(0).max(1)
        .description('Secret-exposure threshold; at or above it the call is denied, never downgraded.')
        .default(DEFAULT_POLICY.secret_exposure)
        .volatile(),
    externalIrreversible: z.number().step(0.01).min(0).max(1)
        .description('External-irreversible threshold; at or above it the call asks.')
        .default(DEFAULT_POLICY.external_irreversible)
        .volatile(),
    readOnly: z.number().step(0.01).min(0).max(1)
        .description('Read-only threshold; at or above it the call is allowed.')
        .default(DEFAULT_POLICY.read_only)
        .volatile(),
    routineDev: z.number().step(0.01).min(0).max(1)
        .description('Routine-development threshold; at or above it the call is allowed.')
        .default(DEFAULT_POLICY.routine_dev)
        .volatile(),
    exemptPrefixes: z.array(z.string())
        .description('Path prefixes where a destructive verdict downgrades to ask; an empty array disables the exemption.')
        .default([...DEFAULT_EXEMPT_PREFIXES])
        .volatile(),
    authorizedOperations: z.array(z.string())
        .description('Exact commands whose external-irreversible ask is downgraded to allow, so a pre-approved irreversible step does not ask every run. Statement-level match, and it never downgrades a secret-exposure or destructive verdict. Empty disables it.')
        .default([])
        .volatile(),
});
export const name = 'decision-gate';
export const inject = ['tools', 'llm'];
function isConfigRef(value) {
    return typeof value === 'object' && value !== null
        && typeof value.get === 'function';
}
/** Resolve a reference chain to its current value; a bare value passes through. */
function configValue(value) {
    let current = value;
    while (isConfigRef(current))
        current = current.get();
    return current;
}
export function apply(ctx, rawConfig) {
    const config = rawConfig !== null && typeof rawConfig === 'object'
        ? rawConfig
        : {};
    // Every field is read per use through the reference, so a config edit made
    // in the settings card applies to the next gated call without a restart.
    let matcher = null;
    let matcherSource = '';
    const judgeName = () => {
        const provider = configValue(config.judgeProvider);
        return provider === 'dsh-llm' || provider === 'typesafe' ? provider : DEFAULT_JUDGE;
    };
    const judgeModel = () => {
        const value = configValue(config.model);
        return typeof value === 'string' ? value : '';
    };
    const pinnedRoute = () => {
        const route = configValue(config.judgeRoute);
        if (route === null || typeof route !== 'object')
            return null;
        const provider = configValue(route.provider);
        const model = configValue(route.model);
        return typeof provider === 'string' && provider !== '' && typeof model === 'string' && model !== ''
            ? { provider, model }
            : null;
    };
    const logPath = () => {
        const value = configValue(config.logPath);
        return typeof value === 'string' && value !== '' ? value : DEFAULT_LOG;
    };
    const typesafeEnvName = () => {
        const value = configValue(config.typesafeApiKeyEnv);
        return typeof value === 'string' && value !== '' ? value : 'TYPESAFE_API_KEY';
    };
    const typesafeKey = () => resolveApiKey(() => {
        const value = configValue(config.typesafeApiKey);
        return typeof value === 'string' ? value : '';
    }, typesafeEnvName());
    const typesafeProxy = () => {
        const value = configValue(config.typesafeProxy);
        return typeof value === 'string' ? value : '';
    };
    const currentPolicy = () => policyFrom({
        destructive: configValue(config.destructive),
        secretExposure: configValue(config.secretExposure),
        externalIrreversible: configValue(config.externalIrreversible),
        readOnly: configValue(config.readOnly),
        routineDev: configValue(config.routineDev),
        exemptPrefixes: configValue(config.exemptPrefixes),
        authorizedOperations: configValue(config.authorizedOperations),
    });
    /** Statement-level match; see {@link isAuthorizedMatch} for the rules. */
    const isAuthorized = isAuthorizedMatch;
    const watchMatcher = () => {
        const source = configValue(config.matcher);
        const next = typeof source === 'string' && source !== '' ? source : DEFAULT_MATCHER;
        if (matcher !== null && next === matcherSource)
            return matcher;
        try {
            matcher = new RegExp(next);
            matcherSource = next;
            return matcher;
        }
        catch {
            ctx.logger.warn(`decision-gate: invalid matcher "${next}"; calls are not gated until it parses`);
            matcherSource = next;
            matcher = null;
            return null;
        }
    };
    // Warm the key at load so the first gated call does not pay the registry
    // read. Only the typesafe backend needs it; the dsh-llm backend rides on
    // credentials DSH already resolved.
    if (judgeName() === 'typesafe') {
        try {
            resolveApiKey(() => {
                const value = configValue(config.typesafeApiKey);
                return typeof value === 'string' ? value : '';
            }, typesafeEnvName());
        }
        catch {
            // resolveApiKey never throws; kept for symmetry with the judge path
        }
    }
    ctx.effect(function* () {
        yield ctx.on('tools/pre-execute', async (exec, next) => {
            const matcherNow = watchMatcher();
            if (matcherNow === null || !matcherNow.test(exec.name))
                return next();
            const started = Date.now();
            const provider = judgeName();
            // `model` is relative to the judge backend: for `typesafe` it is the
            // SystemOne model id (jev-1.13.0 by default); for `dsh-llm` an empty
            // value means "follow the session's live route", resolved per call.
            const model = judgeModel() !== '' ? judgeModel() : (provider === 'typesafe' ? DEFAULT_TYPESAFE_MODEL : '');
            const policy = currentPolicy();
            const record = {
                at: new Date().toISOString(),
                tool: exec.name,
                session_id: sessionIdOf(exec),
                cwd: sessionCwd(exec),
                // Recorded on every row, including the fail-open error path: a signal
                // is only comparable to another signal if both came from the same
                // pinned model, and TypeSafe's own calibration guidance is to pin the
                // version before drawing any conclusion from your own data.
                judge: provider,
                model: model === '' ? '(session route)' : model,
            };
            try {
                const state = buildState(exec);
                record.arguments = state.tool_call.arguments;
                let signals;
                if (provider === 'typesafe') {
                    const body = await judgeTypesafe(state, model, typesafeKey(), resolveProxyAgent(typesafeProxy()), exec.signal);
                    if (body.answers === undefined)
                        throw new Error('response carried no answers object');
                    signals = toSignals(body.answers);
                }
                else {
                    const route = pinnedRoute() ?? sessionRoute(exec);
                    if (route === null) {
                        throw new Error('no judge route: the session request header carries no provider/model and config.judgeRoute pins none');
                    }
                    record.provider = route.provider;
                    record.model = model === '' ? route.model : model;
                    signals = await judgeDshLlm(ctx, state, {
                        provider: route.provider,
                        model: model === '' ? route.model : model,
                    }, exec.signal);
                }
                const command = exec.arguments?.command;
                const exempt = typeof command === 'string'
                    ? isExempt(command, policy.exemptPrefixes, sessionCwd(exec))
                    : false;
                // Whole-command match against the pre-authorized list: the command
                // text must equal an entry after whitespace normalization, so a
                // whitelisted string carried inside a longer command never matches.
                const authorized = typeof command === 'string'
                    ? isAuthorized(command, policy.authorizedOperations)
                    : false;
                const decision = decide(signals, policy, exempt, authorized);
                record.signals = signals;
                record.action = decision.action;
                record.rule = decision.rule;
                if (exempt)
                    record.exempt = true;
                if (authorized)
                    record.authorized = true;
                record.duration_ms = Date.now() - started;
                appendLog(record, logPath());
                if (decision.action === 'deny')
                    return { kind: 'deny', reason: decision.reason };
                if (decision.action === 'ask')
                    return { kind: 'ask', reason: decision.reason };
                return next();
            }
            catch (error) {
                record.error = `${error instanceof Error ? error.name : 'Error'}: ${String(error)}`;
                record.duration_ms = Date.now() - started;
                appendLog(record, logPath());
                ctx.logger.warn(`decision-gate: ${record.error}; allowing "${exec.name}" through`);
                return next();
            }
        });
    }, 'decision-gate lifecycle');
}
