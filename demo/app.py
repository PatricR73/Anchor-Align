"""S9 — Streamlit demo: upload audio + a human-edited transcript, run the
full pipeline (align -> resolve audio order -> segment into cues -> QC),
and show the result — a confidence heatmap over the transcript, an audio
player that jumps to a word's real timing on click, the QC findings, and
VTT/SRT/confidence-JSON downloads.

This is a thin wiring layer, not new alignment logic: every call below is
into the pipeline stages exactly as their own tests exercise them.
"""

from __future__ import annotations

import html
import tempfile
from pathlib import Path

import streamlit as st

from anchor_align.export.qc import write_confidence_json
from anchor_align.export.srt import write_srt
from anchor_align.export.vtt import write_vtt
from anchor_align.ingest.document import parse_transcript
from anchor_align.models import AlignedWord, MatchType, QCIssue, STTOptions
from anchor_align.pipeline import PipelineResult, align_to_cues
from anchor_align.stt.cache import cached_transcribe
from anchor_align.stt.faster_whisper_adapter import FasterWhisperAdapter

st.set_page_config(page_title="anchor-align", layout="wide")

_CONFIDENCE_LOW = (214, 69, 65)  # red
_CONFIDENCE_HIGH = (56, 158, 89)  # green

_SEVERITY_COLOR = {"error": "#e5484d", "warning": "#f5a623", "info": "#5b9dd9"}
_SEVERITY_ICON = {"error": "\u25cf", "warning": "\u25cf", "info": "\u25cf"}

_CSS = """
<style>
.block-container { padding-top: 2.25rem; padding-bottom: 3rem; max-width: 1180px; }

/* header */
.app-subtitle { color: rgba(250,250,250,0.6); font-size: 1rem; margin-top: -0.5rem; margin-bottom: 1.5rem; }

/* metric cards */
.metric-row { display: flex; gap: 0.9rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
.metric-card {
    flex: 1 1 160px;
    background: linear-gradient(160deg, rgba(255,255,255,0.045), rgba(255,255,255,0.01));
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 14px;
    padding: 1rem 1.25rem;
}
.metric-card .mc-label {
    font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em;
    color: rgba(250,250,250,0.5); margin-bottom: 0.4rem;
}
.metric-card .mc-value { font-size: 2rem; font-weight: 700; line-height: 1; }
.metric-card.neutral .mc-value { color: #fafafa; }
.metric-card.error .mc-value { color: #e5484d; }
.metric-card.warning .mc-value { color: #f5a623; }
.metric-card.ok .mc-value { color: #3ecf8e; }

/* tabs */
.stTabs [data-baseweb="tab-list"] { gap: 0.35rem; border-bottom: 1px solid rgba(255,255,255,0.08); }
.stTabs [data-baseweb="tab"] {
    padding: 0.55rem 1.1rem; border-radius: 10px 10px 0 0; font-weight: 500;
}
.stTabs [aria-selected="true"] { background: rgba(62,207,142,0.12); }

/* transcript / heatmap card */
.transcript-card {
    background: rgba(255,255,255,0.035);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 14px;
    padding: 1.4rem 1.6rem;
    line-height: 2.35;
    font-size: 1.08rem;
}
.legend { display: flex; align-items: center; gap: 1.2rem; margin-top: 0.9rem; font-size: 0.85rem; color: rgba(250,250,250,0.6); flex-wrap: wrap; }
.legend .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 0.35rem; vertical-align: middle; }

/* seek buttons */
.stButton button {
    border-radius: 8px !important;
    transition: transform 0.08s ease, border-color 0.12s ease, background 0.12s ease;
}
.stButton button:hover { border-color: #3ecf8e !important; color: #3ecf8e !important; transform: translateY(-1px); }
.stButton button p { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* QC table */
.qc-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.qc-table th {
    text-align: left; padding: 0.55rem 0.8rem; color: rgba(250,250,250,0.55);
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
    border-bottom: 1px solid rgba(255,255,255,0.12);
}
.qc-table td { padding: 0.6rem 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.06); vertical-align: top; }
.qc-table tr:hover td { background: rgba(255,255,255,0.03); }
.qc-badge {
    display: inline-flex; align-items: center; gap: 0.35rem; font-weight: 600; font-size: 0.8rem;
    padding: 0.15rem 0.55rem; border-radius: 999px; white-space: nowrap;
}
.qc-code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.82rem; color: rgba(250,250,250,0.75); }

/* sidebar */
section[data-testid="stSidebar"] .stButton button { width: 100%; }
</style>
"""


def _confidence_color(confidence: float) -> str:
    t = max(0.0, min(1.0, confidence))
    r = round(_CONFIDENCE_LOW[0] + (_CONFIDENCE_HIGH[0] - _CONFIDENCE_LOW[0]) * t)
    g = round(_CONFIDENCE_LOW[1] + (_CONFIDENCE_HIGH[1] - _CONFIDENCE_LOW[1]) * t)
    b = round(_CONFIDENCE_LOW[2] + (_CONFIDENCE_HIGH[2] - _CONFIDENCE_LOW[2]) * t)
    return f"rgb({r},{g},{b})"


def _render_heatmap(words_in_edited_order: list[AlignedWord]) -> None:
    spans = []
    for w in words_in_edited_order:
        color = _confidence_color(w.confidence)
        style = f"color:{color}; font-weight:600;"
        if w.match_type == MatchType.INTERPOLATED:
            # no real STT evidence for this word's timing at all — flagged
            # distinctly from "matched but low-confidence", a different
            # and more serious kind of uncertainty
            style += " text-decoration: underline dashed; text-decoration-color: #999;"
        title = f"{w.match_type.value}, confidence {w.confidence:.2f}, t={w.start:.2f}s"
        spans.append(
            f'<span style="{style}" title="{html.escape(title)}">{html.escape(w.token.text)}</span>'
        )
    st.markdown(
        '<div class="transcript-card">' + " ".join(spans) + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="legend">'
        f'<span><span class="swatch" style="background:{_confidence_color(0.0)};"></span>low confidence</span>'
        f'<span><span class="swatch" style="background:{_confidence_color(1.0)};"></span>high confidence</span>'
        '<span>dashed underline = interpolated (no direct STT evidence for that word)</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def _render_seek_grid(words_in_edited_order: list[AlignedWord]) -> None:
    st.caption("Click a word to jump the player to its aligned timestamp.")
    per_row = 6
    for row_start in range(0, len(words_in_edited_order), per_row):
        row = words_in_edited_order[row_start : row_start + per_row]
        cols = st.columns(per_row)
        for col, w in zip(cols, row):
            label = w.token.text if len(w.token.text) <= 12 else w.token.text[:11] + "..."
            if col.button(label, key=f"seek-{w.token.index}"):
                st.session_state["seek_time"] = w.start


def _render_qc_table(issues: list[QCIssue]) -> None:
    rows = []
    for i in issues:
        color = _SEVERITY_COLOR[i.severity]
        icon = _SEVERITY_ICON[i.severity]
        cue = i.cue_index if i.cue_index is not None else "-"
        rows.append(
            "<tr>"
            f'<td><span class="qc-badge" style="background:{color}22; color:{color};">'
            f"{icon} {html.escape(i.severity)}</span></td>"
            f'<td><span class="qc-code">{html.escape(i.code.value)}</span></td>'
            f"<td>{html.escape(str(cue))}</td>"
            f"<td>{html.escape(i.message)}</td>"
            "</tr>"
        )
    table = (
        '<table class="qc-table"><thead><tr>'
        "<th>Severity</th><th>Code</th><th>Cue</th><th>Message</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )
    st.markdown(table, unsafe_allow_html=True)


def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

    st.title("anchor-align")
    st.markdown(
        '<div class="app-subtitle">Aligns a human-edited transcript to raw STT word timing, then '
        "segments the result into caption cues — upload audio and the edited transcript to see it "
        "end to end.</div>",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Inputs")
        audio_file = st.file_uploader("Audio", type=["wav", "mp3", "m4a", "mp4", "flac", "ogg"])
        transcript_file = st.file_uploader("Edited transcript", type=["docx", "txt"])
        model_size = st.selectbox("faster-whisper model", ["tiny", "base", "small", "medium"], index=1)
        run = st.button("Align", type="primary", disabled=not (audio_file and transcript_file))

    if run and audio_file is not None and transcript_file is not None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            audio_path = tmp_dir / audio_file.name
            audio_path.write_bytes(audio_file.getvalue())
            transcript_path = tmp_dir / transcript_file.name
            transcript_path.write_bytes(transcript_file.getvalue())

            with st.spinner(f"Transcribing with faster-whisper ({model_size})..."):
                try:
                    adapter = FasterWhisperAdapter(model_size=model_size)
                    transcription = cached_transcribe(
                        audio_path, f"faster-whisper-{model_size}", adapter, STTOptions()
                    )
                    edited_tokens = parse_transcript(transcript_path)
                    result = align_to_cues(transcription.words, edited_tokens)
                except Exception as e:  # noqa: BLE001 - surfaced to the user, not swallowed
                    st.error(f"Pipeline failed: {e}")
                    return

            # audio bytes must outlive the tempdir for st.audio to replay
            # on later reruns (e.g. a word-click), so stash them in session
            # state rather than re-reading a path that's about to be deleted
            st.session_state["audio_bytes"] = audio_file.getvalue()
            st.session_state["audio_name"] = audio_file.name
            st.session_state["result"] = result
            st.session_state["seek_time"] = 0.0

            out_dir = tmp_dir / "out"
            out_dir.mkdir()
            vtt_path = write_vtt(result.cues, out_dir / "captions.vtt")
            srt_path = write_srt(result.cues, out_dir / "captions.srt")
            confidence_path = write_confidence_json(
                result.cues, result.audio_order, out_dir / "confidence.json"
            )
            st.session_state["vtt_bytes"] = vtt_path.read_bytes()
            st.session_state["srt_bytes"] = srt_path.read_bytes()
            st.session_state["confidence_bytes"] = confidence_path.read_bytes()

    if "result" not in st.session_state:
        st.info("Upload audio and an edited transcript, then click Align.")
        return

    result: PipelineResult = st.session_state["result"]
    cues = result.cues
    issues = result.issues

    st.audio(st.session_state["audio_bytes"], start_time=st.session_state.get("seek_time", 0.0))

    n_errors = result.error_count
    n_warnings = result.warning_count
    n_interpolated = sum(1 for w in result.aligned if w.match_type == MatchType.INTERPOLATED)

    def _card(kind: str, label: str, value: int) -> str:
        return (
            f'<div class="metric-card {kind}"><div class="mc-label">{html.escape(label)}</div>'
            f'<div class="mc-value">{value}</div></div>'
        )

    st.markdown(
        '<div class="metric-row">'
        + _card("neutral", "Cues", len(cues))
        + _card("error" if n_errors else "ok", "QC errors", n_errors)
        + _card("warning" if n_warnings else "ok", "QC warnings", n_warnings)
        + _card("neutral", "Interpolated words", n_interpolated)
        + "</div>",
        unsafe_allow_html=True,
    )

    heatmap_tab, cues_tab, qc_tab, download_tab = st.tabs(
        ["Transcript", "Cues", "QC report", "Download"]
    )

    with heatmap_tab:
        edited_order = sorted(result.aligned, key=lambda w: w.token.index)
        _render_heatmap(edited_order)
        st.divider()
        _render_seek_grid(edited_order)

    with cues_tab:
        st.dataframe(
            [
                {
                    "index": c.index,
                    "start": round(c.start, 3),
                    "end": round(c.end, 3),
                    "text": " / ".join(c.lines),
                }
                for c in cues
            ],
            use_container_width=True,
            hide_index=True,
        )

    with qc_tab:
        if issues:
            _render_qc_table(issues)
        else:
            st.success("No QC issues.")

    with download_tab:
        dl1, dl2, dl3 = st.columns(3)
        dl1.download_button(
            "VTT", st.session_state["vtt_bytes"], file_name="captions.vtt", use_container_width=True
        )
        dl2.download_button(
            "SRT", st.session_state["srt_bytes"], file_name="captions.srt", use_container_width=True
        )
        dl3.download_button(
            "Confidence JSON",
            st.session_state["confidence_bytes"],
            file_name="confidence.json",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
