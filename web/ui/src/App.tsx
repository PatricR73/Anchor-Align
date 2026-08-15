import { useCallback, useState } from 'react'
import { MotionConfig } from 'motion/react'
import { alignAudio, ApiError, fetchSample, type AlignResult, type Model } from './lib/api'
import { Header } from './components/Header'
import { IdleView } from './components/IdleView'
import { WorkingView } from './components/WorkingView'
import { ErrorView } from './components/ErrorView'
import { ResultView } from './components/ResultView'

type Phase = 'idle' | 'working' | 'done' | 'error'

export default function App() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [result, setResult] = useState<AlignResult | null>(null)
  const [error, setError] = useState<{ code: string; message: string } | null>(null)
  // null = not uploading (processing, or the sample which needs no upload);
  // 0..99 = upload in progress; 100 = upload done, processing
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)

  const [audio, setAudio] = useState<File | null>(null)
  const [transcript, setTranscript] = useState<File | null>(null)
  const [model, setModel] = useState<Model>('base')
  const [phonetic, setPhonetic] = useState(false)

  const run = useCallback(async (a: File, t: File, m: Model, ph: boolean) => {
    setPhase('working')
    setUploadProgress(0)
    setError(null)
    try {
      setResult(
        await alignAudio(a, t, m, ph, (sent, total) => {
          setUploadProgress(total > 0 ? Math.round((sent / total) * 100) : 0)
        }),
      )
      setPhase('done')
    } catch (e) {
      setError(
        e instanceof ApiError
          ? { code: e.code, message: e.message }
          : { code: 'UNKNOWN', message: e instanceof Error ? e.message : String(e) },
      )
      setPhase('error')
    }
  }, [])

  const handleAlign = useCallback(() => {
    if (audio && transcript) void run(audio, transcript, model, phonetic)
  }, [audio, transcript, model, phonetic, run])

  const handleSample = useCallback(async () => {
    setPhase('working')
    setUploadProgress(null)
    setError(null)
    try {
      setResult(await fetchSample())
      setPhase('done')
    } catch (e) {
      setError(
        e instanceof ApiError
          ? { code: e.code, message: e.message }
          : { code: 'UNKNOWN', message: e instanceof Error ? e.message : String(e) },
      )
      setPhase('error')
    }
  }, [])

  const reset = useCallback(() => {
    setPhase('idle')
    setResult(null)
    setError(null)
  }, [])

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex min-h-screen flex-col bg-bg">
        <Header />
        <main className="mx-auto w-full max-w-[1180px] flex-1 px-4 pb-20 sm:px-6">
          {phase === 'idle' && (
            <IdleView
              audio={audio}
              transcript={transcript}
              model={model}
              phonetic={phonetic}
              onAudio={setAudio}
              onTranscript={setTranscript}
              onModel={setModel}
              onPhonetic={setPhonetic}
              onAlign={handleAlign}
              onSample={handleSample}
            />
          )}
          {phase === 'working' && (
            <WorkingView
              model={model}
              audioName={audio?.name}
              transcriptName={transcript?.name}
              uploadProgress={uploadProgress}
            />
          )}
          {phase === 'error' && (
            <ErrorView
              error={error ?? { code: 'UNKNOWN', message: 'Unknown error' }}
              onRetry={handleAlign}
              onBack={reset}
            />
          )}
          {phase === 'done' && result && <ResultView result={result} onReset={reset} />}
        </main>
        <footer className="border-t border-hairline py-6">
          <p className="mx-auto max-w-[1180px] px-4 text-center font-mono text-[11px] text-faint sm:px-6">
            anchor-align — recovers word timing for human-edited transcripts and emits compliant
            VTT/SRT caption cues
          </p>
        </footer>
      </div>
    </MotionConfig>
  )
}
