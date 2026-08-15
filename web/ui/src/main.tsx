import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Latin-only variable fonts: the bare @fontsource-variable entry pulls every
// subset (cyrillic, greek, vietnamese, latin-ext...) — 14 woff2 files. The
// latin woff2 is imported directly and declared in index.css, so only the
// families that render above the fold (display + body — Header wordmark and
// IdleView hero) ship, and they are preloaded. JetBrains Mono is dropped:
// the system mono stack measures within 1-6% of it on timestamps (see
// tools/probe-mono.mjs) and saves ~84 KB.
import spaceGroteskLatinUrl from '@fontsource-variable/space-grotesk/files/space-grotesk-latin-wght-normal.woff2?url'
import interLatinUrl from '@fontsource-variable/inter/files/inter-latin-wght-normal.woff2?url'
import './index.css'
import App from './App'

// Preload only the families that render above the fold (verified against
// Header.tsx and IdleView.tsx): Space Grotesk (display) and Inter (body).
for (const href of [spaceGroteskLatinUrl, interLatinUrl]) {
  const link = document.createElement('link')
  link.rel = 'preload'
  link.as = 'font'
  link.type = 'font/woff2'
  link.crossOrigin = 'anonymous'
  link.href = href
  document.head.appendChild(link)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
