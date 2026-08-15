import { Fragment } from 'react'
import type { AlignedWord } from '../lib/api'
import { confidenceColor } from '../lib/colors'
import { fmtClock, fmtPct } from '../lib/format'
import { cn } from '../lib/cn'

export function TranscriptHeatmap({
  words,
  activeIndex,
  interpolatedCount,
  onSeek,
}: {
  words: AlignedWord[]
  activeIndex: number
  interpolatedCount: number
  onSeek: (t: number) => void
}) {
  return (
    <div className="panel p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-display text-[15px] font-semibold">Aligned transcript</h3>
        <p className="text-[11.5px] text-faint">click a word to seek · hover a word for details</p>
      </div>

      <p className="mt-4 text-[15px] leading-[2.6] tracking-[0.005em]">
        {words.map((w, i) => (
          <Fragment key={w.index}>
            {i > 0 ? ' ' : null}
          <span
            onClick={() => onSeek(w.start)}
            title={
              w.text +
              ' — ' +
              w.match_type +
              ' · confidence ' +
              fmtPct(w.confidence) +
              ' · ' +
              fmtClock(w.start) +
              '–' +
              fmtClock(w.end)
            }
            className={cn(
              'mx-[1.5px] cursor-pointer rounded-[3px] px-[1px] font-medium transition-colors duration-150 hover:bg-surface-3',
              activeIndex === w.index && 'bg-accent-dim ring-1 ring-accent/60',
              w.match_type === 'interpolated' && 'underline decoration-dashed decoration-faint underline-offset-[5px]',
            )}
            style={{ color: confidenceColor(w.confidence) }}
          >
            {w.text}
          </span>
          </Fragment>
        ))}
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-hairline pt-3.5">
        <span className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: confidenceColor(0) }} />
          low confidence
        </span>
        <span className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: confidenceColor(0.5) }} />
          mid
        </span>
        <span className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: confidenceColor(1) }} />
          high
        </span>
        <span className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="inline-block w-4 border-t border-dashed border-faint" />
          interpolated — no direct STT evidence
        </span>
        {interpolatedCount > 0 && (
          <span className="font-mono text-[11px] text-faint">{interpolatedCount} words</span>
        )}
      </div>
    </div>
  )
}
