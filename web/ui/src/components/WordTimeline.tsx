import { memo, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type RefObject } from 'react'
import type { AlignedWord } from '../lib/api'
import { activeIndexAt, buildTimeIndex } from '../lib/activeWord'
import { confidenceColor, confidenceHeight } from '../lib/colors'
import { fmtClock } from '../lib/format'
import { cn } from '../lib/cn'
import { TOOLTIP_ID, Tooltip, useTooltip, wordTooltipText } from './Tooltip'

interface Column {
  /** weakest word covering this 1px column — see the bucketing comment */
  word: AlignedWord
  color: string
}

// Purely visual pixel-column layer. It is aria-hidden, carries no click
// handler and no cursor — the slider above it is the interactive element and
// resolves clicks by hit-testing (composable with the absolute positioning).
// It never receives currentTime, so React.memo skips it during playback.
const SegmentsLayer = memo(function SegmentsLayer({
  words,
  duration,
  width,
}: {
  words: AlignedWord[]
  duration: number
  width: number
}) {
  const safeDur = duration > 0 ? duration : 1

  // Bucket words into 1px columns. A word's true visual width is
  // (end - start) / duration of the strip; sub-pixel words would vanish if
  // inflated with a min-width floor. Each column renders the MINIMUM-
  // confidence word covering it, so an isolated weak word stays visible.
  const columns = useMemo(() => {
    if (width <= 0 || words.length === 0 || safeDur <= 0) return []
    const cols: (Column | null)[] = new Array(width).fill(null)
    for (const w of words) {
      const c0 = Math.floor((w.start / safeDur) * width)
      const c1 = Math.max(c0 + 1, Math.ceil((w.end / safeDur) * width))
      const hi = Math.min(c1, width)
      for (let c = c0; c < hi; c++) {
        const cur = cols[c]
        if (cur === null || w.confidence < cur.word.confidence) {
          cols[c] = { word: w, color: confidenceColor(w.confidence) }
        }
      }
    }
    return cols
  }, [words, width, safeDur])

  return (
    <div aria-hidden="true" className="absolute inset-x-0 top-0.5 h-9 overflow-hidden rounded-md bg-surface-3">
      {columns.map((col, c) =>
        col ? (
          <div
            key={c}
            data-start={col.word.start}
            className="absolute bottom-0 opacity-80 transition-opacity duration-150 hover:opacity-100"
            style={{
              left: c,
              width: 1,
              height: confidenceHeight(col.word.confidence) * 100 + '%',
              backgroundColor: col.color,
            }}
          />
        ) : null,
      )}
    </div>
  )
})

export function WordTimeline({
  words,
  duration,
  time,
  playheadRef,
  onSeek,
}: {
  words: AlignedWord[]
  duration: number
  time: number
  playheadRef: RefObject<HTMLDivElement | null>
  onSeek: (t: number) => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)
  const { tip, show, hide } = useTooltip()
  const safeDur = duration > 0 ? duration : 1

  const timeIndex = useMemo(() => buildTimeIndex(words), [words])

  // keep the pixel-bucket count in sync with the rendered strip
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => setWidth(el.clientWidth)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const showWordTooltip = useCallback(
    (w: AlignedWord, x: number, y: number) => show(wordTooltipText(w), new DOMRect(x, y, 0, 0)),
    [show],
  )

  // Click-to-seek by hit-testing: the slider is the leaf interactive role;
  // its children are not interactive. The click position resolves to a pixel
  // column, and the column's MINIMUM-confidence word wins — the same rule the
  // SegmentsLayer buckets by, so a 1px column (which can span seconds of
  // audio) always seeks to the word its color represents, not whichever word
  // happens to sit under the exact click time.
  const handleSeekClick = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      const rect = e.currentTarget.getBoundingClientRect()
      const c = Math.max(0, Math.min(Math.round(rect.width) - 1, Math.floor(e.clientX - rect.left)))
      const t0 = (c / (rect.width || 1)) * safeDur
      const t1 = ((c + 1) / (rect.width || 1)) * safeDur
      let best: AlignedWord | null = null
      for (const w of words) {
        if (w.end <= t0 || w.start >= t1) continue
        if (best === null || w.confidence < best.confidence) best = w
      }
      if (best) onSeek(best.start)
    },
    [words, safeDur, onSeek],
  )

  const handleHover = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      const rect = e.currentTarget.getBoundingClientRect()
      const t = ((e.clientX - rect.left) / (rect.width || 1)) * safeDur
      const i = activeIndexAt(words, timeIndex, t)
      if (i >= 0) showWordTooltip(words[i], e.clientX, e.clientY)
    },
    [words, timeIndex, safeDur, showWordTooltip],
  )

  // focus trigger: the slider shows the active word's detail
  const handleFocus = useCallback(() => {
    const i = activeIndexAt(words, timeIndex, time)
    if (i >= 0) {
      const el = containerRef.current
      if (el) showWordTooltip(words[i], el.getBoundingClientRect().left, el.getBoundingClientRect().top)
    }
  }, [words, timeIndex, time, showWordTooltip])

  const onKeyDown = (e: KeyboardEvent) => {
    let t: number | null = null
    if (e.key === 'ArrowRight') t = time + 1
    else if (e.key === 'ArrowLeft') t = time - 1
    else if (e.key === 'Home') t = 0
    else if (e.key === 'End') t = duration
    if (t !== null) {
      e.preventDefault()
      onSeek(t)
    }
  }

  return (
    <div
      ref={containerRef}
      role="slider"
      tabIndex={0}
      aria-label="Seek through the aligned words"
      aria-describedby={tip.visible ? TOOLTIP_ID : undefined}
      aria-valuemin={0}
      aria-valuemax={Math.round(duration * 1000)}
      aria-valuenow={Math.round(time * 1000)}
      aria-valuetext={fmtClock(time)}
      onClick={handleSeekClick}
      onMouseMove={handleHover}
      onMouseLeave={hide}
      onFocus={handleFocus}
      onBlur={hide}
      onKeyDown={onKeyDown}
      className={cn('relative h-10 w-full min-w-0 cursor-pointer select-none rounded-md')}
    >
      <SegmentsLayer words={words} duration={duration} width={width} />
      {/* full-width wrapper: translateX(pct%) moves it pct of the strip width;
          the visible 2px line sits at its left edge. Written imperatively. */}
      <div
        ref={playheadRef}
        aria-hidden="true"
        data-playhead
        className="pointer-events-none absolute inset-y-0 left-0 w-full"
      >
        <div className="absolute left-0 top-0 h-full w-[2px] bg-ink/90 shadow-[0_0_6px_rgba(46,230,168,0.8)]" />
      </div>
      <Tooltip tip={tip} />
    </div>
  )
}
