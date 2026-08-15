import { CheckCircle2, CircleX, Info, TriangleAlert } from 'lucide-react'
import { cn } from '../lib/cn'
import type { Issue, Severity } from '../lib/api'

const SEVERITY_META: Record<
  Severity,
  { icon: typeof CircleX; label: string; color: string; bg: string }
> = {
  error: { icon: CircleX, label: 'Error', color: 'text-error', bg: 'bg-error/15' },
  warning: { icon: TriangleAlert, label: 'Warning', color: 'text-warning', bg: 'bg-warning/15' },
  info: { icon: Info, label: 'Info', color: 'text-info', bg: 'bg-info/15' },
}

export function QcTable({ issues }: { issues: Issue[] }) {
  if (issues.length === 0) {
    return (
      <div className="panel flex flex-col items-center gap-3 p-10 text-center">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-accent-dim text-accent">
          <CheckCircle2 className="h-5 w-5" aria-hidden="true" />
        </span>
        <p className="font-display text-[15px] font-semibold">No QC issues</p>
        <p className="max-w-[52ch] text-[12.5px] leading-relaxed text-muted">
          Every cue is within the caption constraints: two lines max, 42 characters per line, one to
          seven seconds, and no more than 21 characters per second.
        </p>
      </div>
    )
  }

  return (
    <div className="panel overflow-hidden">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-hairline">
            <th className="eyebrow px-4 py-3 font-medium sm:px-5">Severity</th>
            <th className="eyebrow px-4 py-3 font-medium sm:px-5">Code</th>
            <th className="eyebrow px-4 py-3 font-medium sm:px-5">Cue</th>
            <th className="eyebrow px-4 py-3 font-medium sm:px-5">Message</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, i) => {
            const meta = SEVERITY_META[issue.severity]
            const Icon = meta.icon
            return (
              <tr key={i} className="border-b border-hairline last:border-b-0">
                <td className="px-4 py-3 sm:px-5">
                  <span
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold',
                      meta.color,
                      meta.bg,
                    )}
                  >
                    <Icon className="h-3 w-3" aria-hidden="true" /> {meta.label}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono text-[11.5px] text-muted sm:px-5">{issue.code}</td>
                <td className="px-4 py-3 font-mono text-[11.5px] text-muted sm:px-5">
                  {issue.cue_index ?? '—'}
                </td>
                <td className="px-4 py-3 text-[13px] leading-relaxed sm:px-5">{issue.message}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
