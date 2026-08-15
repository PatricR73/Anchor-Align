// usage: node tools/payload-budget.mjs [base] [fixture]
// P6 regression guard: the /api/align response for the 9,000-word large
// fixture must stay under a stated ceiling. The fixture payload is the
// worst case the renderer ever parses (9000 aligned words + 691 cues +
// issues + stats), so a payload-shape change that bloats it past the
// ceiling is a regression regardless of how the UI looks.
//
// Ceiling (measured 2026-08-16, P6):
//   raw  1,548,233 B  ->  ceiling 1,900,000 B  (+23%)
//   wire   219,688 B  ->  ceiling   280,000 B  (+27%)
// Justification: the fixture is seeded and frozen, so the measurement is
// exact, not a sample. The ceiling is deliberately BELOW the size of the
// known payload-shape regression it must catch: the full fixture on disk is
// 1,984,950 B raw / 297,816 B gzipped — that is exactly the served payload
// plus download_content (the VTT/SRT/confidence strings the API pops out
// and serves separately). If a future change re-inlines those strings into
// the align response (or duplicates aligned), the payload jumps to the disk
// size and the budget fires. 23% headroom still covers a deliberate new
// per-word field (9000 words x ~20 B = ~180 KB) without a review; anything
// past the disk size is duplicated data, not a shape change.
//
// "wire" is the compressed transfer size (GZipMiddleware on the API); the
// browser holds the decompressed "raw" bytes in memory and the renderer
// walks them every frame, so both matter.
import { chromium } from 'playwright'

const BASE = process.argv[2] || 'http://127.0.0.1:5173'
const FIXTURE = process.argv[3] || 'large'

const RAW_CEILING = 1_900_000
const WIRE_CEILING = 280_000

const browser = await chromium.launch()
const page = await browser.newPage()
// navigate first so the fetch runs from a real origin (a blank page cannot fetch)
await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 30_000 }).catch(() => {})
const url = BASE + '/api/sample?fixture=' + FIXTURE
// fetch in the page: node's undici fetch has a flaky teardown race
// (assert(!this.paused)) on gzipped responses in this Node version
const m = await page.evaluate(async (u) => {
  const t0 = performance.now()
  const res = await fetch(u)
  const blob = await res.blob()
  const dt = performance.now() - t0
  // wire size from resource timing (transferSize = compressed bytes on the wire)
  const entries = performance.getEntriesByName(u)
  const transferSize = entries.length ? entries[0].transferSize : null
  return {
    status: res.status,
    raw: blob.size,
    wire: transferSize,
    fetchMs: Math.round(dt),
    contentType: res.headers.get('content-type'),
  }
}, url)
await browser.close()

const failures = []
if (m.status !== 200) failures.push('HTTP ' + m.status + ' (expected 200)')
if (m.raw > RAW_CEILING) failures.push('raw ' + m.raw + ' B > ceiling ' + RAW_CEILING + ' B')
if (m.wire !== null && m.wire > WIRE_CEILING) failures.push('wire ' + m.wire + ' B > ceiling ' + WIRE_CEILING + ' B')

console.log(JSON.stringify({
  tool: 'payload-budget',
  url,
  measured: m,
  ceilings: { raw: RAW_CEILING, wire: WIRE_CEILING },
  ok: failures.length === 0,
  failures,
}, null, 2))

if (failures.length > 0) process.exit(1)
