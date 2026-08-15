// usage: node tools/timeline-widths.mjs [base]
// P1 regression guard, caught arithmetically instead of visually: the word
// timeline's rendered segments must never sum wider than the strip that
// contains them (<= 100% of the container), and no segment may overflow the
// strip's right edge. The P1 bug class was segments laid out with
// proportional widths plus a min-width floor — sub-pixel words got inflated
// and the total ran past 100%, so the strip overflowed and the low word's
// column drifted from its true time. The fix buckets words into exactly
// `width` 1px columns (WordTimeline.tsx SegmentsLayer); this tool asserts
// the DOM invariant at two viewport widths so a regression to proportional
// layouts fails CI instead of showing up as a visual glitch.
import { chromium } from 'playwright'

const BASE = process.argv[2] || 'http://127.0.0.1:5173'
const WIDTHS = [390, 1440]
const TOLERANCE_PX = 2 // subpixel rounding on fractional column edges

const browser = await chromium.launch()
const failures = []
const results = []

for (const width of WIDTHS) {
  const page = await browser.newPage({ viewport: { width, height: 844 } })
  await page.goto(BASE + '/?fixture=large', { waitUntil: 'networkidle', timeout: 30_000 })
  await page.getByRole('button', { name: /Run the bundled sample/ }).click()
  await page.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
  await page.waitForTimeout(800)

  const m = await page.evaluate(() => {
    const slider = document.querySelector('[role="slider"]')
    if (!slider) return { error: 'no slider' }
    // the SegmentsLayer is the aria-hidden visual layer inside the slider
    const layer = slider.querySelector('[aria-hidden="true"]')
    if (!layer) return { error: 'no segments layer' }
    const cr = layer.getBoundingClientRect()
    if (cr.width === 0) return { error: 'segments layer not laid out' }
    const segs = [...layer.querySelectorAll('[data-start]')]
    const widths = segs.map((s) => s.getBoundingClientRect().width)
    const rights = segs.map((s) => s.getBoundingClientRect().right)
    const sum = widths.reduce((a, b) => a + b, 0)
    const maxRight = segs.reduce((m, s) => Math.max(m, s.getBoundingClientRect().right), cr.left)
    return {
      containerW: cr.width,
      containerRight: cr.right,
      segmentCount: segs.length,
      sumWidths: sum,
      sumPct: (sum / cr.width) * 100,
      maxRight,
      maxRightOverflow: maxRight - cr.right,
      maxLeft: segs.reduce((m, s) => Math.max(m, s.getBoundingClientRect().left), cr.left),
    }
  })

  if (m.error) {
    failures.push('width ' + width + ': ' + m.error)
  } else {
    if (m.sumWidths > m.containerW + TOLERANCE_PX) {
      failures.push('width ' + width + ': segment widths sum ' + m.sumWidths.toFixed(1) + 'px (' + m.sumPct.toFixed(1) + '%) > container ' + m.containerW.toFixed(1) + 'px')
    }
    if (m.maxRight > m.containerRight + TOLERANCE_PX) {
      failures.push('width ' + width + ': segment right edge ' + m.maxRight.toFixed(1) + 'px overflows container right ' + m.containerRight.toFixed(1) + 'px by ' + m.maxRightOverflow.toFixed(1) + 'px')
    }
    results.push({ width, ...m, sumPct: +m.sumPct.toFixed(2) })
  }
  await page.close()
}
await browser.close()

console.log(JSON.stringify({ tool: 'timeline-widths', results, ok: failures.length === 0, failures }, null, 2))
if (failures.length > 0) process.exit(1)
