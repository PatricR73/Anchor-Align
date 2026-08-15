import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
const errs = []
p.on('console', (m) => m.type() === 'error' && errs.push(m.text()))
p.on('requestfailed', (r) => errs.push('reqfail: ' + r.url()))
await p.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle', timeout: 30_000 })
await p.evaluate(() => document.fonts.ready)
const info = await p.evaluate(() => {
  const preloads = [...document.querySelectorAll('link[rel="preload"][as="font"]')].map((l) => l.href.split('/').pop())
  const fonts = {
    display: document.fonts.check('32px "Space Grotesk Variable"'),
    body: document.fonts.check('15px "Inter Variable"'),
    mono: (() => { const el = document.createElement('span'); el.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, monospace'; el.textContent = 'x'; document.body.appendChild(el); const f = getComputedStyle(el).fontFamily; el.remove(); return f })(),
  }
  const wordmark = getComputedStyle(document.querySelector('header h1')).fontFamily.split(',')[0]
  const hero = getComputedStyle(document.querySelector('main h2')).fontFamily.split(',')[0]
  const monoEl = [...document.querySelectorAll('main *')].find((el) => getComputedStyle(el).fontFamily.includes('ui-monospace') && el.textContent.trim().length > 0)
  return { preloads, fonts, wordmark, hero, monoSample: monoEl ? getComputedStyle(monoEl).fontFamily.split(',')[0] : null, monoText: monoEl ? monoEl.textContent.trim().slice(0, 30) : null }
})
console.log(JSON.stringify({ info, errs }, null, 2))
await b.close()
