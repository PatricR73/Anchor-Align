import { Download, FileJson, FileText, FileVideo } from 'lucide-react'
import type { AlignResult } from '../lib/api'
import { fmtBytes, stem } from '../lib/format'

function triggerDownload(name: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

const FORMATS = [
  {
    key: 'vtt',
    name: 'WebVTT',
    desc: 'The caption file for web players and streaming platforms.',
    mime: 'text/vtt',
    icon: FileVideo,
  },
  {
    key: 'srt',
    name: 'SubRip',
    desc: 'The near-universal subtitle format for editors and players.',
    mime: 'application/x-subrip',
    icon: FileText,
  },
  {
    key: 'confidence',
    name: 'Confidence report',
    desc: 'Per-cue mean and minimum confidence, to spot weak stretches.',
    mime: 'application/json',
    icon: FileJson,
  },
] as const

export function DownloadPanel({ result }: { result: AlignResult }) {
  const base = stem(result.audio_name)
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {FORMATS.map(({ key, name, desc, mime, icon: Icon }) => {
        const content = result.downloads[key]
        const filename = key === 'confidence' ? base + '.confidence.json' : base + '.' + key
        return (
          <div key={key} className="panel flex flex-col p-5">
            <span className="grid h-9 w-9 place-items-center rounded-md bg-accent-dim text-accent">
              <Icon className="h-4 w-4" aria-hidden="true" />
            </span>
            <h3 className="mt-3.5 font-display text-[14.5px] font-semibold">{name}</h3>
            <p className="mt-1.5 flex-1 text-[12px] leading-relaxed text-muted">{desc}</p>
            <p className="mt-3 font-mono text-[11px] text-faint">{filename} · {fmtBytes(content)}</p>
            <button
              type="button"
              onClick={() => triggerDownload(filename, content, mime)}
              className="mt-3.5 inline-flex items-center justify-center gap-2 rounded-md border border-hairline bg-surface-2 px-3 py-2 text-[12.5px] font-semibold text-ink transition-colors duration-150 hover:border-accent/40 hover:text-accent"
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" /> Download
            </button>
          </div>
        )
      })}
    </div>
  )
}
