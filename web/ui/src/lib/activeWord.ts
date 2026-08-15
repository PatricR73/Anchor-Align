// Active-word lookup for the transcript heatmap.
//
// Edited order is non-monotonic in time (transposed blocks), so a binary
// search over the aligned array itself is invalid. Instead we sort an INDEX
// array by (start, edited index) ONCE — it depends only on the payload — and
// binary-search that for the word containing t.
//
// Overlapping spans: the original linear scan returned the FIRST word in
// edited order whose [start, end) contains t — i.e. the minimum edited index
// among all containing words. That behaviour is preserved exactly: after
// finding the cut (the last word with start <= t), we walk backward while
// start >= t - maxDuration — any containing word must satisfy that, since
// end <= start + maxDuration and end > t — and keep the smallest edited
// index. Non-overlapping data (the normal case) resolves in one iteration;
// pathological overlaps degrade to a scan bounded by the words within one
// max-duration window.

export interface TimedWord {
  start: number
  end: number
}

export interface TimeIndex {
  /** indices into the source array, sorted by (start, edited index) */
  indices: number[]
  /** maximum word duration — bounds the backward containment walk */
  maxDuration: number
}

export function buildTimeIndex(words: TimedWord[]): TimeIndex {
  const indices = words.map((_, i) => i)
  indices.sort((a, b) => words[a].start - words[b].start || a - b)
  let maxDuration = 0
  for (const w of words) {
    const d = w.end - w.start
    if (d > maxDuration) maxDuration = d
  }
  return { indices, maxDuration }
}

/** Array position in `words` of the active word at time t, or -1. */
export function activeIndexAt(words: TimedWord[], index: TimeIndex, t: number): number {
  const { indices, maxDuration } = index
  let lo = 0
  let hi = indices.length - 1
  let cut = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (words[indices[mid]].start <= t) {
      cut = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  if (cut === -1) return -1
  const floor = t - maxDuration
  let best = -1
  for (let k = cut; k >= 0; k--) {
    const i = indices[k]
    if (words[i].start < floor) break
    if (words[i].end > t && (best === -1 || i < best)) best = i
  }
  return best
}
