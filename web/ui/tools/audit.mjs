// usage: node tools/audit.mjs <url> [width] [sample]
// Asserts the cheap objective things: no horizontal overflow at narrow
// widths, every interactive element has an accessible name, REACHABILITY by
// real Tab/arrow traversal (not merely focus rings once focus arrives),
// text/background contrast >= 4.5:1 (3:1 for large text).
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

// Real keyboard traversal: Tab through every control with actual key
// presses (synthetic KeyboardEvent dispatch never moves focus), assert each
// declared tab stop was REACHED and shows a focus ring, and arrow-navigate
// the roving widgets (listbox, slider).
async function auditFocus(page) {
  const stops = await page.evaluate(() =>
    [...document.querySelectorAll(
      'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"]), [role="slider"], [role="listbox"]',
    )].map((el) => ({
      tag: el.tagName,
      role: el.getAttribute('role'),
      name: (el.getAttribute('aria-label') || (el.textContent || '').trim().slice(0, 30) || '').trim(),
      cls: String(el.className).slice(0, 50),
    })),
  )

  const seen = new Set()
  const sequence = []
  const noRing = []
  const TABS = Math.max(stops.length * 3 + 6, 40)
  for (let i = 0; i < TABS; i++) {
    await page.keyboard.press('Tab')
    const info = await page.evaluate(() => {
      const el = document.activeElement
      if (!el || el === document.body || el === document.documentElement) return null
      const cs = getComputedStyle(el)
      const ring = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0
      return {
        tag: el.tagName,
        role: el.getAttribute('role'),
        name: (el.getAttribute('aria-label') || (el.textContent || '').trim().slice(0, 30) || '').trim(),
        cls: String(el.className).slice(0, 50),
        ring,
      }
    })
    if (!info) continue
    const key = info.tag + '|' + (info.role || '') + '|' + info.name + '|' + info.cls
    seen.add(key)
    if (!info.ring) noRing.push({ tag: info.tag, role: info.role, name: info.name, cls: info.cls })
    if (sequence.length < 20) sequence.push({ tag: info.tag, role: info.role, name: info.name, cls: info.cls })
  }

  const stopKeys = new Set(stops.map((s) => s.tag + '|' + (s.role || '') + '|' + s.name + '|' + s.cls))
  const unreachable = stops.filter((s) => !seen.has(s.tag + '|' + (s.role || '') + '|' + s.name + '|' + s.cls))

  const arrows = {}
  const lb = page.locator('[role="listbox"]')
  if (await lb.count()) {
    await lb.focus()
    const a0 = await lb.getAttribute('aria-activedescendant')
    await page.keyboard.press('ArrowRight')
    const a1 = await lb.getAttribute('aria-activedescendant')
    await page.keyboard.press('Home')
    const aHome = await lb.getAttribute('aria-activedescendant')
    await page.keyboard.press('End')
    const aEnd = await lb.getAttribute('aria-activedescendant')
    const firstId = await lb.evaluate((el) => el.querySelector('[role="option"]')?.id ?? null)
    arrows.listbox = {
      before: a0,
      afterArrow: a1,
      home: aHome,
      end: aEnd,
      arrowMoved: !!a0 && a0 !== a1,
      homeOk: aHome === firstId,
    }
  }
  const sl = page.locator('[role="slider"]')
  if (await sl.count()) {
    await sl.focus()
    const v0 = Number(await sl.getAttribute('aria-valuenow'))
    await page.keyboard.press('ArrowRight')
    const v1 = Number(await sl.getAttribute('aria-valuenow'))
    arrows.slider = { before: v0, after: v1, moved: v1 > v0 }
  }

  return { declaredStops: stops.length, sequence, unreachable, noRing, arrows }
}

report.focus = await auditFocus(page)

console.log(JSON.stringify(report, null, 2))
for (const e of pageErrors) console.log('PAGE ERROR:', e)

// Exit non-zero on violations so CI fails: horizontal overflow, unnamed
// interactive elements, unreachable declared tab stops, focus without a
// visible ring, sub-4.5:1 contrast (3:1 large), and page errors.
const violations = []
if (report.overflow) violations.push('horizontal overflow: scrollWidth ' + report.overflow.scrollWidth + ' > innerWidth ' + report.overflow.innerWidth)
if (report.unnamed.length) violations.push(report.unnamed.length + ' interactive element(s) without an accessible name')
if (report.focus.unreachable.length) violations.push(report.focus.unreachable.length + ' declared tab stop(s) never reached: ' + report.focus.unreachable.map((s) => s.tag + ' ' + (s.name || s.cls)).join('; '))
if (report.focus.noRing.length) violations.push(report.focus.noRing.length + ' focused element(s) with no visible focus ring')
if (report.contrast.length) violations.push(report.contrast.length + ' contrast failure(s), worst ' + Math.min(...report.contrast.map((c) => c.ratio)) + ':1')
if (pageErrors.length) violations.push(pageErrors.length + ' page error(s): ' + pageErrors[0])
if (violations.length) {
  console.log('AUDIT FAIL:')
  for (const v of violations) console.log('  - ' + v)
  process.exit(1)
}
await browser.close()
