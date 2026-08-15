import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://127.0.0.1:5173/?fixture=large', { waitUntil: 'networkidle', timeout: 30_000 })
await p.getByRole('button', { name: /Run the bundled sample/ }).click()
await p.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await p.waitForTimeout(1000)
const client = await p.context().newCDPSession(p)
await client.send('Performance.enable')
const pick = (m) => Object.fromEntries(m.metrics.map((x) => [x.name, x.value]))
const b1 = pick(await client.send('Performance.getMetrics'))
// 1) busy-loop validation: 500ms of pure script
const busy = await p.evaluate(() => new Promise((resolve) => {
  const t0 = performance.now()
  while (performance.now() - t0 < 500) { /* busy */ }
  resolve(performance.now() - t0)
}))
const b2 = pick(await client.send('Performance.getMetrics'))
console.log('busy loop took', busy.toFixed(0) + 'ms; ScriptDuration delta:', (b2.ScriptDuration - b1.ScriptDuration).toFixed(1), 'ms')

// 2) did playback run? watch playing state and time over 1s
const playCheck = await p.evaluate(() => new Promise((resolve) => {
  const a = document.querySelector('audio')
  const t0 = a.currentTime
  a.currentTime = 120
  void a.play()
  const s0 = performance.now()
  setTimeout(() => { resolve({ paused: a.paused, readyState: a.readyState, timeBefore: t0.toFixed(2), timeAfter: a.currentTime.toFixed(2), duration: a.duration, err: a.error ? a.error.code : null }) }, 1200)
}))
console.log('playback check:', JSON.stringify(playCheck))
await b.close()
