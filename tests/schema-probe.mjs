// Throwaway: does the exported Config look like a schemastery node to the code
// in packages/settings/settings/src/schema.ts? Delete after use.
import { Config } from '../lib/index.js'

const live = Config
console.log('live object keys:', Object.keys(live).slice(0, 20).join(', '))
console.log('live.type:       ', live.type)
console.log('live.meta:       ', JSON.stringify(live.meta))
console.log('live.dict size:  ', live.dict ? Object.keys(live.dict).length : '(no dict)')
console.log('has toJSON:      ', typeof live.toJSON === 'function')

const j = live.toJSON()
console.log('')
console.log('toJSON keys:     ', Object.keys(j).join(', '))
console.log('toJSON.type:     ', j.type)
console.log('toJSON.meta:     ', JSON.stringify(j.meta))
console.log('toJSON.dict size:', j.dict ? Object.keys(j.dict).length : '(no dict)')

// Which children carry meta.volatile?
if (j.dict) {
  const vol = Object.entries(j.dict).filter(([, f]) => f?.meta?.volatile).map(([k]) => k)
  const non = Object.entries(j.dict).filter(([, f]) => !f?.meta?.volatile).map(([k]) => k)
  console.log('')
  console.log('volatile children:     ', vol.join(', ') || '(none)')
  console.log('non-volatile children: ', non.join(', ') || '(none)')
}
