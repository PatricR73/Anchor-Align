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
  // byte sizes of the download artifacts; content is fetched on demand from
  // /api/download/{audio_id}/{fmt}
  downloads: { vtt: number; srt: number; confidence: number }
}

export const MODEL_OPTIONS = ['tiny', 'base', 'small', 'medium'] as const
export type Model = (typeof MODEL_OPTIONS)[number]

export const AUDIO_ACCEPT = '.wav,.mp3,.m4a,.mp4,.flac,.ogg'
export const TRANSCRIPT_ACCEPT = '.txt,.docx'

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

// Parse a non-2xx response body (structured detail or a bare string) into
// an ApiError carrying the machine-readable code.
function toApiError(status: number, text: string): ApiError {
  let code = 'REQUEST_FAILED'
  let message = `Request failed (HTTP ${status})`
  try {
    const body = JSON.parse(text) as { detail?: unknown }
    const detail = body?.detail
    if (typeof detail === 'string') {
      message = detail
    } else if (detail && typeof detail === 'object') {
      const d = detail as { code?: unknown; message?: unknown }
      if (typeof d.code === 'string') code = d.code
      if (typeof d.message === 'string') message = d.message
    }
  } catch {
    /* non-JSON error body — keep the generic message */
  }
  return new ApiError(status, code, message)
}

async function toResult(res: Response): Promise<AlignResult> {
  if (!res.ok) throw toApiError(res.status, await res.text())
  return (await res.json()) as AlignResult
}

export type UploadProgress = (sentBytes: number, totalBytes: number) => void

// Upload via XHR instead of fetch+FormData: fetch emits no upload-progress
// events, so a large file on a slow link would show only an indeterminate
// spinner. XHR's upload.onprogress reports true bytes sent; the UI can then
// distinguish "uploading 43%" from "processing".
export function alignAudio(
  audio: File,
  transcript: File,
  model: Model,
  phonetic: boolean,
  onProgress?: UploadProgress,
): Promise<AlignResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/align')
    xhr.responseType = 'text'
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded, e.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as AlignResult)
        } catch {
          reject(new ApiError(xhr.status, 'REQUEST_FAILED', 'Malformed server response'))
        }
      } else {
        reject(toApiError(xhr.status, xhr.responseText))
      }
    }
    xhr.onerror = () =>
      reject(new ApiError(0, 'REQUEST_FAILED', 'The upload could not reach the server. Check the connection and try again.'))
    const fd = new FormData()
    fd.append('audio', audio)
    fd.append('transcript', transcript)
    fd.append('model', model)
    fd.append('phonetic', String(phonetic))
    xhr.send(fd)
  })
}

export async function fetchSample(): Promise<AlignResult> {
  // Dev-only hook for the large synthetic fixture: the query param is only
  // read when import.meta.env.DEV, so production builds dead-code-eliminate
  // this branch and can never request the fixture (which the API also
  // refuses without ALLOW_FIXTURES=1).
  let url = '/api/sample'
  if (import.meta.env.DEV && new URLSearchParams(window.location.search).get('fixture') === 'large') {
    url = '/api/sample?fixture=large'
  }
  return toResult(await fetch(url))
}

export function audioUrl(id: string): string {
  return `/api/audio/${id}`
}
