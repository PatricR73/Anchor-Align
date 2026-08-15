// Latent-coupling regression: the active-word highlight must be keyed to
// the ARRAY POSITION in result.aligned, not to token.index.
//
// This payload drops index 5 ("five") — positions 0..9 carry indices
// 0,1,2,3,4,6,7,8,9,10 — so the two numbering spaces diverge after the
// gap. Position 7 is index 8 ("eight"); the word with index 7 sits at
// position 6 ("seven"). If the UI compares the active position to
// token.index, the highlight lands one word early and silently points at
// the wrong word.
//
// Also asserts the dev-mode invariant tripwire fires for this payload.
import { chromium } from 'playwright'

const WORDS = ['zero', 'one', 'two', 'three', 'four', 'six', 'seven', 'eight', 'nine', 'ten']

const aligned = WORDS.map((text, p) => ({
  text,
  index: p < 5 ? p : p + 1, // index 5 deliberately missing
  char_offset: p * 5,
  sentence_id: 0,
  is_sentence_end: p === WORDS.length - 1,
  match_type: 'exact',
  confidence: 0.9,
  start: +(p * 0.3).toFixed(3),
  end: +(p * 0.3 + 0.28).toFixed(3),
}))

const payload = {
  audio_id: 'missing-token',
  audio_name: 'missing.wav',
  transcript_name: 'missing.txt',
  model: 'base',
  phonetic: false,
  elapsed_s: 0.0,
  audio_duration_s: 3.0,
  stats: { cues: 2, qc_errors: 0, qc_warnings: 0, interpolated_words: 0, mean_confidence: 0.92 },
  aligned,
  cues: [
    { index: 1, start: 0.0, end: 1.5, lines: ['zero one two three four'] },
    { index: 2, start: 1.5, end: 3.0, lines: ['six seven eight nine ten'] },
  ],
  issues: [],
  downloads: { vtt: 0, srt: 0, confidence: 0 },
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
// serve the missing-token payload in place of the large fixture; the audio
// element is irrelevant to the highlight (seek drives the time state).
await page.route('**/api/sample*', (route) => {
  if (route.request().url().includes('fixture=large')) route.fulfill({ json: payload })
  else route.continue()
})
await page.route('**/api/audio/**', (route) => route.abort())

await page.goto('http://127.0.0.1:5173/?fixture=large', { waitUntil: 'networkidle', timeout: 30_000 })
await page.getByRole('button', { name: /Run the bundled sample/ }).click()
await page.getByRole('heading', { name: 'Aligned transcript' }).waitFor({ timeout: 30_000 })
await page.waitForTimeout(800)

// click the word at array position 7 ("eight"); the word containing its
// start time is position 7, so the highlight must land on "eight"
await page.locator('[role="option"]').nth(7).click()
await page.waitForTimeout(300)

const highlighted = (await page.locator('[role="option"].bg-accent-dim').textContent()) ?? null
const tripwireFired = errors.some((e) => e.includes('anchor-align invariant'))

const ok = highlighted === 'eight' && tripwireFired
console.log(JSON.stringify(
  { clicked: 'eight (array position 7, index 8)', highlighted, tripwireFired, ok },
  null,
  2,
))
await browser.close()
if (!ok) process.exit(1)
