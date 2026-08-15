import { Fragment, memo, useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { AlignedWord } from '../lib/api'
import { confidenceColor, confidenceFontWeight } from '../lib/colors'
import { cn } from '../lib/cn'
import { TOOLTIP_ID, Tooltip, useTooltip, wordTooltipText } from './Tooltip'

// Per-word listbox option, memo'd on (word, active, focused, ...): when the
// active word or the roving focus changes, only the affected options
// re-render — the other ~9,000 are prop-equal and skipped.
const HeatmapWord = memo(function HeatmapWord({
  word,
  active,
  focused,
  onSeek,
  onShowTooltip,
  onHideTooltip,
}: {
  word: AlignedWord
  active: boolean
  focused: boolean
  onSeek: (t: number) => void
  onShowTooltip: (w: AlignedWord, rect: DOMRect) => void
  onHideTooltip: () => void
}) {
  return (
    <span
      id={'heatmap-word-' + word.index}
      role="option"
      aria-selected={active}
      aria-describedby={focused ? TOOLTIP_ID : undefined}
      data-start={word.start}
      onClick={() => onSeek(word.start)}
      onMouseEnter={(e) => onShowTooltip(word, e.currentTarget.getBoundingClientRect())}
      onMouseLeave={onHideTooltip}
      className={cn(
        'mx-[1.5px] cursor-pointer rounded-[3px] px-[1px] font-medium transition-colors duration-150 hover:bg-surface-3',
        active && 'bg-accent-dim ring-1 ring-accent/60',
        focused && 'ring-1 ring-accent',
        word.match_type === 'interpolated' && 'underline decoration-dashed decoration-faint underline-offset-[5px]',
      )}
      style={{ color: confidenceColor(word.confidence), fontWeight: confidenceFontWeight(word.confidence) }}
    >
      {word.text}
    </span>
  )
})

// Memo'd: words/onSeek/interpolatedCount are stable per payload and the
// active word updates only at word boundaries, so this re-renders there,
// not per playback frame.
export const TranscriptHeatmap = memo(function TranscriptHeatmap({
  words,
  activeIndex,
  interpolatedCount,
  onSeek,
}: {
  words: AlignedWord[]
  activeIndex: number
  interpolatedCount: number
  onSeek: (t: number) => void
}) {
  const { tip, show, hide } = useTooltip()
  const [focusedIndex, setFocusedIndex] = useState(-1)
  // true while the cursor moves by arrow/Home/End keys — a mouse focus must
  // not scroll the document (that would swallow the very click that focused)
  const keyboardNavRef = useRef(false)

  const showTooltip = useCallback((w: AlignedWord, rect: DOMRect) => show(wordTooltipText(w), rect), [show])
  const hideTooltip = useCallback(() => hide(), [hide])

  // Roving tabindex: ONE tab stop on the container; arrows move the active
  // descendant, Home/End jump, Enter/Space seeks. No per-word tab stops.
  const onKeyDown = (e: KeyboardEvent<HTMLParagraphElement>) => {
    const base = focusedIndex >= 0 ? focusedIndex : activeIndex >= 0 ? activeIndex : 0
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      keyboardNavRef.current = true
      setFocusedIndex(Math.min(words.length - 1, base + 1))
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      keyboardNavRef.current = true
      setFocusedIndex(Math.max(0, base - 1))
    } else if (e.key === 'Home') {
      e.preventDefault()
      keyboardNavRef.current = true
      setFocusedIndex(0)
    } else if (e.key === 'End') {
      e.preventDefault()
      keyboardNavRef.current = true
      setFocusedIndex(words.length - 1)
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      if (words[base]) onSeek(words[base].start)
    }
  }

  // On focus, establish the cursor (a click on an option focuses the
  // container; the cursor must not trigger a scroll — that would swallow the
  // click). On blur, release it and hide the tooltip.
  const onContainerFocus = () => {
    keyboardNavRef.current = false
    setFocusedIndex((cur) => (cur >= 0 ? cur : activeIndex >= 0 ? activeIndex : 0))
  }
  const onContainerBlur = () => {
    setFocusedIndex(-1)
    hideTooltip()
  }

  // Keyboard-navigated options scroll into view and show their tooltip (the
  // focus trigger half of the tooltip contract). Mouse focus never scrolls.
  useEffect(() => {
    if (focusedIndex < 0 || !words[focusedIndex] || !keyboardNavRef.current) return
    const el = document.getElementById('heatmap-word-' + words[focusedIndex].index)
    el?.scrollIntoView({ block: 'nearest' })
    if (el) showTooltip(words[focusedIndex], el.getBoundingClientRect())
  }, [focusedIndex, words, showTooltip])

  return (
    <div className="panel p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-display text-[15px] font-semibold">Aligned transcript</h3>
        <p className="text-[11.5px] text-faint">click or arrow+Enter to seek · hover or focus for details</p>
      </div>

      <p
        role="listbox"
        aria-label="Aligned transcript words — arrow keys move, Enter seeks"
        aria-activedescendant={
          focusedIndex >= 0 && words[focusedIndex] ? 'heatmap-word-' + words[focusedIndex].index : undefined
        }
        tabIndex={0}
        onKeyDown={onKeyDown}
        onFocus={onContainerFocus}
        onBlur={onContainerBlur}
        className="mt-4 text-[15px] leading-[2.6] tracking-[0.005em]"
      >
        {words.map((w, i) => (
          <Fragment key={w.index}>
            {i > 0 ? ' ' : null}
            <HeatmapWord
              word={w}
              active={activeIndex === i}
              focused={focusedIndex === i}
              onSeek={onSeek}
              onShowTooltip={showTooltip}
              onHideTooltip={hideTooltip}
            />
          </Fragment>
        ))}
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-hairline pt-3.5">
        <span className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: confidenceColor(0) }} />
          likely misheard — check this
        </span>
        <span className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: confidenceColor(0.5) }} />
          may be off — verify the timing
        </span>
        <span className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: confidenceColor(1) }} />
          matched cleanly — no action
        </span>
        <span className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <span className="inline-block w-4 border-t border-dashed border-faint" />
          interpolated — no direct STT evidence
        </span>
        <span className="flex items-center gap-1.5 text-[11.5px] text-faint">
          <span className="inline-block h-2 w-2 rounded-[1px] bg-faint/60" />
          thin words and short bars = lower confidence
        </span>
        {interpolatedCount > 0 && (
          <span className="font-mono text-[11px] text-faint">{interpolatedCount} words</span>
        )}
      </div>
      <Tooltip tip={tip} />
    </div>
  )
})
