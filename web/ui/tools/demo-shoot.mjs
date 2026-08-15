// Drives the app through idle -> sample run -> every tab, at desktop and
// mobile widths, and verifies seek/play interactions. Re-run after fixes.
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '.shots')
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const BASE = process.argv[2] || '' + BASE + ''
const errs = []

async function newPage(w, h) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 })
  page.on('console', (m) => m.type() === 'error' && errs.push('console: ' + m.text()))
  page.on('pageerror', (e) => errs.push('pageerror: ' + String(e)))
  page.on('requestfailed', (r) => errs.push('requestfailed: ' + r.url() + ' ' + (r.failure()?.errorText ?? '')))
  return page
}

const results = {}

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
const wordSpans = desk.locator('p span[title]')
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

// download interaction: clicking Download triggers a blob download — verify a dialog-less download event
const dl = desk.waitForEvent('download', { timeout: 5000 }).catch(() => null)
await desk.getByRole('button', { name: /Download/ }).first().click()
const dlEvent = await dl
results.download = { ok: !!dlEvent, name: dlEvent ? dlEvent.suggestedFilename() : null }

results.consoleErrors = errs
console.log(JSON.stringify(results, null, 2))
await browser.close()
