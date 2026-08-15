import { useCallback, useState } from 'react'
import type { AlignedWord } from '../lib/api'
import { fmtClock, fmtPct } from '../lib/format'

export const TOOLTIP_ID = 'aa-tooltip'

// The word detail shown in tooltips (hover AND focus), replacing native
// title attributes: no ~500ms delay, works with the roving focus, and is
// announced via aria-describedby instead of inconsistent title behavior.
export function wordTooltipText(w: AlignedWord): string {
  return w.text + ' — ' + w.match_type + ' · confidence ' + fmtPct(w.confidence) + ' · ' + fmtClock(w.start) + '–' + fmtClock(w.end)
}

export interface TooltipState {
  text: string
  x: number
  y: number
  visible: boolean
}

export function useTooltip() {
  const [tip, setTip] = useState<TooltipState>({ text: '', x: 0, y: 0, visible: false })
  const show = useCallback((text: string, rect: DOMRect) => {
    setTip({ text, x: rect.left, y: rect.top, visible: true })
  }, [])
  const hide = useCallback(() => setTip((t) => (t.visible ? { ...t, visible: false } : t)), [])
  return { tip, show, hide }
}

export function Tooltip({ tip }: { tip: TooltipState }) {
  if (!tip.visible) return null
  const above = tip.y > 48
  return (
    <div
      id={TOOLTIP_ID}
      role="tooltip"
      className="pointer-events-none fixed z-50 max-w-[280px] rounded-md border border-hairline bg-surface-3 px-2.5 py-1.5 font-mono text-[11px] leading-relaxed text-ink shadow-[0_8px_24px_rgba(0,0,0,0.5)]"
      style={{ left: Math.max(8, Math.min(tip.x, (typeof window !== 'undefined' ? window.innerWidth : 1200) - 290)), top: above ? tip.y - 36 : tip.y + 20 }}
    >
      {tip.text}
    </div>
  )
}
