import { cn } from '../lib/cn'
import { MODEL_OPTIONS, type Model } from '../lib/api'

interface OptionsBarProps {
  model: Model
  onModel: (m: Model) => void
  phonetic: boolean
  onPhonetic: (v: boolean) => void
}

export function OptionsBar({ model, onModel, phonetic, onPhonetic }: OptionsBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-7 gap-y-3">
      <label className="flex items-center gap-2.5">
        <span className="eyebrow">Model</span>
        <select
          value={model}
          onChange={(e) => onModel(e.target.value as Model)}
          className="rounded-md border border-hairline bg-surface-2 px-2.5 py-1.5 font-mono text-[12.5px] text-ink transition-colors duration-150 hover:border-accent/40"
        >
          {MODEL_OPTIONS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>

      <div className="flex items-center gap-2.5">
        <span className="eyebrow">Phonetic match</span>
        <button
          type="button"
          role="switch"
          aria-checked={phonetic}
          aria-label="Phonetic matching"
          onClick={() => onPhonetic(!phonetic)}
          className={cn(
            'relative h-5 w-9 shrink-0 rounded-full transition-colors duration-150',
            phonetic ? 'bg-accent' : 'bg-surface-3',
          )}
        >
          <span
            className={cn(
              'absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-ink transition-transform duration-150',
              phonetic && 'translate-x-4',
            )}
          />
        </button>
        <span className="text-[12px] text-muted">Double Metaphone — opt-in, can help with homophone mishearings</span>
      </div>
    </div>
  )
}
