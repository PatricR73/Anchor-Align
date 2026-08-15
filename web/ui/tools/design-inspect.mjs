// Design review via computed styles (vision fallback). Dumps the type
// scale, palette in use, spacing rhythm, and key geometry.
import { chromium } from 'playwright'

const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' })
await p.waitForTimeout(900)

const idle = await p.evaluate(() => {
  const textStyles = {}
  for (const el of document.querySelectorAll('h1, h2, h3, p, span, button, a, dt, dd, th, td, li')) {
    if (!el.textContent.trim()) continue
    const cs = getComputedStyle(el)
    const key = cs.fontSize + '/' + cs.fontWeight + '/' + cs.fontFamily.split(',')[0] + '/' + cs.letterSpacing
    textStyles[key] = (textStyles[key] || 0) + 1
  }
  const colors = {}
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el)
    if (cs.backgroundColor !== 'rgba(0, 0, 0, 0)') colors[cs.backgroundColor] = (colors[cs.backgroundColor] || 0) + 1
  }
  const hero = document.querySelector('main h2')
  const heroP = document.querySelector('main h2 + p')
  const cards = [...document.querySelectorAll('.panel')].map((c) => {
    const r = c.getBoundingClientRect()
    const cs = getComputedStyle(c)
    return { cls: String(c.className).slice(0, 30), w: Math.round(r.width), h: Math.round(r.height), pad: cs.padding, radius: cs.borderRadius, shadow: cs.boxShadow.slice(0, 40) }
  })
  const dropzones = [...document.querySelectorAll('label[aria-label]')].map((l) => {
    const r = l.parentElement.getBoundingClientRect()
    return { label: l.getAttribute('aria-label'), h: Math.round(r.height) }
  })
  const btn = document.querySelector('main button[type="button"]')
  const btnCs = btn ? getComputedStyle(btn) : null
  return {
    fontFamilies: [...new Set([...document.querySelectorAll('body *')].map((el) => getComputedStyle(el).fontFamily.split(',')[0]))],
    textStyleHistogram: Object.entries(textStyles).sort((a, b2) => b2[1] - a[1]).slice(0, 14),
    bgColors: Object.entries(colors).sort((a, b2) => b2[1] - a[1]).slice(0, 10),
    hero: hero ? { text: hero.textContent.slice(0, 40), size: getComputedStyle(hero).fontSize, weight: getComputedStyle(hero).fontWeight, family: getComputedStyle(hero).fontFamily.split(',')[0], track: getComputedStyle(hero).letterSpacing } : null,
    heroPara: heroP ? { width: Math.round(heroP.getBoundingClientRect().width), charsPerLine: Math.round(heroP.getBoundingClientRect().width / (parseFloat(getComputedStyle(heroP).fontSize) * 0.5)) } : null,
    panels: cards.slice(0, 6),
    dropzones,
    primaryBtn: btnCs ? { size: btnCs.fontSize, pad: btnCs.padding, bg: btnCs.backgroundColor, color: btnCs.color, radius: btnCs.borderRadius } : null,
  }
})
console.log('===== IDLE DESIGN DUMP =====')
console.log(JSON.stringify(idle, null, 2))

// sample run
await p.getByRole('button', { name: /Run the bundled sample/ }).click()
await p.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30000 })
await p.waitForTimeout(900)

const result = await p.evaluate(() => {
  const h = {}
  for (const el of document.querySelectorAll('h2, h3, dt, dd, p')) {
    if (!el.textContent.trim()) continue
    const cs = getComputedStyle(el)
    const key = cs.fontSize + '/' + cs.fontWeight
    h[key] = (h[key] || 0) + 1
  }
  const metricCards = [...document.querySelectorAll('dl > div')].map((c) => {
    const r = c.getBoundingClientRect()
    return { w: Math.round(r.width), h: Math.round(r.height), label: c.querySelector('dt')?.textContent }
  })
  const player = document.querySelector('.panel p + .flex, .panel .flex')
  const timeline = document.querySelector('[role="slider"]')
  const tr = timeline ? timeline.getBoundingClientRect() : null
  const heatmapP = document.querySelector('p span[title]')?.parentElement
  const heatRects = heatmapP ? heatmapP.getClientRects() : null
  const words = heatmapP ? heatmapP.querySelectorAll('span').length : 0
  return {
    histogram: Object.entries(h).sort((a, b2) => b2[1] - a[1]).slice(0, 10),
    metricCards,
    timeline: tr ? { w: Math.round(tr.width), h: Math.round(tr.height) } : null,
    heatmap: heatmapP ? { lines: heatRects.length, words, pWidth: Math.round(heatmapP.getBoundingClientRect().width), lineHeight: getComputedStyle(heatmapP).lineHeight } : null,
    cuesTabRow: (() => { const b = document.querySelector('[role="tablist"]'); const r = b ? b.getBoundingClientRect() : null; return r ? { w: Math.round(r.width) } : null })(),
  }
})
console.log('===== RESULT DESIGN DUMP =====')
console.log(JSON.stringify(result, null, 2))
await b.close()
