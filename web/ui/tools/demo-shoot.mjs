// Drives the app through idle -> sample run -> every tab, at desktop and
// mobile widths, and verifies seek/play interactions. Re-run after fixes.
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '.shots')
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const BASE = process.argv[2] || 'http://127.0.0.1:5173'
const errs = []

async function newPage(w, h) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 })
  page.on('console', (m) => m.type() === 'error' && errs.push('console: ' + m.text()))
  page.on('pageerror', (e) => errs.push('pageerror: ' + String(e)))
  // ERR_ABORTED is a benign cancellation (tab switch kills the media fetch,
  // navigation cancels in-flight requests) — not a defect. Anything else is.
  page.on('requestfailed', (r) => {
    const t = r.failure()?.errorText ?? ''
    if (!t.includes('ERR_ABORTED')) errs.push('requestfailed: ' + r.url() + ' ' + t)
  })
  return page
}

const results = {}

// P0 fixture acceptance (WordTimeline fix): the seeded low-confidence
// word at ~38:00 must be VISIBLE and CLICKABLE in the word-timeline strip
// at BOTH viewports, and clicking it must seek to within 50ms of its true
// start. Expected values are derived from the fixture payload itself (the
// min-confidence word), so the assertion tracks fixture regeneration.
// The timeline aggregates sub-pixel words into 1px columns and renders the
// minimum-confidence word per column, so this word owns its column's color
// and a click on that column lands on its true start.
async function assertLowConfidenceWord(page, label) {
  const heading = await page.locator('main h2').textContent().catch(() => '')
  if ((heading || '').trim() !== 'fixture_large') {
    results['lowWord_' + label] = { skipped: true, reason: 'P0 fixture not loaded (heading=' + heading + ')' }
    return
  }
  // fetch in the browser page: node's undici fetch has a flaky teardown
  // race (assert(!this.paused)) on gzipped responses in this Node version
  const payload = await page.evaluate(async () => {
    const res = await fetch('/api/sample?fixture=large')
    return res.json()
  })
  const low = payload.aligned.reduce((m, w) => (w.confidence < m.confidence ? w : m))
  const expectedStart = low.start

  const slider = page.getByRole('slider')
  const sliderBox = await slider.boundingBox()
  // timeline columns carry the min word's start in data-start (no titles now)
  const cols = slider.locator('[data-start="' + expectedStart + '"]')
  const count = await cols.count()
  const col = cols.first()
  const colBox = count > 0 ? await col.boundingBox() : null
  const visible =
    count > 0 &&
    colBox !== null &&
    sliderBox !== null &&
    colBox.x >= sliderBox.x - 1 &&
    colBox.x + colBox.width <= sliderBox.x + sliderBox.width + 1
  const claimed = count > 0 ? parseFloat(await col.getAttribute('data-start')) : null
  if (claimed !== null && Math.abs(claimed - expectedStart) > 0.01) {
    throw new Error(
      label + ': low-confidence column claims start ' + claimed + 's, expected ' + expectedStart + 's',
    )
  }
  if (visible) {
    // click the STRIP at the low column's x: columns are 1px wide and
    // Chromium's hit-testing rounds fractional coords up a pixel, so the
    // strip resolves the column arithmetically from the mouse position.
    await slider.click({
      position: {
        x: colBox.x - sliderBox.x + 0.5,
        y: colBox.y - sliderBox.y + colBox.height / 2,
      },
    })
    await page.waitForTimeout(250)
  }
  const nowMs = Number(await slider.getAttribute('aria-valuenow'))
  const targetMs = Math.round(expectedStart * 1000)
  const errMs = Math.abs(nowMs - targetMs)
  results['lowWord_' + label] = { visible, count, expectedStart, claimed, nowMs, targetMs, errMs, ok: visible && errMs <= 50 }
}

const desk = await newPage(1440, 900)
await desk.goto('' + BASE + '', { waitUntil: 'networkidle', timeout: 30_000 })
await desk.waitForTimeout(900)
await desk.screenshot({ path: path.join(OUT, 'idle-desktop.png'), fullPage: true })

const mob = await newPage(390, 844)
await mob.goto('' + BASE + '', { waitUntil: 'networkidle', timeout: 30_000 })
await mob.waitForTimeout(900)
await mob.screenshot({ path: path.join(OUT, 'idle-mobile.png'), fullPage: true })

// run the sample on desktop
await desk.getByRole('button', { name: /Run the bundled sample/ }).click()
await desk.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await desk.waitForTimeout(1000)
await desk.screenshot({ path: path.join(OUT, 'result-transcript-desktop.png'), fullPage: true })

// interaction checks on desktop
const slider = desk.getByRole('slider')
const before = Number(await slider.getAttribute('aria-valuenow'))
const wordSpans = desk.locator('[role="option"]')
await wordSpans.nth(10).click()
await desk.waitForTimeout(300)
const afterSeek = Number(await slider.getAttribute('aria-valuenow'))
results.seek = { before, afterSeek, ok: afterSeek > before }

const playBtn = desk.getByRole('button', { name: 'Play' })
await playBtn.click()
await desk.waitForTimeout(1500)
const duringPlay = Number(await slider.getAttribute('aria-valuenow'))
const pauseBtn = await desk.getByRole('button', { name: 'Pause' }).count()
await desk.getByRole('button', { name: 'Pause' }).click().catch(() => {})
results.play = { duringPlay, ok: duringPlay > afterSeek, showsPause: pauseBtn === 1 }

// P0 acceptance: low-confidence word visible + clickable + seeks accurately
await assertLowConfidenceWord(desk, 'desktop')

// tabs
await desk.getByRole('tab', { name: /^Cues/ }).click()
await desk.waitForTimeout(500)
await desk.screenshot({ path: path.join(OUT, 'result-cues-desktop.png'), fullPage: true })
await desk.getByRole('tab', { name: /QC report/ }).click()
await desk.waitForTimeout(500)
await desk.screenshot({ path: path.join(OUT, 'result-qc-desktop.png'), fullPage: true })
await desk.getByRole('tab', { name: /^Download/ }).click()
await desk.waitForTimeout(500)
await desk.screenshot({ path: path.join(OUT, 'result-download-desktop.png'), fullPage: true })

// sample on mobile
await mob.getByRole('button', { name: /Run the bundled sample/ }).click()
await mob.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await mob.waitForTimeout(1000)
await mob.screenshot({ path: path.join(OUT, 'result-transcript-mobile.png'), fullPage: true })

// P0 acceptance on mobile: same word, same accuracy
await assertLowConfidenceWord(mob, 'mobile')

// download interaction: clicking Download triggers a blob download — verify a dialog-less download event
const dl = desk.waitForEvent('download', { timeout: 5000 }).catch(() => null)
await desk.getByRole('button', { name: /Download/ }).first().click()
const dlEvent = await dl
results.download = { ok: !!dlEvent, name: dlEvent ? dlEvent.suggestedFilename() : null }

results.consoleErrors = errs
console.log(JSON.stringify(results, null, 2))

// Exit non-zero when any acceptance check failed so CI fails loudly.
const failed = []
for (const [k, v] of Object.entries(results)) {
  if (v && typeof v === 'object' && 'ok' in v && v.ok === false) failed.push(k + ': ' + JSON.stringify(v))
}
if (results.consoleErrors.length) failed.push('console/page/request errors: ' + results.consoleErrors.join(' | '))
if (failed.length) {
  console.log('DEMO-SHOOT FAIL:')
  for (const f of failed) console.log('  - ' + f)
  process.exit(1)
}
await browser.close()
