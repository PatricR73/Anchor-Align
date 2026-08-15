import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 390, height: 844 } })
await p.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' })
await p.getByRole('button', { name: /Run the bundled sample/ }).click()
await p.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30000 })
await p.waitForTimeout(800)
const tabs = ['Cues', 'QC report', 'Download', 'Transcript']
const out = {}
for (const t of tabs) {
  await p.getByRole('tab', { name: new RegExp('^' + t) }).click()
  await p.waitForTimeout(400)
  out[t] = await p.evaluate(() => {
    const iw = window.innerWidth
    const wide = [...document.querySelectorAll('body *')]
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter((x) => x.r.right > iw + 1 || x.r.left < -1)
      .slice(0, 3)
      .map((x) => x.el.tagName + '.' + String(x.el.className).slice(0, 40))
    return { docScroll: document.documentElement.scrollWidth, iw, wide, unnamed: [...document.querySelectorAll('button')].filter((el) => !(el.getAttribute('aria-label') || el.textContent.trim()) && !el.closest('[aria-hidden="true"]')).map((el) => el.tagName + '.' + String(el.className).slice(0, 30)).slice(0, 4) }
  })
}
console.log(JSON.stringify(out, null, 2))
await b.close()
