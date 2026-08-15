import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://127.0.0.1:5173/?fixture=large', { waitUntil: 'networkidle', timeout: 30_000 })
await p.getByRole('button', { name: /Run the bundled sample/ }).click()
await p.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await p.waitForTimeout(1200)

// 1) how many of the 9000 timeline segments are actually visible?
const t1 = await p.evaluate(() => {
  const slider = document.querySelector('[role="slider"]')
  const container = slider.querySelector('div')
  const cr = container.getBoundingClientRect()
  const segs = [...container.querySelectorAll('button')]
  const visible = segs.filter((s) => {
    const r = s.getBoundingClientRect()
    return r.left >= cr.left - 1 && r.right <= cr.right + 1
  }).length
  return { total: segs.length, containerW: Math.round(cr.width), visible, visiblePct: (visible / segs.length * 100).toFixed(2) + '%' }
})

// 2) real frame rate while playing (rAF count over 2s)
await p.getByRole('button', { name: 'Play' }).click()
const t2 = await p.evaluate(() => new Promise((resolve) => {
  let frames = 0
  const start = performance.now()
  const loop = () => { frames++; if (performance.now() - start < 2000) requestAnimationFrame(loop); else resolve(Math.round(frames / 2)) }
  requestAnimationFrame(loop)
}))
await p.getByRole('button', { name: 'Pause' }).click().catch(() => {})

// 3) is the audit's focus test capable of failing? synthetic Tab vs real Tab
const t3 = await p.evaluate(() => {
  const before = document.activeElement?.tagName
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
  const afterSynthetic = document.activeElement?.tagName
  return { before, afterSynthetic }
})
await p.keyboard.press('Tab')
const activeAfterRealTab = await p.evaluate(() => document.activeElement?.tagName)

// 4) react render cost: time to re-render on a state tick (seek triggers a render)
const t4 = await p.evaluate(() => {
  const slider = document.querySelector('[role="slider"]')
  slider.setAttribute('aria-valuenow', '1234') // force no-op; instead measure layout of heatmap
  const hp = document.querySelector('p span[title]')?.parentElement
  const start = performance.now()
  const r = hp.getBoundingClientRect() // forces layout
  const layoutMs = performance.now() - start
  return { layoutMs: Math.round(layoutMs * 100) / 100, height: Math.round(r.height) }
})

console.log(JSON.stringify({ timeline: t1, fpsDuringPlay: t2, focusTest: { ...t3, activeAfterRealTab }, heatmap: t4 }, null, 2))
await b.close()
