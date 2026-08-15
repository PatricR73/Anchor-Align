import type { Cue } from '../lib/api'
import { fmtStamp } from '../lib/format'

export function CuesTable({ cues, onSeek }: { cues: Cue[]; onSeek: (t: number) => void }) {
  if (cues.length === 0) {
    return (
      <div className="panel p-8 text-center text-[13.5px] text-muted">
        No cues were produced — check the QC report for details.
      </div>
    )
  }

  return (
    <ol className="panel overflow-hidden">
      {cues.map((cue) => (
        <li key={cue.index} className="border-b border-hairline last:border-b-0">
          <button
            type="button"
            onClick={() => onSeek(cue.start)}
            title="Jump the player to this cue"
            className="flex w-full items-start gap-4 px-4 py-3 text-left transition-colors duration-150 hover:bg-surface-2 sm:px-5"
          >
            <span className="mt-0.5 w-7 shrink-0 font-mono text-[11.5px] text-faint">
              {String(cue.index).padStart(2, '0')}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-mono text-[11.5px] text-muted">
                {fmtStamp(cue.start)} <span className="text-faint">→</span> {fmtStamp(cue.end)}
              </span>
              <span className="mt-1 block text-[15px] leading-relaxed text-ink">
                {cue.lines.map((line, i) => (
                  <span key={i}>
                    {i > 0 && <span className="text-faint"> / </span>}
                    {line}
                  </span>
                ))}
              </span>
            </span>
            <span className="mt-1 hidden shrink-0 text-[11.5px] text-faint sm:block">
              {(cue.end - cue.start).toFixed(1)}s
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}
