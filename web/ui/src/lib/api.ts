export type MatchType = 'anchor' | 'exact' | 'phonetic' | 'fuzzy' | 'interpolated'

export interface AlignedWord {
  text: string
  index: number
  char_offset: number
  sentence_id: number
  is_sentence_end: boolean
  match_type: MatchType
  confidence: number
  start: number
  end: number
}

export interface Cue {
  index: number
  start: number
  end: number
  lines: string[]
}

export type Severity = 'error' | 'warning' | 'info'

export interface Issue {
  severity: Severity
  code: string
  message: string
  cue_index: number | null
}

export interface Stats {
  cues: number
  qc_errors: number
  qc_warnings: number
  interpolated_words: number
  mean_confidence: number | null
}

export interface AlignResult {
  audio_id: string
  audio_name: string
  transcript_name: string
  model: string
  phonetic: boolean
  elapsed_s: number
  audio_duration_s: number
  stats: Stats
  aligned: AlignedWord[]
  cues: Cue[]
  issues: Issue[]
  downloads: { vtt: string; srt: string; confidence: string }
}

export const MODEL_OPTIONS = ['tiny', 'base', 'small', 'medium'] as const
export type Model = (typeof MODEL_OPTIONS)[number]

export const AUDIO_ACCEPT = '.wav,.mp3,.m4a,.mp4,.flac,.ogg'
export const TRANSCRIPT_ACCEPT = '.txt,.docx'

async function toResult(res: Response): Promise<AlignResult> {
  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status})`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new Error(detail)
  }
  return (await res.json()) as AlignResult
}

export async function alignAudio(
  audio: File,
  transcript: File,
  model: Model,
  phonetic: boolean,
): Promise<AlignResult> {
  const fd = new FormData()
  fd.append('audio', audio)
  fd.append('transcript', transcript)
  fd.append('model', model)
  fd.append('phonetic', String(phonetic))
  const res = await fetch('/api/align', { method: 'POST', body: fd })
  return toResult(res)
}

export async function fetchSample(): Promise<AlignResult> {
  return toResult(await fetch('/api/sample'))
}

export function audioUrl(id: string): string {
  return `/api/audio/${id}`
}
