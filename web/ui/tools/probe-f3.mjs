// F3 verification: the playhead and the segments must agree. The playhead is
// now ref-driven (written outside React by usePlayback), so it only moves
// through the app's real paths: keyboard seeks on the slider, word/timeline
// clicks, and the playback rAF loop. This probe exercises exactly those.
import { chromium } from 'playwright'

const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://127.0.0.1:5173/?fixture=large', { waitUntil: 'networkidle', timeout: 30_000 })
await p.getByRole('button', { name: /Run the bundled sample/ }).click()
await p.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await p.waitForTimeout(1000)

const slider = p.getByRole('slider')
const box = await slider.boundingBox()
const readPlayhead = () => slider.evaluate((el) => {
  const ph = el.querySelector('[data-playhead]')
  const pr = ph.getBoundingClientRect()
  const sr = el.getBoundingClientRect()
  return pr.left - sr.left
})

const results = {}

// keyboard Home -> 0%
await slider.focus()
await p.keyboard.press('Home')
await p.waitForTimeout(150)
results.zero = { playheadPx: Math.round((await readPlayhead()) * 10) / 10, expected: 0 }

// keyboard End -> 100% (strip width)
await p.keyboard.press('End')
await p.waitForTimeout(150)
results.hundred = { playheadPx: Math.round((await readPlayhead()) * 10) / 10, expected: box.width }

// click the low-confidence word in the heatmap -> playhead sits on its column
const payload = await p.evaluate(async () => (await (await fetch('/api/sample?fixture=large')).json()))
const low = payload.aligned.reduce((m, w) => (w.confidence < m.confidence ? w : m))

await p.locator('[role="option"][data-start="' + low.start + '"]').first().click()
await p.waitForTimeout(200)
const lowColLeft = Math.round((low.start / payload.audio_duration_s) * box.width)
const lowPlayhead = Math.round((await readPlayhead()) * 10) / 10
results.lowWord = { start: low.start, columnLeftPx: lowColLeft, playheadPx: lowPlayhead, gapPx: Math.round((lowPlayhead - lowColLeft) * 10) / 10 }

// playback moves the playhead
const before = await readPlayhead()
await p.getByRole('button', { name: 'Play' }).click()
await p.waitForTimeout(800)
const after = await readPlayhead()
await p.getByRole('button', { name: 'Pause' }).click().catch(() => {})
results.playbackMoves = { beforePx: Math.round(before * 10) / 10, afterPx: Math.round(after * 10) / 10, moved: after > before }

// sanity: columns tile the strip (no floors)
const sumCheck = await slider.evaluate(() => {
  const el = document.querySelector('[role="slider"]')
  const strip = el.querySelector('div[aria-hidden="true"]')
  const cols = strip.querySelectorAll('[data-start]')
  const maxRight = Math.max(...[...cols].map((c) => c.getBoundingClientRect().right - strip.getBoundingClientRect().left))
  return { colCount: cols.length, stripWidth: Math.round(strip.getBoundingClientRect().width), maxRightPx: Math.round(maxRight) }
})
results.sumCheck = sumCheck
console.log(JSON.stringify(results, null, 2))
await b.close()
