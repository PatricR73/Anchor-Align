// usage: node tools/audit.mjs <url> [width] [sample]
// Asserts the cheap objective things: no horizontal overflow at narrow
// widths, every interactive element has an accessible name, visible focus
// outlines, text/background contrast >= 4.5:1 (3:1 for large text).
// Pass "sample" as the third arg to run the bundled sample first.
import { chromium } from 'playwright'

const [url, w = 390, mode] = process.argv.slice(2)
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: +w, height: 844 } })
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e)))
await page.goto(url, { waitUntil: 'networkidle', timeout: 30_000 })
await page.waitForTimeout(600)
if (mode === 'sample') {
  await page.getByRole('button', { name: /Run the bundled sample/ }).click()
  await page.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
  await page.waitForTimeout(800)
}

const report = await page.evaluate(() => {
  const out = { overflow: null, unnamed: [], focus: [], contrast: [], samples: {} }
  const doc = document.documentElement

  if (doc.scrollWidth > window.innerWidth + 1) {
    out.overflow = { scrollWidth: doc.scrollWidth, innerWidth: window.innerWidth }
  }

  const interactive = [
    ...document.querySelectorAll(
      'button, a[href], input, select, textarea, [role="button"], [role="switch"], [role="tab"], [role="slider"]',
    ),
  ]
  for (const el of interactive) {
    if (el.closest('[aria-hidden="true"]')) continue
    const name = (el.getAttribute('aria-label') || (el.textContent || '').trim() || '').trim()
    const labelledby = el.getAttribute('aria-labelledby')
    const hasLabel = 'labels' in el && el.labels && el.labels.length > 0
    if (!name && !labelledby && !hasLabel) {
      out.unnamed.push({ tag: el.tagName, cls: String(el.className).slice(0, 70) })
    }
  }

  const focusable = [
    ...document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'),
  ].slice(0, 40)
  // real keyboard focus: Tab between elements so :focus-visible actually matches
  document.body.focus()
  for (let i = 0; i < focusable.length + 2; i++) {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
  }
  for (const el of focusable) {
    if (el.matches(':focus-visible')) {
      const cs = getComputedStyle(el)
      const outlineVisible = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0
      const shadowVisible = cs.boxShadow !== 'none'
      if (!outlineVisible && !shadowVisible) {
        out.focus.push({ tag: el.tagName, cls: String(el.className).slice(0, 70), outline: cs.outline })
      }
    }
  }

  const lum = (rgb) => {
    const f = (v) => {
      v /= 255
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
    }
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])
  }
  const parseColor = (c) => {
    const m = c.match(/rgba?\(([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)/)
    return m ? [+m[1], +m[2], +m[3]] : null
  }
  const effectiveBg = (el) => {
    // composite every background layer (body -> top) with real alpha
    const layers = []
    let cur = el
    while (cur) {
      const cs = getComputedStyle(cur)
      const m = cs.backgroundColor.match(/rgba?\(([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)[, ]*([\d.]*)\)/)
      if (m) layers.push([+m[1], +m[2], +m[3], m[4] === undefined || m[4] === '' ? 1 : parseFloat(m[4])])
      cur = cur.parentElement
    }
    let bg = [10, 14, 19]
    for (const [r, g, b, a] of layers.reverse()) {
      bg = [Math.round(r * a + bg[0] * (1 - a)), Math.round(g * a + bg[1] * (1 - a)), Math.round(b * a + bg[2] * (1 - a))]
    }
    return bg
  }

  const textEls = [...document.querySelectorAll('body *')].filter((el) => {
    const r = el.getBoundingClientRect()
    if (r.width < 2 || r.height < 2) return false
    const cs = getComputedStyle(el)
    if (cs.display === 'none' || cs.visibility === 'hidden') return false
    const direct = el.childNodes.length === 1 && el.childNodes[0].nodeType === 3
    return direct && el.textContent.trim().length > 0
  }).slice(0, 140)

  for (const el of textEls) {
    const cs = getComputedStyle(el)
    const fg = parseColor(cs.color)
    if (!fg) continue
    const bg = effectiveBg(el)
    const l1 = lum(fg)
    const l2 = lum(bg)
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
    const size = parseFloat(cs.fontSize)
    const bold = parseInt(cs.fontWeight) >= 700
    const large = size >= 24 || (size >= 18.66 && bold)
    const min = large ? 3 : 4.5
    if (ratio < min) {
      out.contrast.push({
        text: el.textContent.trim().slice(0, 40),
        cls: String(el.className).slice(0, 55),
        ratio: +ratio.toFixed(2),
        size,
        bold,
        color: cs.color,
        bg: 'rgb(' + bg.join(',') + ')',
      })
    }
  }
  return out
})

console.log(JSON.stringify(report, null, 2))
for (const e of pageErrors) console.log('PAGE ERROR:', e)
await browser.close()
