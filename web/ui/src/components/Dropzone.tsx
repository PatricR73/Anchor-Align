import { useRef, useState, type DragEvent } from 'react'
import { FileAudio, FileText, X } from 'lucide-react'
import { cn } from '../lib/cn'

interface DropzoneProps {
  id: string
  label: string
  accept: string
  hint: string
  icon: 'audio' | 'text'
  file: File | null
  onFile: (f: File | null) => void
}

export function Dropzone({ id, label, accept, hint, icon, file, onFile }: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    const f = e.dataTransfer.files?.[0]
    if (f) onFile(f)
  }

  return (
    <div
      className={cn(
        'panel relative flex min-h-[148px] flex-col items-start justify-between gap-4 p-4 transition-colors duration-150',
        over && 'border-accent/50 bg-accent-dim',
      )}
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <label htmlFor={id} className="absolute inset-0 z-0 cursor-pointer" aria-label={label + ': drop a file or browse'}>
        <input
          ref={inputRef}
          id={id}
          type="file"
          accept={accept}
          className="sr-only"
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        />
      </label>

      <span className={'relative z-10 flex items-center gap-2.5' + (file ? '' : ' pointer-events-none')}>
        <span
          className={cn(
            'grid h-8 w-8 place-items-center rounded-md transition-colors duration-150',
            file ? 'bg-accent-dim text-accent' : 'bg-surface-3 text-muted',
          )}
        >
          {icon === 'audio' ? <FileAudio className="h-4 w-4" aria-hidden="true" /> : <FileText className="h-4 w-4" aria-hidden="true" />}
        </span>
        <span className="text-[13.5px] font-medium">{file ? file.name : label}</span>
      </span>

      {file ? (
        <div className="relative z-10 flex w-full items-center justify-between gap-2">
          <p className="min-w-0 truncate font-mono text-[11px] text-muted">{(file.size / 1024).toFixed(0)} KB</p>
          <button
            type="button"
            onClick={() => {
              onFile(null)
              if (inputRef.current) inputRef.current.value = ''
            }}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[11.5px] text-muted transition-colors hover:bg-surface-3 hover:text-ink"
            aria-label={'Remove ' + label.toLowerCase()}
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" /> Remove
          </button>
        </div>
      ) : (
        <p className="pointer-events-none relative z-10 text-[11.5px] leading-relaxed text-faint">
          Drop a file here — accepts {hint}.
        </p>
      )}
    </div>
  )
}
