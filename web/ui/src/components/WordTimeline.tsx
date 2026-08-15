import type { KeyboardEvent } from 'react'
import type { AlignedWord } from '../lib/api'
import { confidenceColor } from '../lib/colors'
import { fmtClock, fmtPct } from '../lib/format'

export function WordTimeline({
  words,
  duration,
  currentTime,
  onSeek,
}: {
  words: AlignedWord[]
  duration: number
  currentTime: number
  onSeek: (t: number) => void
}) {
  const safeDur = duration > 0 ? duration : 1
  const playheadPct = Math.min(100, (currentTime / safeDur) * 100)

  const onKeyDown = (e: KeyboardEvent) => {
    let t: number | null = null
    if (e.key === 'ArrowRight') t = currentTime + 1
    else if (e.key === 'ArrowLeft') t = currentTime - 1
    else if (e.key === 'Home') t = 0
    else if (e.key === 'End') t = duration
    if (t !== null) {
      e.preventDefault()
      onSeek(t)
    }
  }

  return (
    <div
      role="slider"
      tabIndex={0}
      aria-label="Seek through the aligned words"
      aria-valuemin={0}
      aria-valuemax={Math.round(duration * 1000)}
      aria-valuenow={Math.round(currentTime * 1000)}
      aria-valuetext={fmtClock(currentTime)}
      onKeyDown={onKeyDown}
      className="relative h-10 w-full min-w-0 cursor-pointer select-none rounded-md outline-none"
    >
      <div className="flex h-9 w-full items-stretch gap-px overflow-hidden rounded-md bg-surface-3">
        {words.map((w) => {
          const pct = Math.max(((w.end - w.start) / safeDur) * 100, 0.35)
          return (
            <button
              key={w.index}
              type="button"
              tabIndex={-1}
              title={w.text + ' · ' + fmtPct(w.confidence) + ' · ' + fmtClock(w.start) + '–' + fmtClock(w.end)}
              aria-hidden="true"
              onClick={() => onSeek(w.start)}
              style={{ width: pct + '%', backgroundColor: confidenceColor(w.confidence) }}
              className="h-full min-w-[2px] opacity-80 transition-opacity duration-150 hover:opacity-100"
            />
          )
        })}
      </div>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-0 h-full w-[2px] bg-ink/90 shadow-[0_0_6px_rgba(46,230,168,0.8)]"
        style={{ left: playheadPct + '%' }}
      />
    </div>
  )
}
