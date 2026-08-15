import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://127.0.0.1:5173/?fixture=large', { waitUntil: 'networkidle', timeout: 30_000 })
await p.getByRole('button', { name: /Run the bundled sample/ }).click()
await p.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await p.waitForTimeout(800)
const check = await p.evaluate(async () => {
  const mod = window.__activeWord
  if (!mod) return { error: 'dev exposure missing' }
  const results = {}
  for (const [label, url] of [['sample', '/api/sample'], ['fixture', '/api/sample?fixture=large']]) {
    const payload = await (await fetch(url)).json()
    const words = payload.aligned
    const duration = payload.audio_duration_s
    const index = mod.buildTimeIndex(words)
    // reference: the original linear scan (first in edited order containing t)
    const reference = (t) => {
      for (let i = 0; i < words.length; i++) if (t >= words[i].start && t < words[i].end) return i
      return -1
    }
    let mismatches = 0
    let checked = 0
    const step = label === 'sample' ? 0.01 : 0.05
    for (let t = 0; t <= duration; t += step) {
      checked++
      if (reference(t) !== mod.activeIndexAt(words, index, t)) mismatches++
    }
    // also probe every word's start/mid/end-eps (the boundaries)
    for (const w of words) {
      for (const t of [w.start, (w.start + w.end) / 2, w.end - 0.0001]) {
        checked++
        if (reference(t) !== mod.activeIndexAt(words, index, t)) mismatches++
      }
    }
    results[label] = { words: words.length, checked, mismatches, equal: mismatches === 0 }
  }
  return results
})
console.log(JSON.stringify(check, null, 2))
await b.close()
