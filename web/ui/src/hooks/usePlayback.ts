import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AlignResult } from '../lib/api'
import { activeIndexAt, buildTimeIndex } from '../lib/activeWord'

export interface Playback {
  audioRef: React.RefObject<HTMLAudioElement | null>
  /** the timeline playhead node, written imperatively outside React */
  playheadRef: React.RefObject<HTMLDivElement | null>
  playing: boolean
  time: number
  duration: number
  seek: (t: number) => void
  toggle: () => void
  /** array position of the active word in result.aligned — NOT token.index */
  activeIndex: number
}

export function usePlayback(result: AlignResult): Playback {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const playheadRef = useRef<HTMLDivElement | null>(null)
  const [playing, setPlaying] = useState(false)
  // time is deliberately low-frequency: it drives the time display and the
  // slider aria values, updating from the audio element timeupdate events
  // (~4 Hz) plus seeks — never from the 60fps playhead loop.
  const [time, setTime] = useState(0)
  const [activeIndex, setActiveIndex] = useState(-1)
  const lastActiveRef = useRef(-1)
  const [duration, setDuration] = useState(result.audio_duration_s)

  useEffect(() => {
    const a = audioRef.current
    if (!a) return
    const onTime = () => setTime(a.currentTime)
    const onMeta = () => {
      if (Number.isFinite(a.duration) && a.duration > 0) setDuration(a.duration)
    }
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    a.addEventListener('timeupdate', onTime)
    a.addEventListener('seeked', onTime)
    a.addEventListener('loadedmetadata', onMeta)
    a.addEventListener('durationchange', onMeta)
    a.addEventListener('play', onPlay)
    a.addEventListener('pause', onPause)
    return () => {
      a.removeEventListener('timeupdate', onTime)
      a.removeEventListener('seeked', onTime)
      a.removeEventListener('loadedmetadata', onMeta)
      a.removeEventListener('durationchange', onMeta)
      a.removeEventListener('play', onPlay)
      a.removeEventListener('pause', onPause)
    }
  }, [])

  // The playhead is written directly to the DOM (transform on the ref'd
  // node) so the 60fps updates never trigger a React render — the timeline's
  // segment layer is memo'd and never receives currentTime.
  const writePlayhead = useCallback(
    (t: number) => {
      const node = playheadRef.current
      if (!node) return
      const safeDur = duration > 0 ? duration : 1
      const pct = Math.min(100, (t / safeDur) * 100)
      node.style.transform = 'translateX(' + pct + '%)'
    },
    [duration],
  )

  // Sorted index built ONCE per payload (never per time change): edited
  // order is non-monotonic in time, so the binary search runs over this
  // time-sorted index array instead (see lib/activeWord.ts for the overlap
  // semantics it preserves).
  const timeIndex = useMemo(() => buildTimeIndex(result.aligned), [result.aligned])

  const activeAt = useCallback(
    (t: number) => activeIndexAt(result.aligned, timeIndex, t),
    [result.aligned, timeIndex],
  )

  // dev-only exposure so the Playwright sweep test can compare the real
  // implementation against the reference linear scan (dead code in prod)
  useEffect(() => {
    if (!import.meta.env.DEV) return
    ;(window as unknown as { __activeWord?: unknown }).__activeWord = { activeIndexAt, buildTimeIndex }
  }, [])

  // rAF loop: writes the playhead directly and updates the active word ONLY
  // when it changes — no React render happens per frame.
  useEffect(() => {
    if (!playing) return
    let raf = 0
    const loop = () => {
      const a = audioRef.current
      const t = a ? a.currentTime : 0
      writePlayhead(t)
      const idx = activeAt(t)
      if (idx !== lastActiveRef.current) {
        lastActiveRef.current = idx
        setActiveIndex(idx)
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [playing, writePlayhead, activeAt])

  const seek = useCallback(
    (t: number) => {
      const a = audioRef.current
      if (!a) return
      const clamped = Math.max(0, Math.min(t, Number.isFinite(duration) && duration > 0 ? duration : t))
      a.currentTime = clamped
      setTime(clamped)
      writePlayhead(clamped)
      const idx = activeAt(clamped)
      if (idx !== lastActiveRef.current) {
        lastActiveRef.current = idx
        setActiveIndex(idx)
      }
    },
    [duration, writePlayhead, activeAt],
  )

  const toggle = useCallback(() => {
    const a = audioRef.current
    if (!a) return
    if (a.paused) {
      void a.play()
    } else {
      a.pause()
    }
  }, [])

  // Establish the active word on payload load (and when the payload
  // changes): the current time is 0 on a fresh alignment.
  useEffect(() => {
    const idx = activeAt(time)
    lastActiveRef.current = idx
    setActiveIndex(idx)
  }, [result.aligned, activeAt])

  // Dev-mode tripwire: activeIndex is a position, but every word also
  // carries token.index (baked in by _build_payload, web/api.py:142). The
  // two spaces coincide only while indices are contiguous; the UI compares
  // positions so a divergence no longer mis-highlights — but it must still
  // be loud in dev, because any code comparing against w.index would
  // silently point at the wrong word. Observational (console.error), not a
  // crash: a non-contiguous payload is legal input and the highlight is
  // correct either way.
  useEffect(() => {
    if (!import.meta.env.DEV) return
    const bad = result.aligned.findIndex((w, i) => w.index !== i)
    if (bad !== -1) {
      console.error(
        'anchor-align invariant: aligned[' + bad + '].index=' + result.aligned[bad].index +
        ' != array position ' + bad + ' — token indices are not contiguous; the active-word ' +
        'highlight is position-based, but any code comparing against w.index will ' +
        'silently highlight the wrong word.',
      )
    }
  }, [result.aligned])

  return { audioRef, playheadRef, playing, time, duration, seek, toggle, activeIndex }
}
