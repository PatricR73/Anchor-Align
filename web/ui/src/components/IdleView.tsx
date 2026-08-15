import { motion } from 'motion/react'
import { ArrowRight, Sparkles } from 'lucide-react'
import { cn } from '../lib/cn'
import { AUDIO_ACCEPT, TRANSCRIPT_ACCEPT, type Model } from '../lib/api'
import { Dropzone } from './Dropzone'
import { OptionsBar } from './OptionsBar'

interface IdleViewProps {
  audio: File | null
  transcript: File | null
  model: Model
  phonetic: boolean
  onAudio: (f: File | null) => void
  onTranscript: (f: File | null) => void
  onModel: (m: Model) => void
  onPhonetic: (v: boolean) => void
  onAlign: () => void
  onSample: () => void
}

export function IdleView({
  audio,
  transcript,
  model,
  phonetic,
  onAudio,
  onTranscript,
  onModel,
  onPhonetic,
  onAlign,
  onSample,
}: IdleViewProps) {
  const ready = audio !== null && transcript !== null

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: 'easeOut' }}
    >
      <div className="pb-8 pt-10 sm:pt-14">
        <h2 className="font-display text-[26px] font-semibold leading-tight tracking-tight sm:text-[32px]">
          Turn an edited transcript into timed captions.
        </h2>
        <p className="mt-3 max-w-[62ch] text-[15px] leading-relaxed text-muted">
          Upload the audio and the human-edited transcript. anchor-align recovers word timings from
          speech-to-text, segments them into caption cues, and runs QC — VTT, SRT and a confidence
          report come out the other side.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <Dropzone
          id="audio-file"
          label="Audio"
          accept={AUDIO_ACCEPT}
          hint="wav · mp3 · m4a · mp4 · flac · ogg"
          icon="audio"
          file={audio}
          onFile={onAudio}
        />
        <Dropzone
          id="transcript-file"
          label="Edited transcript"
          accept={TRANSCRIPT_ACCEPT}
          hint=".txt · .docx"
          icon="text"
          file={transcript}
          onFile={onTranscript}
        />
      </div>

      <div className="panel mt-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-4 px-4 py-3.5">
        <OptionsBar model={model} onModel={onModel} phonetic={phonetic} onPhonetic={onPhonetic} />
        <button
          type="button"
          disabled={!ready}
          onClick={onAlign}
          className={cn(
            'inline-flex items-center gap-2 rounded-md px-4 py-2.5 text-[13.5px] font-semibold transition-all duration-150',
            ready
              ? 'bg-accent text-[#08170f] hover:brightness-110'
              : 'cursor-not-allowed bg-surface-3 text-faint',
          )}
        >
          Align captions
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <div className="mt-7 flex items-center gap-3">
        <span className="h-px flex-1 bg-hairline" />
        <span className="eyebrow">or</span>
        <span className="h-px flex-1 bg-hairline" />
      </div>

      <div className="mt-6 flex justify-center">
        <button
          type="button"
          onClick={onSample}
          className="group inline-flex items-center gap-2 rounded-md border border-hairline bg-surface-2 px-4 py-2.5 text-[13.5px] font-medium text-ink transition-colors duration-150 hover:border-accent/40 hover:text-accent"
        >
          <Sparkles className="h-4 w-4 text-accent" aria-hidden="true" />
          Run the bundled sample
          <span className="font-mono text-[11px] text-faint">33.9s audio</span>
        </button>
      </div>
    </motion.section>
  )
}
