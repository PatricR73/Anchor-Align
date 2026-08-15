import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle', timeout: 30_000 })
await p.evaluate(() => document.fonts.ready)
const samples = ['0:04.2', '38:00.9', '00:06.240', '00:06.240 \u2192 00:09.120', 'vtt \u00b7 srt \u00b7 qc']
const sizes = [11, 11.5, 12.5, 13]
const results = await p.evaluate(({ samples, sizes }) => {
  const measure = (family, text, size) => {
    const el = document.createElement('span')
    el.style.fontFamily = family
    el.style.fontSize = size + 'px'
    el.style.fontWeight = '400'
    el.style.position = 'absolute'
    el.style.visibility = 'hidden'
    el.textContent = text
    document.body.appendChild(el)
    const w = el.getBoundingClientRect().width
    el.remove()
    return w
  }
  const jetLoaded = document.fonts.check('11px "JetBrains Mono Variable"')
  const out = {}
  for (const s of samples) {
    for (const size of sizes) {
      const jet = measure("'JetBrains Mono Variable', monospace", s, size)
      const sys = measure("ui-monospace, SFMono-Regular, Menlo, monospace", s, size)
      out[s + ' @ ' + size + 'px'] = { jetBrains: +jet.toFixed(2), system: +sys.toFixed(2), diffPct: +(((jet - sys) / sys) * 100).toFixed(2) }
    }
  }
  const probeEl = document.createElement('span')
  probeEl.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, monospace'
  probeEl.textContent = 'x'
  document.body.appendChild(probeEl)
  const used = getComputedStyle(probeEl).fontFamily
  probeEl.remove()
  return { jetLoaded, systemMonoResolvedTo: used, out }
}, { samples, sizes })
console.log(JSON.stringify(results, null, 2))
await b.close()
