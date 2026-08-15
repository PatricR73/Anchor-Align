import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
const client = await p.context().newCDPSession(p)
// throttle the UPLOAD to ~100 KB/s so the uploading state is observable
await client.send('Network.enable')
await client.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: 100 * 1024 })
await p.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle', timeout: 30_000 })
await p.setInputFiles('#audio-file', '/home/retrix/Desktop/Anchor-Align/data/sample/sample_audio.mp3')
await p.setInputFiles('#transcript-file', '/home/retrix/Desktop/Anchor-Align/data/sample/sample_transcript.txt')
const observations = []
await p.getByRole('button', { name: /Align captions/ }).click()
// sample the working view every 300ms to catch the uploading state
for (let i = 0; i < 12; i++) {
  const text = await p.locator('[role="status"]').textContent().catch(() => null)
  if (text && observations.length < 6) observations.push(text)
  await p.waitForTimeout(300)
}
// wait for the result
await p.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
const heading = await p.locator('main h2').textContent()
await client.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })
console.log(JSON.stringify({ observations, finalHeading: heading, sawUploading: observations.some((o) => o.includes('Uploading')), sawPercent: observations.some((o) => /Uploading \d+%/.test(o)) }, null, 2))
await b.close()
