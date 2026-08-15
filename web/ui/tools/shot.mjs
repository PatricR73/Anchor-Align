// usage: node tools/shot.mjs <url> <out> [width] [height]
import { chromium } from 'playwright'

const [url, out, w = 1440, h = 900] = process.argv.slice(2)
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 2 })
const errs = []
page.on('console', (m) => m.type() === 'error' && errs.push(m.text()))
page.on('pageerror', (e) => errs.push(String(e)))
await page.goto(url, { waitUntil: 'networkidle', timeout: 30_000 })
await page.waitForTimeout(600)
await page.screenshot({ path: out + '.png', fullPage: true })
console.log(errs.length ? 'CONSOLE ERRORS:\n' + errs.join('\n') : 'clean')
await browser.close()
