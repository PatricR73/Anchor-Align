// Confidence ramp: red -> amber -> phosphor across [0, 1].
// The endpoints double as the app's semantic colors so the heatmap
// reads as part of the system, not a palette of its own.
const STOPS: { t: number; c: [number, number, number] }[] = [
  { t: 0, c: [255, 92, 92] }, //  --color-error
  { t: 0.5, c: [255, 178, 36] }, // --color-warning
  { t: 1, c: [46, 230, 168] }, // --color-accent
]

export function confidenceColor(conf: number): string {
  const t = Math.max(0, Math.min(1, conf))
  for (let i = 1; i < STOPS.length; i++) {
    const a = STOPS[i - 1]
    const b = STOPS[i]
    if (t <= b.t) {
      const f = (t - a.t) / (b.t - a.t || 1)
      const r = Math.round(a.c[0] + (b.c[0] - a.c[0]) * f)
      const g = Math.round(a.c[1] + (b.c[1] - a.c[1]) * f)
      const bl = Math.round(a.c[2] + (b.c[2] - a.c[2]) * f)
      return `rgb(${r} ${g} ${bl})`
    }
  }
  return 'rgb(46 230 168)'
}
