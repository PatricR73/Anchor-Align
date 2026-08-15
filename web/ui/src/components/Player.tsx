import { Pause, Play } from 'lucide-react'
import type { AlignResult } from '../lib/api'
import { audioUrl } from '../lib/api'
import { fmtClock, fmtPct } from '../lib/format'
import type { Playback } from '../hooks/usePlayback'
import { WordTimeline } from './WordTimeline'

export function Player({ result, playback }: { result: AlignResult; playback: Playback }) {
  const { audioRef, playing, time, duration, seek, toggle } = playback

  return (
    <div className="panel p-4 sm:p-5">
      <audio ref={audioRef} src={audioUrl(result.audio_id)} preload="auto" className="hidden" />
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={toggle}
          aria-label={playing ? 'Pause' : 'Play'}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-accent text-[#08170f] transition-transform duration-150 hover:scale-105 active:scale-95"
        >
          {playing ? <Pause className="h-[18px] w-[18px]" aria-hidden="true" /> : <Play className="h-[18px] w-[18px] translate-x-[1px]" aria-hidden="true" />}
        </button>
        <WordTimeline words={result.aligned} duration={duration} currentTime={time} onSeek={seek} />
        <p className="w-[92px] shrink-0 text-right font-mono text-[12.5px] text-muted">
          {fmtClock(time)} <span className="text-faint">/</span> {fmtClock(duration)}
        </p>
      </div>
      <p className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-faint">
        <span className="max-w-[220px] truncate">{result.audio_name}</span>
        <span aria-hidden="true">·</span>
        <span>faster-whisper {result.model}</span>
        <span aria-hidden="true">·</span>
        <span>
          mean word confidence{' '}
          {result.stats.mean_confidence !== null ? fmtPct(result.stats.mean_confidence) : '—'}
        </span>
      </p>
    </div>
  )
}
