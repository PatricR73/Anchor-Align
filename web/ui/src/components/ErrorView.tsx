import { AlertTriangle, RotateCcw } from 'lucide-react'

export function ErrorView({
  error,
  onRetry,
  onBack,
}: {
  error: string
  onRetry: () => void
  onBack: () => void
}) {
  return (
    <div className="panel mx-auto mt-16 max-w-[560px] p-8">
      <div className="flex items-start gap-4">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-error/15 text-error">
          <AlertTriangle className="h-[18px] w-[18px]" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 className="font-display text-[17px] font-semibold">Alignment failed</h2>
          <p className="mt-2 break-words font-mono text-[12.5px] leading-relaxed text-muted">{error}</p>
        </div>
      </div>
      <div className="mt-6 flex gap-3">
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-[13px] font-semibold text-[#08170f] transition-all duration-150 hover:brightness-110"
        >
          <RotateCcw className="h-4 w-4" aria-hidden="true" /> Try again
        </button>
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
