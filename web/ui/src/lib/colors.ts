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

// ---- Redundant, color-independent confidence channel -----------------------
// The color ramp sits on the red-green confusion axis: simulated under
// deuteranopia the mid-amber and high-green bands collapse in luminance
// (#e0c82b vs #ccc5ac, dL 0.016) and under protanopia the red/green hue
// distinction vanishes entirely — so "look at the red parts" fails for a
// large share of users, and pure grayscale loses the hue outright.
// Every confidence visual therefore ALSO encodes SOLIDITY: lower confidence
// is rendered less solid — thinner in the heatmap (font weight), shorter in
// the timeline (segment height). Both components derive from these functions,
// one shared source of truth, so the channels can never drift. The mapping is
// monotonic (more solid = more confident), which implies no false ordering.
export function confidenceSolidity(conf: number): number {
  return Math.max(0, Math.min(1, conf))
}

/** heatmap: 400 (thin, low confidence) .. 650 (solid, high confidence) */
export function confidenceFontWeight(conf: number): number {
  return 400 + Math.round(confidenceSolidity(conf) * 250)
}

/** timeline: 25% (short stub, low confidence) .. 100% (full bar, high) */
export function confidenceHeight(conf: number): number {
  return 0.25 + confidenceSolidity(conf) * 0.75
}
