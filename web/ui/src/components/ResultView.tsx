import { useState } from 'react'
import { motion } from 'motion/react'
import { ArrowLeft, FileText } from 'lucide-react'
import type { AlignResult } from '../lib/api'
import { stem } from '../lib/format'
import { usePlayback } from '../hooks/usePlayback'
import { MetricCards, type Metric } from './MetricCards'
import { Player } from './Player'
import { Tabs, TabPanel } from './Tabs'
import { TranscriptHeatmap } from './TranscriptHeatmap'
import { CuesTable } from './CuesTable'
import { QcTable } from './QcTable'
import { DownloadPanel } from './DownloadPanel'

export function ResultView({ result, onReset }: { result: AlignResult; onReset: () => void }) {
  const [tab, setTab] = useState('transcript')
  const playback = usePlayback(result)
  const s = result.stats

  const metrics: Metric[] = [
    { label: 'Cues', value: s.cues, tone: 'neutral' },
    { label: 'QC errors', value: s.qc_errors, tone: s.qc_errors > 0 ? 'error' : 'ok', hint: s.qc_errors === 0 ? 'all clear' : 'review needed' },
    { label: 'QC warnings', value: s.qc_warnings, tone: s.qc_warnings > 0 ? 'warning' : 'ok', hint: s.qc_warnings === 0 ? 'all clear' : 'review suggested' },
    { label: 'Interpolated', value: s.interpolated_words, tone: s.interpolated_words > 0 ? 'warning' : 'ok', hint: s.interpolated_words === 0 ? 'every word timed' : 'no direct STT evidence' },
  ]

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: 'easeOut' }}>
      <div className="flex flex-wrap items-end justify-between gap-4 pb-6 pt-8">
        <div className="min-w-0">
          <h2 className="truncate font-display text-[24px] font-semibold leading-tight tracking-tight sm:text-[28px]">
            {stem(result.audio_name)}
          </h2>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-muted">
            <span className="inline-flex items-center gap-1.5">
              <FileText className="h-3.5 w-3.5 text-faint" aria-hidden="true" /> {result.transcript_name}
            </span>
            <span className="text-faint" aria-hidden="true">·</span>
            <span className="font-mono">{result.model}</span>
            {result.phonetic && <span className="font-mono text-accent">phonetic</span>}
            <span className="text-faint" aria-hidden="true">·</span>
            <span className="font-mono">{result.elapsed_s.toFixed(1)}s pipeline</span>
          </p>
        </div>
        <button
          type="button"
          onClick={onReset}
          className="inline-flex items-center gap-1.5 rounded-md border border-hairline bg-surface-2 px-3 py-2 text-[12.5px] font-medium text-muted transition-colors duration-150 hover:border-accent/40 hover:text-accent"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" /> New alignment
        </button>
      </div>

      <MetricCards metrics={metrics} />

      <div className="mt-3">
        <Player result={result} playback={playback} />
      </div>

      <div className="mt-8">
        <Tabs
          tabs={[
            { id: 'transcript', label: 'Transcript' },
            { id: 'cues', label: 'Cues', badge: s.cues },
            { id: 'qc', label: 'QC report', badge: s.qc_errors + s.qc_warnings },
            { id: 'download', label: 'Download' },
          ]}
          active={tab}
          onChange={setTab}
        />
        {tab === 'transcript' && (
          <TabPanel id="transcript">
            <TranscriptHeatmap
              words={result.aligned}
              activeIndex={playback.activeIndex}
              interpolatedCount={s.interpolated_words}
              onSeek={playback.seek}
            />
          </TabPanel>
        )}
        {tab === 'cues' && (
          <TabPanel id="cues">
            <CuesTable cues={result.cues} onSeek={playback.seek} />
          </TabPanel>
        )}
        {tab === 'qc' && (
          <TabPanel id="qc">
            <QcTable issues={result.issues} />
          </TabPanel>
        )}
        {tab === 'download' && (
          <TabPanel id="download">
            <DownloadPanel result={result} />
          </TabPanel>
        )}
      </div>
    </motion.div>
  )
}
