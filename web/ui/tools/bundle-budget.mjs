// usage: node tools/bundle-budget.mjs [distDir]
// P7 regression guard: the built frontend bundle (JS + CSS) must stay under
// a stated ceiling. The bundle is what every user downloads to render the
// app, so unbudgeted growth (a new dependency, an import that drags in a
// chunk, a vendored asset) is a regression even when the UI is unchanged.
//
// Ceiling (measured 2026-08-16, P7, after `npm run build`):
//   raw JS+CSS   412,932 B  ->  ceiling 550,000 B  (+33%)
//   gz  JS+CSS   127,673 B  ->  ceiling 180,000 B  (+41%)
// Justification: measured on the built dist (JS 387,913 + CSS 25,019;
// gzip 121,786 + 5,887). Headroom covers one new dependency the size of
// the current largest (motion/react) plus Tailwind class growth from new
// screens, without a review. Fonts are excluded: they are static, hashed
// assets served separately, and the latin-only subset is a deliberate
// decision (documented in web/ui/src/index.css), not part of the bundle.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { gzipSync } from 'node:zlib'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const dist = path.resolve(process.argv[2] || path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'dist'))
const RAW_CEILING = 550_000
const GZ_CEILING = 180_000

if (!statSync(dist).isDirectory()) {
  console.error('bundle-budget: no dist directory at ' + dist + ' — run `npm run build` first')
  process.exit(1)
}

const assets = readdirSync(path.join(dist, 'assets'))
const files = assets.filter((f) => f.endsWith('.js') || f.endsWith('.css')).map((f) => {
  const p = path.join(dist, 'assets', f)
  const buf = readFileSync(p)
  return { name: f, raw: buf.length, gz: gzipSync(buf).length }
})

const totals = files.reduce((acc, f) => ({ raw: acc.raw + f.raw, gz: acc.gz + f.gz }), { raw: 0, gz: 0 })

const failures = []
if (totals.raw > RAW_CEILING) failures.push('raw ' + totals.raw + ' B > ceiling ' + RAW_CEILING + ' B')
if (totals.gz > GZ_CEILING) failures.push('gz ' + totals.gz + ' B > ceiling ' + GZ_CEILING + ' B')

console.log(JSON.stringify({
  tool: 'bundle-budget',
  dist,
  files,
  totals,
  ceilings: { raw: RAW_CEILING, gz: GZ_CEILING },
  ok: failures.length === 0,
  failures,
}, null, 2))

if (failures.length > 0) process.exit(1)
