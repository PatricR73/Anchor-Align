import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

export interface TabDef {
  id: string
  label: string
  badge?: number
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: TabDef[]
  active: string
  onChange: (id: string) => void
}) {
  return (
    <div role="tablist" aria-label="Result sections" className="flex gap-1 overflow-x-auto border-b border-hairline">
      {tabs.map((t) => {
        const selected = t.id === active
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={'tab-' + t.id}
            aria-selected={selected}
            aria-controls={'tabpanel-' + t.id}
            onClick={() => onChange(t.id)}
            className={cn(
              'relative whitespace-nowrap px-3.5 py-2.5 text-[13.5px] font-medium transition-colors duration-150 sm:px-4',
              selected ? 'text-ink' : 'text-muted hover:text-ink',
            )}
          >
            {t.label}
            {t.badge !== undefined && t.badge > 0 && (
              <span
                className={cn(
                  'ml-1.5 rounded-full px-1.5 py-0.5 font-mono text-[10px]',
                  selected ? 'bg-accent-dim text-accent' : 'bg-surface-3 text-muted',
                )}
              >
                {t.badge}
              </span>
            )}
            {selected && (
              <motion.span
                layoutId="tab-underline"
                className="absolute inset-x-2 -bottom-px h-px bg-accent"
                transition={{ type: 'spring', stiffness: 500, damping: 40 }}
              />
            )}
          </button>
        )
      })}
    </div>
  )
}

export function TabPanel({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={'tabpanel-' + id} aria-labelledby={'tab-' + id} className="pt-6">
      {children}
    </div>
  )
}
