/** Player clock: 0:04.2 */
export function fmtClock(s: number): string {
  if (!Number.isFinite(s) || s < 0) s = 0
  const totalTenths = Math.floor(s * 10)
  const m = Math.floor(totalTenths / 600)
  const sec = Math.floor((totalTenths % 600) / 10)
  const t = totalTenths % 10
  return `${m}:${sec.toString().padStart(2, '0')}.${t}`
}

/** Caption timestamp: 00:01.240 (no hours until the cue crosses an hour) */
export function fmtStamp(s: number): string {
  if (!Number.isFinite(s) || s < 0) s = 0
  const totalMs = Math.round(s * 1000)
  const h = Math.floor(totalMs / 3_600_000)
  const m = Math.floor((totalMs % 3_600_000) / 60_000)
  const sec = Math.floor((totalMs % 60_000) / 1000)
  const ms = totalMs % 1000
  const mm = h > 0 ? m.toString().padStart(2, '0') : m.toString().padStart(2, '0')
  const body = `${mm}:${sec.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`
  return h > 0 ? `${h.toString().padStart(2, '0')}:${body}` : body
}

export function fmtPct(c: number): string {
  return `${Math.round(c * 100)}%`
}

export function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function stem(name: string): string {
  const i = name.lastIndexOf('.')
  return i > 0 ? name.slice(0, i) : name
}
