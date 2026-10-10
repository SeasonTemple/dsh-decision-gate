// Functional test of the gate against the built lib, with a fake cordis
// Context whose llm.stream returns scripted StreamChunks. Covers both judge
// backends, the volatile-reference config shape the loader actually delivers
// (`config.field.get()`), the fail-open paths, and the decision log.
//
// Run with plain node: node tests/functional.mjs   (no build, no network)

import { rmSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { apply, resolveProxyAgent } from '../lib/index.js'

const LOG = fileURLToPath(new URL('../runtime/fake-decisions.jsonl', import.meta.url))
rmSync(LOG, { force: true })

// The loader hands a volatile config as live references, not bare values
// (first-party plugins read `config.field.get()`). Wrap every value — nested
// objects one level deep — so these tests exercise the real delivery shape:
// reading them as bare values silently dropped every key to its default, the
// bug this file now guards.
function refs(config) {
  const out = {}
  for (const [key, value] of Object.entries(config)) {
    out[key] = value !== null && typeof value === 'object' && !Array.isArray(value)
      ? { get: () => refs(value) }
      : { get: () => value }
  }
  return out
}

function makeCtx(script) {
  const listeners = []
  const warns = []
  const ctx = {
    logger: { warn: (m) => warns.push(m) },
    on: (event, listener) => { listeners.push({ event, listener }); return () => {} },
    effect: (fn) => { fn().next() },
    llm: { stream: (options) => script(options) },
  }
  return { ctx, listeners, warns }
}

async function* scripted(text, finish = { kind: 'stop' }) {
  for (const piece of (text.match(/.{1,20}/gs) ?? [])) {
    yield { type: 'text-delta', index: 0, text: piece }
  }
  yield { type: 'finish', reason: finish }
}

const SIGNALS = (o) => JSON.stringify(o)
const DESTRUCTIVE = { read_only: 0.02, destructive: 0.94, secret_exposure: 0.02, external_irreversible: 0.03, routine_dev: 0.08 }
const ROUTINE = { read_only: 0.04, destructive: 0.08, secret_exposure: 0.15, external_irreversible: 0.08, routine_dev: 0.96 }

const exec = {
  name: 'pwsh',
  arguments: { command: 'rm -rf /' },
  agent: {
    id: 'session-1',
    session: {
      cwd: 'C:/example/proj',
      requestHeader: () => ({ config: { provider: 'deepseek', model: 'deepseek-chat' } }),
    },
  },
}

let failures = 0
const check = (name, ok, detail) => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : ' -- ' + detail}`)
  if (!ok) failures += 1
}

// 1. destructive judge -> deny, routed through the session's provider/model
{
  let seenOptions = null
  const { ctx, listeners } = makeCtx((options) => { seenOptions = options; return scripted(SIGNALS(DESTRUCTIVE)) })
  apply(ctx, refs({ judgeProvider: 'dsh-llm', logPath: LOG }))
  const listener = listeners[0].listener
  const decision = await listener(exec, async () => ({ kind: 'allow' }))
  check('destructive judge denies', decision.kind === 'deny' && /destroy data/.test(decision.reason), JSON.stringify(decision))
  check('route follows session request header', seenOptions?.provider === 'deepseek' && seenOptions?.model === 'deepseek-chat', JSON.stringify(seenOptions))
  check('system prompt carries the protocol', /exactly one JSON object/.test(seenOptions?.system ?? ''), 'system')
  check('user turn carries the command', /rm -rf \//.test(seenOptions?.messages?.[0]?.content?.[0]?.text ?? ''), 'messages')
}

// 2. routine judge -> allow, calls next()
{
  const { ctx, listeners } = makeCtx(() => scripted(SIGNALS(ROUTINE)))
  apply(ctx, refs({ judgeProvider: 'dsh-llm', logPath: LOG }))
  let nexted = false
  const decision = await listeners[0].listener(exec, async () => { nexted = true; return { kind: 'allow' } })
  check('routine judge allows via next()', decision.kind === 'allow' && nexted, JSON.stringify(decision))
}

// 3. judge stream error -> fail open, logs the error
{
  const { ctx, listeners, warns } = makeCtx(() => scripted('', { kind: 'error', failure: { code: 'UNKNOWN', message: 'provider unavailable' } }))
  apply(ctx, refs({ judgeProvider: 'dsh-llm', logPath: LOG }))
  let nexted = false
  const decision = await listeners[0].listener(exec, async () => { nexted = true; return { kind: 'allow' } })
  check('judge failure fails open', decision.kind === 'allow' && nexted, JSON.stringify(decision))
  check('judge failure warns', warns.some((w) => /provider unavailable/.test(w)), warns.join('|'))
}

// 4. malformed judge output -> fail open
{
  const { ctx, listeners } = makeCtx(() => scripted('not json at all'))
  apply(ctx, refs({ judgeProvider: 'dsh-llm', logPath: LOG }))
  let nexted = false
  const decision = await listeners[0].listener(exec, async () => { nexted = true; return { kind: 'allow' } })
  check('malformed judge output fails open', decision.kind === 'allow' && nexted, JSON.stringify(decision))
}

// 5. no session route and no pin -> fail open with a logged reason
{
  const noHeader = { name: 'pwsh', arguments: { command: 'ls' }, agent: { id: 's', session: { cwd: 'C:/example/x' } } }
  const { ctx, listeners } = makeCtx(() => scripted(SIGNALS(ROUTINE)))
  apply(ctx, refs({ judgeProvider: 'dsh-llm', logPath: LOG }))
  let nexted = false
  const decision = await listeners[0].listener(noHeader, async () => { nexted = true; return { kind: 'allow' } })
  check('missing route fails open', decision.kind === 'allow' && nexted, JSON.stringify(decision))
}

// 6. pinned route wins over the session header
{
  let seenOptions = null
  const { ctx, listeners } = makeCtx((options) => { seenOptions = options; return scripted(SIGNALS(ROUTINE)) })
  apply(ctx, refs({ judgeProvider: 'dsh-llm', logPath: LOG, judgeRoute: { provider: 'claude-corp', model: 'claude-haiku-4-5-20251001' } }))
  await listeners[0].listener(exec, async () => ({ kind: 'allow' }))
  check('pinned route overrides session header', seenOptions?.provider === 'claude-corp' && seenOptions?.model === 'claude-haiku-4-5-20251001', JSON.stringify(seenOptions))
}

// 7. pinned model id overrides the session model
{
  let seenOptions = null
  const { ctx, listeners } = makeCtx((options) => { seenOptions = options; return scripted(SIGNALS(ROUTINE)) })
  apply(ctx, refs({ judgeProvider: 'dsh-llm', logPath: LOG, model: 'k3-256k' }))
  await listeners[0].listener(exec, async () => ({ kind: 'allow' }))
  check('config.model overrides session model', seenOptions?.model === 'k3-256k', JSON.stringify(seenOptions))
}

// 8. typesafe backend still selected explicitly and needs no ctx.llm
{
  const { ctx, listeners } = makeCtx(() => { throw new Error('dsh-llm must not be used when typesafe is selected') })
  apply(ctx, refs({ judgeProvider: 'typesafe', logPath: LOG, matcher: '^nothing-matches$' }))
  check('typesafe backend registers without touching ctx.llm', listeners.length === 1, String(listeners.length))
}

// 9. the log records the judge identity on every row — and lands at the
// configured path, which is the reference-read regression in miniature
{
  const rows = readFileSync(LOG, 'utf8').trim().split('\n').map((line) => JSON.parse(line))
  check('every row records judge + model', rows.every((r) => r.judge === 'dsh-llm' && typeof r.model === 'string'), JSON.stringify(rows.map((r) => [r.judge, r.model])))
  check('rows carry provider', rows.some((r) => r.provider === 'deepseek' || r.provider === 'claude-corp'), JSON.stringify(rows.map((r) => r.provider)))
}

// 10. proxy agent candidates for the typesafe backend (the region-block path)
{
  const hadHttp = process.env.HTTP_PROXY
  const hadHttps = process.env.HTTPS_PROXY
  delete process.env.HTTP_PROXY
  delete process.env.HTTPS_PROXY
  check('explicit proxy builds an agent', resolveProxyAgent('http://proxy.example:8080') !== null)
  check('no config and no env is a direct connection', resolveProxyAgent('') === null)
  process.env.HTTPS_PROXY = 'http://proxy.invalid:8080'
  check('env proxy builds an agent', resolveProxyAgent('') !== null)
  if (hadHttp === undefined) delete process.env.HTTP_PROXY; else process.env.HTTP_PROXY = hadHttp
  if (hadHttps === undefined) delete process.env.HTTPS_PROXY; else process.env.HTTPS_PROXY = hadHttps
}

console.log(`\nfunctional tests, failures: ${failures}`)
console.log(`EXIT_CODE=${failures === 0 ? 0 : 1}`)
