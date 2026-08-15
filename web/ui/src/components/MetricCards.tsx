import { cn } from '../lib/cn'

export interface Metric {
  label: string
  value: number | string
  tone: 'neutral' | 'ok' | 'error' | 'warning'
  hint?: string
}

const TONE: Record<Metric['tone'], string> = {
  neutral: 'text-ink',
  ok: 'text-accent',
  error: 'text-error',
  warning: 'text-warning',
}

export function MetricCards({ metrics }: { metrics: Metric[] }) {
  return (
    <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {metrics.map((m) => (
        <div key={m.label} className="panel px-4 py-3.5">
          <dt className="eyebrow">{m.label}</dt>
          <dd className={cn('mt-1.5 font-display text-[26px] font-semibold leading-none tracking-tight', TONE[m.tone])}>
            {m.value}
          </dd>
          {m.hint && <p className="mt-1.5 text-[11.5px] text-faint">{m.hint}</p>}
        </div>
      ))}
    </dl>
  )
}
