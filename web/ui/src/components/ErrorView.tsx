import { AlertTriangle, Info, RotateCcw } from 'lucide-react'

export interface ErrorShape {
  code: string
  message: string
}

// What happened / can it be retried / what to do next, per machine-readable
// error code (web/api.py raises these; toResult in lib/api.ts passes them
// through). Anything without a known code falls back to a generic,
// retryable error.
const GUIDANCE: Record<string, { title: string; retryable: boolean; action: string }> = {
  UPLOAD_TOO_LARGE: {
    title: 'Upload too large',
    retryable: false,
    action: 'Reduce the audio or transcript size and try again — the server rejects uploads above its configured limit before processing them.',
  },
  PIPELINE_FAILED: {
    title: 'Alignment failed',
    retryable: true,
    action: 'The server hit an unexpected error while processing your files. Wait a moment, then try again. If it keeps failing, check the server logs.',
  },
  FIXTURES_DISABLED: {
    title: 'Sample unavailable',
    retryable: false,
    action: 'The bundled sample is disabled on this server. Upload your own audio and transcript instead.',
  },
  INVALID_UPLOAD: {
    title: 'Unsupported file',
    retryable: false,
    action: 'Check the file formats — audio must be wav/mp3/m4a/mp4/flac/ogg and the transcript must be .txt or .docx — then try again.',
  },
  REQUEST_FAILED: {
    title: 'Request failed',
    retryable: true,
    action: 'The server could not complete the request. Check that it is running, then try again.',
  },
}

const FALLBACK: { title: string; retryable: boolean; action: string } = {
  title: 'Something went wrong',
  retryable: true,
  action: 'Check the server logs for details, then try again.',
}

export function ErrorView({
  error,
  onRetry,
  onBack,
}: {
  error: ErrorShape
  onRetry: () => void
  onBack: () => void
}) {
  const guidance = GUIDANCE[error.code] ?? FALLBACK

  return (
    <div className="panel mx-auto mt-16 max-w-[560px] p-8">
      <div className="flex items-start gap-4">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-error/15 text-error">
          <AlertTriangle className="h-[18px] w-[18px]" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 className="font-display text-[17px] font-semibold">{guidance.title}</h2>
          <p className="mt-2 break-words text-[13px] leading-relaxed text-muted">{error.message}</p>
          <p className="mt-1.5 font-mono text-[11px] text-faint">error {error.code}</p>
        </div>
      </div>
      <div className="mt-5 flex items-start gap-2.5 border-t border-hairline pt-4">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-faint" aria-hidden="true" />
        <p className="text-[12.5px] leading-relaxed text-muted">
          {guidance.retryable ? 'This can be retried. ' : 'This cannot be retried as-is. '}
          {guidance.action}
        </p>
      </div>
      <div className="mt-5 flex gap-3">
        {guidance.retryable && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-[13px] font-semibold text-[#08170f] transition-all duration-150 hover:brightness-110"
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" /> Try again
          </button>
        )}
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border border-hairline bg-surface-2 px-4 py-2 text-[13px] font-medium text-muted transition-colors duration-150 hover:text-ink"
        >
          Back
        </button>
      </div>
    </div>
  )
}
