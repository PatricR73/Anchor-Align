import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Spinner } from './Spinner'

const STAGES = [
  'Transcribing audio with faster-whisper',
  'Aligning words to STT timing',
  'Segmenting caption cues',
  'Running QC checks',
]

export function WorkingView({
  model,
  audioName,
  transcriptName,
}: {
  model: string
  audioName?: string
  transcriptName?: string
}) {
  const [stage, setStage] = useState(0)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const stageTimer = setInterval(() => setStage((s) => (s + 1) % STAGES.length), 2400)
    const clock = setInterval(() => setElapsed((v) => v + 1), 1000)
    return () => {
      clearInterval(stageTimer)
      clearInterval(clock)
    }
  }, [])

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="panel mx-auto mt-16 max-w-[560px] p-8 text-center"
    >
      <Spinner className="h-8 w-8" />
      <p role="status" aria-live="polite" className="mt-5 font-display text-[17px] font-semibold">
        {STAGES[stage]}…
      </p>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
        {audioName && transcriptName
          ? audioName + ' + ' + transcriptName
          : 'The first run may take a minute while the model loads.'}
      </p>
      <div className="mt-6 h-1 w-full overflow-hidden rounded-full bg-surface-3">
        <div className="h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full bg-accent" />
      </div>
      <p className="mt-3 font-mono text-[11px] text-faint">
        faster-whisper {model} · {elapsed}s
      </p>
    </motion.div>
  )
}
