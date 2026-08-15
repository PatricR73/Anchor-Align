import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const OUT = '/home/retrix/Desktop/Anchor-Align/.cache/gif-frames'
mkdirSync(OUT, { recursive: true })

const FPS = 8
const SECONDS = 8
const N = FPS * SECONDS

const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 880, height: 720 } })
await p.goto('http://127.0.0.1:5173/?fixture=large', { waitUntil: 'networkidle', timeout: 30_000 })
await p.getByRole('button', { name: /Run the bundled sample/ }).click()
await p.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await p.waitForTimeout(1000)

const payload = await p.evaluate(async () => (await (await fetch('/api/sample?fixture=large')).json()))
const low = payload.aligned.reduce((m, w) => (w.confidence < m.confidence ? w : m))
const lowStart = low.start

await p.evaluate(() => {
  const c = document.createElement('div')
  c.id = 'aa-cursor'
  c.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 2l17 11-7.5 1L10 22z" fill="#e9eef4" stroke="#0a0e13" stroke-width="1.5"/></svg>'
  c.style.cssText = 'position:fixed;left:0;top:0;z-index:9999;pointer-events:none;filter:drop-shadow(0 1px 2px rgba(0,0,0,.6))'
  document.body.appendChild(c)
})
const setCursor = (x, y) => p.evaluate(({ x, y }) => { const c = document.getElementById('aa-cursor'); c.style.transform = 'translate(' + x + 'px,' + y + 'px)' }, { x, y })

// reference viewport positions, each measured in its own scroll state
await p.getByRole('slider').scrollIntoViewIfNeeded()
const tlBox = await p.getByRole('slider').boundingBox()
const startPos = { x: tlBox.x + (low.start / payload.audio_duration_s) * tlBox.width, y: tlBox.y + tlBox.height / 2 }

const opt = p.locator('[role="option"][data-start="' + lowStart + '"]').first()
const centerLow = () => p.evaluate((s) => document.querySelector('[role="option"][data-start="' + s + '"]')?.scrollIntoView({ block: 'center' }), lowStart)
await centerLow()
await p.waitForTimeout(200)
const wordBox = await opt.boundingBox()
const wordPos = { x: wordBox.x + wordBox.width / 2, y: wordBox.y + wordBox.height / 2 }

const lerp = (a, b, f) => ({ x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f })
const ease = (f) => f * f * (3 - 2 * f)

for (let f = 0; f < N; f++) {
  const t = f / FPS
  let cursor = startPos
  if (t >= 1 && t < 3) cursor = lerp(startPos, wordPos, ease((t - 1) / 2))
  if (t >= 3) cursor = wordPos
  setCursor(cursor.x, cursor.y)

  if (t >= 3 && t < 3.6) await p.mouse.move(wordPos.x, wordPos.y)
  if (t >= 3.5 && t < 3.6) await p.mouse.click(wordPos.x, wordPos.y)
  if (t >= 5.5 && t < 5.7) await p.evaluate(() => document.querySelector('button[aria-label="Play"]')?.click())

  // timeline region: measure the slider fresh in this scroll state
  await p.getByRole('slider').scrollIntoViewIfNeeded()
  const sb = await p.getByRole('slider').boundingBox()
  const clipA = { x: 0, y: Math.max(0, sb.y - 46), width: 880, height: 132 }
  await p.screenshot({ path: OUT + '/A_' + String(f).padStart(2, '0') + '.png', clip: clipA })

  // heatmap region: center the low word, measure fresh
  await centerLow()
  await p.waitForTimeout(60)
  const ob = await opt.boundingBox()
  const clipB = { x: 0, y: Math.max(0, ob.y - 170), width: 880, height: 360 }
  await p.screenshot({ path: OUT + '/B_' + String(f).padStart(2, '0') + '.png', clip: clipB })
}

console.log(JSON.stringify({ frames: N, startPos: { x: Math.round(startPos.x), y: Math.round(startPos.y) }, wordPos: { x: Math.round(wordPos.x), y: Math.round(wordPos.y) } }))
await b.close()
