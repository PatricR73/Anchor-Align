"""Generate a large synthetic alignment payload for scale-testing the UI.

Produces .cache/fixtures/large.json — a payload in the EXACT shape
_build_payload() in web/api.py returns (and web/ui/src/lib/api.ts types) —
plus .cache/fixtures/large.wav, a silent 40-minute 8kHz WAV so the player
has real audio metadata to seek against.

Seeded content (all reproducible from SEED):
  * 9,000 words spanning 2400 s (~40 min) of contiguous word timings
  * one isolated low-confidence word at ~38:00 amid high-confidence text
  * a 61-word run of match_type="interpolated" words
  * a transposed block (time indices 7000..7160) spliced to the END of
    edited order, so edited order is non-monotonic in time
  * cues segmented from the audio-order stream, one deliberately 8.2 s long
    so the QC pass emits a CUE_TOO_LONG warning; a TRANSPOSED_BLOCK info
    issue flags the moved block

Dev-only by construction: the JSON lives in .cache/ (gitignored, never in a
build artifact), and web/api.py only serves it when ALLOW_FIXTURES=1.
"""

from __future__ import annotations

import json
import random
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / ".cache" / "fixtures"

N_WORDS = 9000
DURATION_S = 2400.0  # 40 minutes
SEED = 20250815

MIN_WORD_S = 0.12
MAX_WORD_S = 0.45

WORD_POOL = (
    "the be of and a to in he have it that for they I with as not on she at by this we you do but "
    "from or which one would all will there say who make when can more if no man out other so what "
    "time up go about than into could state only new year some take come these know see use get "
    "like then first any work now may such give over think most even find day also after way many "
    "must look before great back through long where much should well people down own just because "
    "good each those feel seem how high too place little world very still nation hand old life "
    "tell write become here show house both between need mean call develop under last right move "
    "thing general school never same another begin while number part turn real leave might want "
    "point form off child few small since against ask late home interest large person end open "
    "public follow during present without again hold govern around possible head consider word "
    "program problem however lead system set order eye plan run keep face fact group play stand "
    "increase early course change help line city put close case force meet once water upon war "
    "build hear light unite live every country bring center let side try provide continue name "
    "certain power pay result question study woman member until far night always service away "
    "report something company week church toward start social room figure nature though young "
    "less enough almost read include president nothing yet better big boy cost business value "
    "second why clear expect family complete act sense mind experience art next near direct car "
    "law industry important girl god several matter usual rather per often kind among white "
    "reason action return foot care simple within love human along appear doctor believe speak "
    "active student month drive concern best door hope example inform body ever least probable "
    "understand reach effect different idea whole control condition field pass fall note special "
    "talk particular today measure walk teach low hour type carry rate remain full street easy "
    "although record sit determine level local sure receive thus moment spirit train college "
    "religion perhaps music grow free cause serve age book board recent sound office cut step "
    "class true history position above strong friend necessary add court deal tax support party "
    "whether either land material happen education death agree arm mother across quite anything "
    "town past view society manage answer break organize half fire lose money stop actual already "
    "effort wait department able political learn voice air early understand point call million "
    "available hour he already whom water hair bring hand go friend toward get water age system "
    "bill cost area number write special I night same water long then small over air still under "
    "job plan water place human fact home child run public head mother other sea heat home here "
    "open age land body work air during year man live line want need water head play full record "
    "air use call him second good so an two air"
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    # Short words only: 9000 words over 2400 s is ~23 cps with 5+ char
    # words (the caption cap is 21 chars/sec counting spaces). Capping the
    # pool at 5 chars keeps the density at ~19.9 cps so cues stay
    # constraint-clean outside the deliberate seeds.
    pool = [w for w in WORD_POOL.split() if len(w) <= 5]
    assert len(pool) >= 150, "word pool too small"

    # ---- 1) words in TIME order, contiguous timings ----
    # Word duration is proportional to (len + 1 space) and normalized to
    # exactly DURATION_S, so every cue lands at ~19.9 chars/sec — under the
    # 21 cps caption cap. A fixed 0.267s mean with 5-6 char words would
    # exceed the cap (23 cps) on every cue; length-proportional timing is
    # what keeps the fixture constraint-clean outside the deliberate seeds.
    time_words: list[dict] = []
    for i in range(N_WORDS):
        word = pool[rng.randrange(len(pool))]
        if i > 0 and rng.random() < 0.09:
            word += ","
        if rng.random() < 0.075:
            word += rng.choice([".", ".", "!", "?"])
        time_words.append({"text": word})
    total_units = sum(len(w["text"]) + 1 for w in time_words)
    unit_s = DURATION_S / total_units
    t = 0.0
    for w in time_words:
        w["start"] = t
        t += (len(w["text"]) + 1) * unit_s
        w["end"] = t
    time_words[-1]["end"] = DURATION_S

    # ---- 2) seeds ----
    for idx in range(5000, 5061):
        time_words[idx]["match_type"] = "interpolated"
        time_words[idx]["confidence"] = round(rng.uniform(0.40, 0.62), 4)
    low_idx = 8550
    for idx in range(N_WORDS):
        if "match_type" not in time_words[idx]:
            r = rng.random()
            time_words[idx]["match_type"] = "anchor" if r < 0.04 else ("fuzzy" if r < 0.06 else "exact")
            time_words[idx]["confidence"] = round(rng.uniform(0.86, 0.99), 4)
    time_words[low_idx]["confidence"] = 0.28
    time_words[low_idx]["match_type"] = "fuzzy"
    time_words[low_idx]["text"] = time_words[low_idx]["text"].rstrip(".,!?") + "."

    # ---- 3) edited order: A(0..6999) + C(7161..8999) + B(7000..7160) ----
    block_b = time_words[7000:7161]  # 161 words, ~43 s of audio, moved to doc end
    edited = time_words[:7000] + time_words[7161:] + block_b
    assert len(edited) == N_WORDS

    aligned: list[dict] = []
    char_offset = 0
    sentence_id = 0
    prev_end = False
    for pos, w in enumerate(edited):
        text = w["text"]
        if pos > 0 and prev_end:
            text = text[0].upper() + text[1:]
        prev_end = text.endswith((".", "!", "?"))
        aligned.append(
            {
                "text": text,
                "index": pos,
                "char_offset": char_offset,
                "sentence_id": sentence_id,
                "is_sentence_end": prev_end,
                "match_type": w["match_type"],
                "confidence": w["confidence"],
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
            }
        )
        char_offset += len(text) + 1
        if prev_end:
            sentence_id += 1

    # ---- 4) cues from the TIME-ordered stream ----
    def wrap_lines(ws: list[dict]) -> list[str]:
        words = [w["text"] for w in ws]
        total = sum(len(t) + 1 for t in words) - 1
        if total <= 42:
            return [" ".join(words)]
        if total <= 84:
            # best split into exactly 2 lines, both <= 42 chars
            best: tuple[int, list[str]] | None = None
            for k in range(1, len(words)):
                l1 = " ".join(words[:k])
                l2 = " ".join(words[k:])
                if len(l1) <= 42 and len(l2) <= 42:
                    score = max(len(l1), len(l2))
                    if best is None or score < best[0]:
                        best = (score, [l1, l2])
            if best is not None:
                return best[1]
        lines: list[str] = []
        line: list[str] = []
        for t in words:
            cand = " ".join(line + [t])
            if len(cand) > 42 and line:
                lines.append(" ".join(line))
                line = [t]
            else:
                line.append(t)
        if line:
            lines.append(" ".join(line))
        return lines

    cues: list[dict] = []
    long_done = False
    i = 0
    while i < N_WORDS:
        cur = [time_words[i]]
        cue_start_i = i
        i += 1
        start = cur[0]["start"]
        while i < N_WORDS:
            w = time_words[i]
            cur_total = sum(len(x["text"]) + 1 for x in cur) - 1  # chars of cur, joined
            cur_dur = cur[-1]["end"] - start
            long_target = not long_done and 595.0 <= start <= 610.0
            if long_target:
                cur.append(w)
                i += 1
                if w["end"] - start >= 8.2:
                    long_done = True
                continue
            # honor the caption constraints: 2 lines x 42 chars, 1-7 s
            # (cps is bounded by the length-proportional timings above)
            if (cur_dur >= 4.5 or cur_total > 84 or len(cur) >= 13) and cur_dur >= 1.0:
                break
            cur.append(w)
            i += 1
        end = cur[-1]["end"]
        cues.append(
            {
                "index": len(cues) + 1,
                "start": round(start, 3),
                "end": round(end, 3),
                "lines": wrap_lines(cur),
                "word_span": (cue_start_i, i),
            }
        )

    # ---- 5) mini QC pass mirroring export.qc.qc_report ----
    issues: list[dict] = []
    prev_end: float | None = None
    for c in cues:
        dur = c["end"] - c["start"]
        if len(c["lines"]) > 2:
            issues.append({"severity": "error", "code": "TOO_MANY_LINES", "message": str(len(c["lines"])) + " lines (max 2)", "cue_index": c["index"]})
        for line in c["lines"]:
            if len(line) > 42:
                issues.append({"severity": "warning", "code": "LINE_TOO_LONG", "message": "line is " + str(len(line)) + " chars (max 42)", "cue_index": c["index"]})
        if dur < 1.0:
            issues.append({"severity": "warning", "code": "CUE_TOO_SHORT", "message": "duration " + format(dur, ".3f") + "s < minimum 1s", "cue_index": c["index"]})
        if dur > 7.0:
            issues.append({"severity": "warning", "code": "CUE_TOO_LONG", "message": "duration " + format(dur, ".3f") + "s > maximum 7s", "cue_index": c["index"]})
        cps = sum(len(line) for line in c["lines"]) / dur if dur > 0 else float("inf")
        if cps > 21:
            issues.append({"severity": "warning", "code": "CPS_EXCEEDED", "message": format(cps, ".1f") + " chars/sec (max 21)", "cue_index": c["index"]})
        if prev_end is not None and c["start"] < prev_end:
            issues.append({"severity": "error", "code": "OVERLAP", "message": "starts at " + str(c["start"]) + "s, before previous cue ends at " + str(prev_end) + "s", "cue_index": c["index"]})
        prev_end = c["end"]
    issues.append(
        {
            "severity": "info",
            "code": "TRANSPOSED_BLOCK",
            "message": "block edited later in the document (words 7000-7160) emitted in audio order",
            "cue_index": None,
        }
    )

    # ---- 6) downloads ----
    def ts(seconds: float, sep: str) -> str:
        total_ms = round(seconds * 1000)
        h, rem = divmod(total_ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"

    vtt_lines = ["WEBVTT", ""]
    srt_blocks: list[str] = []
    conf_report: list[dict] = []
    for c in cues:
        vtt_lines.append(str(c["index"]))
        vtt_lines.append(ts(c["start"], ".") + " --> " + ts(c["end"], "."))
        vtt_lines.extend(c["lines"])
        vtt_lines.append("")
        srt_blocks.append(
            "\n".join([str(c["index"]), ts(c["start"], ",") + " --> " + ts(c["end"], ","), *c["lines"]])
        )
        span = c["word_span"]
        confs = [w["confidence"] for w in time_words[span[0] : span[1]]]
        conf_report.append(
            {
                "cue_index": c["index"],
                "start": c["start"],
                "end": c["end"],
                "mean_confidence": round(sum(confs) / len(confs), 4) if confs else None,
                "min_confidence": min(confs) if confs else None,
                "word_count": len(confs),
            }
        )

    all_confs = [w["confidence"] for w in time_words]
    vtt_content = "\n".join(vtt_lines)
    srt_content = "\n\n".join(srt_blocks) + "\n"
    conf_content = json.dumps(conf_report, indent=2)
    payload = {
        "audio_id": "",  # filled by the API when it registers the wav
        "audio_name": "fixture_large.wav",
        "transcript_name": "fixture_large.txt",
        "model": "base",
        "phonetic": False,
        "elapsed_s": 0.0,
        "audio_duration_s": DURATION_S,
        "stats": {
            "cues": len(cues),
            "qc_errors": sum(1 for x in issues if x["severity"] == "error"),
            "qc_warnings": sum(1 for x in issues if x["severity"] == "warning"),
            "interpolated_words": sum(1 for w in time_words if w["match_type"] == "interpolated"),
            "mean_confidence": round(sum(all_confs) / len(all_confs), 4),
        },
        "aligned": aligned,
        "cues": [{"index": c["index"], "start": c["start"], "end": c["end"], "lines": c["lines"]} for c in cues],
        "issues": issues,
        "downloads": {
            "vtt": len(vtt_content),
            "srt": len(srt_content),
            "confidence": len(conf_content),
        },
        "download_content": {
            "vtt": vtt_content,
            "srt": srt_content,
            "confidence": conf_content,
        },
    }

    (OUT / "large.json").write_text(json.dumps(payload), encoding="utf-8")

    wav_path = OUT / "large.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(1)
        wf.setframerate(8000)
        wf.writeframes(b"\x80" * int(DURATION_S * 8000))

    n_interp = sum(1 for w in time_words if w["match_type"] == "interpolated")
    low = aligned[8550]
    print("words=" + str(len(aligned)) + " cues=" + str(len(cues)) + " duration=" + str(int(DURATION_S)) + "s")
    print("interpolated_run=" + str(n_interp) + " low_conf_word_idx=" + str(low["index"]) + " conf=" + str(low["confidence"]) + " at t=" + format(low["start"], ".1f") + "s")
    print("edited order non-monotonic: " + format(aligned[6999]["end"], ".1f") + "s -> " + format(aligned[7000]["start"], ".1f") + "s -> " + format(aligned[8838]["end"], ".1f") + "s -> " + format(aligned[8839]["start"], ".1f") + "s")
    print("issues: " + str(len(issues)) + " (errors=" + str(payload["stats"]["qc_errors"]) + ", warnings=" + str(payload["stats"]["qc_warnings"]) + ")")
    print("json=" + format((OUT / "large.json").stat().st_size / 1e6, ".2f") + "MB wav=" + format(wav_path.stat().st_size / 1e6, ".1f") + "MB")


if __name__ == "__main__":
    main()
