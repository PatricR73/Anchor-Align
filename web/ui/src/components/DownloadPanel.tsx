import { Download, FileJson, FileText, FileVideo } from 'lucide-react'
import type { AlignResult } from '../lib/api'
import { fmtBytes, stem } from '../lib/format'

// The download content is served by the API (GET /api/download/{audio_id}/
// {fmt}) — the golden-tested exporters own VTT/SRT formatting, and the align
// response carries only byte sizes. This fetches the artifact and saves it
// under the same filename the previous implementation produced, so the
// downloaded bytes are identical.
async function fetchAndSave(audioId: string, fmt: string, name: string) {
  const res = await fetch(`/api/download/${audioId}/${fmt}`)
  if (!res.ok) {
    throw new Error(`download failed (HTTP ${res.status})`)
  }
  const blob = await res.blob()
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
    icon: FileVideo,
  },
  {
    key: 'srt',
    name: 'SubRip',
    desc: 'The near-universal subtitle format for editors and players.',
    icon: FileText,
  },
  {
    key: 'confidence',
    name: 'Confidence report',
    desc: 'Per-cue mean and minimum confidence, to spot weak stretches.',
    icon: FileJson,
  },
] as const

export function DownloadPanel({ result }: { result: AlignResult }) {
  const base = stem(result.audio_name)
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {FORMATS.map(({ key, name, desc, icon: Icon }) => {
        const size = result.downloads[key]
        const filename = key === 'confidence' ? base + '.confidence.json' : base + '.' + key
        return (
          <div key={key} className="panel flex flex-col p-5">
            <span className="grid h-9 w-9 place-items-center rounded-md bg-accent-dim text-accent">
              <Icon className="h-4 w-4" aria-hidden="true" />
            </span>
            <h3 className="mt-3.5 font-display text-[14.5px] font-semibold">{name}</h3>
            <p className="mt-1.5 flex-1 text-[12px] leading-relaxed text-muted">{desc}</p>
            <p className="mt-3 font-mono text-[11px] text-faint">{filename} · {fmtBytes(size)}</p>
            <button
              type="button"
              onClick={() => {
                void fetchAndSave(result.audio_id, key, filename).catch((e) => console.error(e))
              }}
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
