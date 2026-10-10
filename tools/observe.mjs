// Observation report for the calibration watch period: reads the decision
// log and prints what a threshold review needs — decision distribution,
// judge health (error rate), near-miss allows (a dangerous-looking signal
// below the threshold), and the recent denials/asks for false-deny review.
//
// Usage: node tools/observe.mjs [logPath] [--rows N]
// Default log: <pkg>/runtime/decisions.jsonl, report over the last 500 rows.

import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const args = process.argv.slice(2)
const rowsFlag = args.indexOf('--rows')
const limit = rowsFlag >= 0 ? Number(args[rowsFlag + 1]) : 500
const logPath = args.find((argument) => !argument.startsWith('--') && argument !== args[rowsFlag + 1])
  ?? fileURLToPath(new URL('../runtime/decisions.jsonl', import.meta.url))

if (!existsSync(logPath)) {
  console.log(`no log at ${logPath}`)
  process.exit(0)
}

const rows = readFileSync(logPath, 'utf8').trim().split('\n')
  .map((line) => { try { return JSON.parse(line) } catch { return null } })
  .filter((row) => row !== null)
  .slice(-limit)

const tally = (key) => rows.reduce((out, row) => {
  const value = row[key] ?? '(none)'
  out[value] = (out[value] ?? 0) + 1
  return out
}, {})

console.log(`log: ${logPath}`)
console.log(`rows: ${rows.length} (window ${limit})`)
console.log('by judge:', JSON.stringify(tally('judge')))
console.log('by action:', JSON.stringify(tally('action')))
console.log('by rule:', JSON.stringify(tally('rule')))

const errors = rows.filter((row) => row.error !== undefined)
console.log(`judge errors: ${errors.length} (${errors.length === 0 ? 'healthy' : 'LAST: ' + errors.at(-1).error})`)

const NEAR_MISS = 0.3
const nearMiss = rows.filter((row) => row.signals !== undefined
  && (row.action === 'allow' || row.action === undefined)
  && (row.signals.destructive >= NEAR_MISS || row.signals.secret_exposure >= NEAR_MISS))
console.log(`\nnear-miss allows (destructive|secret >= ${NEAR_MISS}): ${nearMiss.length}`)
for (const row of nearMiss.slice(-10)) {
  const command = row.arguments?.command ?? ''
  console.log(`  ${row.at} des=${row.signals.destructive} sec=${row.signals.secret_exposure} ${command.slice(0, 80)}`)
}

const blocked = rows.filter((row) => row.action === 'deny' || row.action === 'ask')
console.log(`\nrecent blocked (review for false denies): ${blocked.length}`)
for (const row of blocked.slice(-10)) {
  const command = row.arguments?.command ?? ''
  console.log(`  ${row.at} ${row.action} ${row.rule} ${command.slice(0, 80)}`)
}
