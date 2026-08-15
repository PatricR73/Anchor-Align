import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://127.0.0.1:5173/?fixture=large', { waitUntil: 'networkidle', timeout: 30_000 })
await p.getByRole('button', { name: /Run the bundled sample/ }).click()
await p.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await p.waitForTimeout(1000)
const payload = await p.evaluate(async () => (await (await fetch('/api/sample?fixture=large')).json()))
const low = payload.aligned.reduce((m, w) => (w.confidence < m.confidence ? w : m))
const lowIdx = payload.aligned.indexOf(low)
const neighbor = payload.aligned[lowIdx + 1] || payload.aligned[lowIdx - 1]

// seek to the low word -> it becomes the ACTIVE word (item 3 state)
await p.locator('[role="option"][data-start="' + low.start + '"]').first().click()
await p.waitForTimeout(300)

const info = await p.evaluate(({ lowStart, neighborStart }) => {
  const words = [...document.querySelectorAll('[role="option"]')]
  const find = (s) => words.find((el) => parseFloat(el.getAttribute('data-start')) === s)
  const lowEl = find(lowStart)
  const nbEl = find(neighborStart)
  const lum = (rgb) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])
  }
  const parse = (c) => { const m = c.match(/rgba?\(([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)[, ]*([\d.]*)\)/); return m ? [+m[1], +m[2], +m[3], m[4] === undefined || m[4] === '' ? 1 : parseFloat(m[4])] : null }
  const composite = (fg, bg, a) => [Math.round(fg[0] * a + bg[0] * (1 - a)), Math.round(fg[1] * a + bg[1] * (1 - a)), Math.round(fg[2] * a + bg[2] * (1 - a))]
  // effective bg under the active word: its own bg over the panel
  const lcs = getComputedStyle(lowEl)
  const lc = parse(lcs.backgroundColor)  // accent-dim rgba
  const panel = [16, 21, 28]
  const effBg = composite([lc[0], lc[1], lc[2]], panel, lc[3])
  const text = parse(lcs.color)
  const ratio = (Math.max(lum(text), lum(effBg)) + 0.05) / (Math.min(lum(text), lum(effBg)) + 0.05)
  const gray = (rgb) => Math.round(lum(rgb) * 255)
  return {
    activeContrast: { text: 'rgb(' + text.slice(0, 3).join(',') + ')', effBg: 'rgb(' + effBg.join(',') + ')', ratio: +ratio.toFixed(2), passes: ratio >= 4.5 },
    channels: {
      lowFontWeight: lcs.fontWeight,
      neighborFontWeight: getComputedStyle(nbEl).fontWeight,
      lowGray: gray(text.slice(0, 3)),
      neighborGray: gray(parse(getComputedStyle(nbEl).color).slice(0, 3)),
    },
  }
}, { lowStart: low.start, neighborStart: neighbor.start })

// timeline heights: the low column vs neighbors
const heights = await p.evaluate((lowStart) => {
  const slider = document.querySelector('[role="slider"]')
  const cols = [...slider.querySelectorAll('[data-start]')]
  const lowCol = cols.find((c) => c.getAttribute('data-start') === String(lowStart))
  const others = cols.filter((c) => c !== lowCol).slice(0, 3)
  const h = (el) => Math.round(el.getBoundingClientRect().height)
  return { lowColumnHeight: lowCol ? h(lowCol) : null, neighborHeights: others.map(h), stripHeight: Math.round(slider.querySelector('div[aria-hidden="true"]').getBoundingClientRect().height) }
}, low.start)

// P10 gate: the redundant solidity channel must actually separate the low
// word from its neighbors, and the active-word contrast must stay >= 4.5.
// Fail (exit 1) if the encoding is removed or collapsed — this is the check
// that stops someone reverting the second channel as "visual noise".
const failures = []
if (!info.activeContrast.passes) failures.push('active-word contrast ' + info.activeContrast.ratio + ':1 < 4.5:1')
if (parseInt(info.channels.lowFontWeight) >= parseInt(info.channels.neighborFontWeight)) {
  failures.push('low word font weight ' + info.channels.lowFontWeight + ' not lighter than neighbor ' + info.channels.neighborFontWeight)
}
if (Math.abs(info.channels.lowGray - info.channels.neighborGray) < 8) {
  failures.push('low vs neighbor grayscale luminance too close (' + info.channels.lowGray + ' vs ' + info.channels.neighborGray + ') — the solidity channel no longer separates in grayscale')
}
if (heights.lowColumnHeight === null) failures.push('low column missing from timeline')
else if (heights.neighborHeights.length && heights.lowColumnHeight >= Math.min(...heights.neighborHeights)) {
  failures.push('low column height ' + heights.lowColumnHeight + 'px not shorter than neighbor ' + Math.min(...heights.neighborHeights) + 'px')
}

console.log(JSON.stringify({ info, heights, ok: failures.length === 0, failures }, null, 2))
if (failures.length > 0) process.exit(1)
await b.close()
