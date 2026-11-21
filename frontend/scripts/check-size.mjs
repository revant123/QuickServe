// Performance budget: how much JavaScript a phone downloads before the first
// screen works. Fails the build (and CI) if it grows past the budget.
// Why a budget at all: see the README, Phase 13 ("How big is the app?").
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'

const BUDGET_KB = 150 // gzipped JS on first load
const dist = new URL('../dist/', import.meta.url).pathname
const html = readFileSync(join(dist, 'index.html'), 'utf8')
const files = [...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.js)"/g)].map((m) => m[1])

let total = 0
for (const f of files) {
  const kb = gzipSync(readFileSync(join(dist, f))).length / 1024
  total += kb
  console.log(`${kb.toFixed(1).padStart(7)} KB  ${f}`)
}
console.log(`${total.toFixed(1).padStart(7)} KB  first-load JavaScript (gzipped), budget ${BUDGET_KB} KB`)
if (total > BUDGET_KB) {
  console.error(`Over budget by ${(total - BUDGET_KB).toFixed(1)} KB`)
  process.exit(1)
}
