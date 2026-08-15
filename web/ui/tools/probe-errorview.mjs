import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
const results = {}
for (const [label, payload] of [
  ['too_large', { status: 413, body: { detail: { code: 'UPLOAD_TOO_LARGE', message: 'Upload exceeds the maximum allowed size (1073741824 bytes).', max_bytes: 1073741824 } } }],
  ['pipeline', { status: 500, body: { detail: { code: 'PIPELINE_FAILED', message: 'The alignment pipeline failed while processing your files. Please try again.' } } }],
]) {
  const page = await b.newPage({ viewport: { width: 1440, height: 900 } })
  await page.route('**/api/align', (route) => route.fulfill({ status: payload.status, contentType: 'application/json', body: JSON.stringify(payload.body) }))
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle', timeout: 30_000 })
  // set files via the dropzones by intercepting? simpler: click sample is intercepted too - instead upload via input
  await page.setInputFiles('#audio-file', { name: 'a.wav', mimeType: 'audio/wav', buffer: Buffer.from('data') })
  await page.setInputFiles('#transcript-file', { name: 't.txt', mimeType: 'text/plain', buffer: Buffer.from('hello') })
  await page.getByRole('button', { name: /Align captions/ }).click()
  await page.waitForTimeout(800)
  const heading = await page.locator('main h2').textContent().catch(() => null)
  const retryCount = await page.getByRole('button', { name: /Try again/ }).count()
  const bodyText = await page.locator('main').textContent()
  results[label] = { heading, retryCount, hasAction: /can(not)? be retried/.test(bodyText), text: bodyText.replace(/\s+/g, ' ').slice(0, 300) }
  await page.close()
}
console.log(JSON.stringify(results, null, 2))
await b.close()
