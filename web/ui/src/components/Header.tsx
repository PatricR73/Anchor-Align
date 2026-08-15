import { AudioWaveform } from 'lucide-react'

export function Header() {
  return (
    <header className="mx-auto flex w-full max-w-[1180px] items-center justify-between px-4 pb-2 pt-8 sm:px-6">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-[10px] bg-accent-dim ring-1 ring-accent/35">
          <AudioWaveform className="h-[18px] w-[18px] text-accent" aria-hidden="true" />
        </div>
        <div>
          <h1 className="font-display text-[19px] font-semibold leading-none tracking-tight">anchor-align</h1>
          <p className="mt-1 text-[12.5px] leading-none text-muted">timed captions from edited transcripts</p>
        </div>
      </div>
      <p className="hidden font-mono text-[11px] uppercase tracking-[0.14em] text-faint sm:block">
        vtt · srt · qc
      </p>
    </header>
  )
}
