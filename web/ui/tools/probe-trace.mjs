import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://127.0.0.1:5173/?fixture=large', { waitUntil: 'networkidle', timeout: 30_000 })
await p.getByRole('button', { name: /Run the bundled sample/ }).click()
await p.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await p.waitForTimeout(1000)
const client = await p.context().newCDPSession(p)
await client.send('Tracing.start', { categories: '-*,devtools.timeline', transferMode: 'ReportEvents' })
const collected = []
client.on('Tracing.dataCollected', (e) => collected.push(...e.params.value))
const frames = await p.evaluate(() => new Promise((resolve) => {
  const a = document.querySelector('audio')
  a.currentTime = 120
  void a.play()
  const started = performance.now()
  let prev = started
  let n = 0
  const loop = (now) => {
    n++
    if (now - started < 2000) requestAnimationFrame(loop)
    else { a.pause(); resolve(n) }
  }
  requestAnimationFrame(loop)
}))
await client.send('Tracing.end')
// sum main-thread task durations (RunTask) and script (FunctionCall)
let taskMs = 0, scriptMs = 0, layoutMs = 0
for (const ev of collected) {
  if (ev.name === 'RunTask' && ev.args?.data?.duration) taskMs += ev.args.data.duration
  if (ev.name === 'FunctionCall' && ev.args?.data?.duration) scriptMs += ev.args.data.duration
  if (ev.name === 'Layout' && ev.args?.data?.duration) layoutMs += ev.args.data.duration
}
console.log(JSON.stringify({ events: collected.length, frames, taskMsPerFrame: +(taskMs / frames).toFixed(2), scriptMsPerFrame: +(scriptMs / frames).toFixed(2), layoutMsPerFrame: +(layoutMs / frames).toFixed(2) }, null, 2))
await b.close()
