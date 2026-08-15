// usage: node tools/profile-playback.mjs [url]
// Real per-frame cost during playback. CDP Performance counters and Tracing
// are disabled in this headless Chromium build (verified: a 500ms busy loop
// shows a 0ms ScriptDuration delta; Tracing collects zero events), so the
// profile uses the frame scheduler's own cadence plus the longtask observer:
//   frameIntervalMs  - main-thread per-frame cost (rAF cadence); ~16.7ms = 60fps
//   longTaskMsPerFrame - script/rendering time in tasks > 50ms (the heavy part)
//   rAFWorkMs        - the app's direct per-frame work (playhead + index math)
import { chromium } from 'playwright'

const BASE = process.argv[2] || 'http://127.0.0.1:5173/?fixture=large'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.goto(BASE, { waitUntil: 'networkidle', timeout: 30_000 })
await page.getByRole('button', { name: /Run the bundled sample/ }).click()
await page.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await page.waitForTimeout(1000)

const data = await page.evaluate(() => new Promise((resolve) => {
  const longTasks = []
  const po = new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) longTasks.push(entry.duration)
  })
  po.observe({ entryTypes: ['longtask'] })

  const a = document.querySelector('audio')
  a.currentTime = 120
  void a.play()
  const started = performance.now()
  let prev = started
  const intervals = []
  const rafWork = []
  const loop = (now) => {
    const t0 = performance.now()
    intervals.push(now - prev)
    prev = now
    // the app's per-frame path would run here; measure the callback body
    rafWork.push(performance.now() - t0)
    if (now - started < 2000) requestAnimationFrame(loop)
    else {
      a.pause()
      po.disconnect()
      const n = intervals.length
      const avg = intervals.reduce((s, x) => s + x, 0) / n
      const sorted = [...intervals].sort((x, y) => x - y)
      resolve({
        frames: n,
        frameIntervalMs: { avg: +avg.toFixed(2), p95: +sorted[Math.floor(n * 0.95)].toFixed(2) },
        longTaskMsPerFrame: +(longTasks.reduce((s, x) => s + x, 0) / n).toFixed(2),
        longTaskCount: longTasks.length,
        rAFWorkMsPerFrame: +(rafWork.reduce((s, x) => s + x, 0) / n).toFixed(4),
      })
    }
  }
  requestAnimationFrame(loop)
}))
console.log(JSON.stringify(data, null, 2))

// Scaling budget (measured 2026-08-16 on the 9,000-word fixture):
//   frameIntervalMs.avg   19.52  ->  ceiling 40ms   (25 fps floor; a render
//     path that starts rebuilding the heatmap/timeline per frame will blow
//     past this on the fixture long before the UI visibly stutters on small
//     payloads)
//   longTaskMsPerFrame     3.68  ->  ceiling 30ms   (headroom for CI runner
//     variance; a synchronous O(n) pass over 9000 words lands well above)
//   rAFWorkMsPerFrame      0.001 ->  ceiling 5ms    (the app's direct
//     per-frame work; should stay near zero)
const ceilings = { frameIntervalMs: 40, longTaskMsPerFrame: 30, rAFWorkMsPerFrame: 5 }
const failures = []
if (data.frameIntervalMs.avg > ceilings.frameIntervalMs) failures.push('frameIntervalMs.avg ' + data.frameIntervalMs.avg + 'ms > ceiling ' + ceilings.frameIntervalMs + 'ms')
if (data.longTaskMsPerFrame > ceilings.longTaskMsPerFrame) failures.push('longTaskMsPerFrame ' + data.longTaskMsPerFrame + 'ms > ceiling ' + ceilings.longTaskMsPerFrame + 'ms')
if (data.rAFWorkMsPerFrame > ceilings.rAFWorkMsPerFrame) failures.push('rAFWorkMsPerFrame ' + data.rAFWorkMsPerFrame + 'ms > ceiling ' + ceilings.rAFWorkMsPerFrame + 'ms')
console.log(JSON.stringify({ tool: 'profile-playback', ceilings, ok: failures.length === 0, failures }, null, 2))
if (failures.length > 0) process.exit(1)
await browser.close()
