import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AlignResult } from '../lib/api'

export interface Playback {
  audioRef: React.RefObject<HTMLAudioElement | null>
  playing: boolean
  time: number
  duration: number
  seek: (t: number) => void
  toggle: () => void
  activeIndex: number
}

export function usePlayback(result: AlignResult): Playback {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
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

  // rAF loop keeps the playhead smooth while playing
  useEffect(() => {
    if (!playing) return
    let raf = 0
    const loop = () => {
      const a = audioRef.current
      if (a) setTime(a.currentTime)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [playing])

  const seek = useCallback(
    (t: number) => {
      const a = audioRef.current
      if (!a) return
      const clamped = Math.max(0, Math.min(t, Number.isFinite(duration) && duration > 0 ? duration : t))
      a.currentTime = clamped
      setTime(clamped)
    },
    [duration],
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

  // Edited order can contain transposed blocks, so timestamps are not
  // monotonic in this list — a linear scan is the honest, simple answer
  // (documents are a few hundred words; even 5k words at 60fps is fine).
  const activeIndex = useMemo(() => {
    const words = result.aligned
    for (let i = 0; i < words.length; i++) {
      if (time >= words[i].start && time < words[i].end) return i
    }
    return -1
  }, [time, result.aligned])

  return { audioRef, playing, time, duration, seek, toggle, activeIndex }
}
