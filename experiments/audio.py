#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Measure the audio front end and write RESULTS-audio.md.

    python experiments/audio.py

Every corpus piece is played by the reference synthesizer in several tone
colours, transcribed by every transcriber, and compared with the notes that
were played.  Then the whole chain - audio in, chip arrangement out - is
compared with the same arrangement made from the MIDI file.

Needs NumPy; the lossy-codec rows also need ffmpeg and are left out without it.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eigenchip import __version__, metrics                      # noqa: E402
from eigenchip.arrangers import arrange                         # noqa: E402
from eigenchip.audio import analysis, decode, evaluate, synth   # noqa: E402
from eigenchip.audio.transcribe import TRANSCRIBERS, Spectrum, find_drums, transcribe   # noqa: E402
from eigenchip.voices import consistency, flatten, separate    # noqa: E402
from eigenchip.ir import quantize                               # noqa: E402
from eigenchip.readers import read                              # noqa: E402
from eigenchip.readers.audio import score_from_samples          # noqa: E402

COLOURS = ["sine", "square", "pluck", "band"]
KEYS = ["precision", "recall", "f1", "f1_class", "frame_f1"]
HEAD = {"precision": "precision", "recall": "recall", "f1": "F1", "f1_class": "F1, octaves forgiven",
        "frame_f1": "frame F1"}
E2E = ["melody_recall", "bass_recall", "pitch_recall", "pitch_precision", "chroma", "onset_f1"]
E2E_HEAD = {"melody_recall": "melody", "bass_recall": "bass", "pitch_recall": "kept", "pitch_precision": "true",
            "chroma": "harmony", "onset_f1": "rhythm"}
CODECS = [("Ogg Vorbis, quality 2 (about 96 kbit/s)", ".ogg", ["-c:a", "libvorbis", "-q:a", "2"]),
          ("MP3, 64 kbit/s", ".mp3", ["-c:a", "libmp3lame", "-b:a", "64k"]),
          ("MP3, 32 kbit/s", ".mp3", ["-c:a", "libmp3lame", "-b:a", "32k"])]


def cell(v):
    return "-" if v is None else "%.2f" % v


def mean(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def melody_recall(score, truth, notes, tolerance=0.05):
    """Share of the true melody's notes that the transcription contains."""
    ch = (truth or {}).get("melody")
    if ch is None:
        return None
    spb = 60.0 / score.tempo
    want = [(n.start * spb, n.pitch) for n in score.notes if n.channel == ch and not n.drum]
    used, hits = set(), 0
    for onset, pitch in want:
        for i, (t0, _t1, p) in enumerate(notes):
            if i not in used and p == pitch and abs(t0 - onset) <= tolerance:
                used.add(i)
                hits += 1
                break
    return hits / float(len(want) or 1)


def run(log=None):
    say = log or (lambda *_a: None)
    corpus = os.path.join(ROOT, "corpus")
    with open(os.path.join(corpus, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    out = {"manifest": manifest, "notes": [], "drums": [], "tempo": [], "chain": [], "codecs": [],
           "kit": [], "voices": [], "deep": []}
    kinds = {35: "k", 36: "k", 37: "s", 38: "s", 39: "s", 40: "s"}
    ffmpeg = decode.ffmpeg_path()
    for entry in manifest:
        score = read(os.path.join(corpus, entry["file"]))
        truth = synth.truth(score)
        has_drums = any(n.drum for n in score.notes)
        # lines: take the channels away from the MIDI file and see whether they can be found again
        flat = flatten(score)
        apart = separate(flat)
        grid = quantize(score)
        row = {"piece": entry["title"], "consistency": consistency(score, apart)}
        for label, version in (("true", score), ("none", flat), ("found", apart)):
            res = metrics.evaluate(grid, arrange(quantize(version), "roles"), None, entry.get("truth"))
            row["melody_" + label] = res["melody_recall"]
        out["voices"].append(row)
        if entry["file"].startswith("deep_drone"):
            for colour in ("pad", "sine", "organ"):
                samples = synth.render(score, colour)
                for label, spec in (("deep window", Spectrum(samples)), ("without it", Spectrum(samples, deep=False))):
                    for name in ("nmf", "pads"):
                        notes = [n[:3] for n in transcribe(spec, name)]
                        res = evaluate.note_scores(truth, notes, tolerance=0.25)
                        low_true = {p for _a, _b, p in truth if p < 36}
                        low_found = {p for _a, _b, p in notes if p < 36}
                        res.update(colour=colour, method=name, window=label,
                                   low="%d of %d, %d wrong" % (len(low_true & low_found), len(low_true),
                                                               len(low_found - low_true)))
                        out["deep"].append(res)
        for colour in COLOURS:
            samples = synth.render(score, colour, drums=False)
            spec = Spectrum(samples)
            for name in TRANSCRIBERS:
                notes = [n[:3] for n in transcribe(spec, name)]
                res = evaluate.note_scores(truth, notes)
                res.update(piece=entry["file"], colour=colour, method=name,
                           melody=melody_recall(score, entry.get("truth"), notes))
                out["notes"].append(res)
            if colour == "band":
                bpm, phase, conf = analysis.estimate_tempo(spec.flux, spec.flux_fps)
                out["tempo"].append({"piece": entry["title"], "true": score.tempo, "estimated": bpm,
                                     "verdict": evaluate.tempo_verdict(bpm, score.tempo), "confidence": conf})
                # the whole chain: audio -> notes -> grid -> arrangement, judged against the original notes
                grid = quantize(score)
                ratio = {"double": 0.5, "half": 2.0}.get(out["tempo"][-1]["verdict"], 1.0)
                for name in TRANSCRIBERS:
                    for lines in (0, 5):
                        heard = score_from_samples(samples, transcriber=name, meter=score.meter, voices=lines,
                                                   tempo=bpm * ratio if ratio != 1.0 else None)
                        heard_grid = quantize(heard)
                        for arranger in ("skyline", "roles-arp"):
                            if lines and arranger == "skyline":
                                continue                        # skyline does not look at channels
                            res = metrics.evaluate(grid, arrange(heard_grid, arranger), None, entry.get("truth"))
                            res.update(piece=entry["file"], source=name + (", lines found" if lines else ""),
                                       arranger=arranger)
                            out["chain"].append(res)
                for arranger in ("skyline", "roles-arp"):
                    res = metrics.evaluate(grid, arrange(grid, arranger), None, entry.get("truth"))
                    res.update(piece=entry["file"], source="midi", arranger=arranger)
                    out["chain"].append(res)
                if has_drums:
                    spb = 60.0 / score.tempo
                    true_hits = [(n.start * spb, kinds.get(n.pitch, "h")) for n in score.notes if n.drum]
                    for kit_colour in ("band", "square", "pluck"):
                        heard = find_drums(Spectrum(synth.render(score, kit_colour, drums=True)))
                        res = evaluate.drum_scores(true_hits, heard)
                        res.update(piece=entry["title"], colour=kit_colour)
                        out["kit"].append(res)
                    with_drums = Spectrum(synth.render(score, "band", drums=True))
                    find_drums(with_drums)                      # tells the note cutter where the kicks are
                    for name in TRANSCRIBERS:
                        for label, sp in (("without drums", spec), ("with drums", with_drums)):
                            res = evaluate.note_scores(truth, [n[:3] for n in transcribe(sp, name)])
                            res.update(piece=entry["title"], method=name, setting=label)
                            out["drums"].append(res)
                if ffmpeg:
                    folder = tempfile.mkdtemp(prefix="eigenchip-")
                    wav = os.path.join(folder, "a.wav")
                    decode.write_wav(wav, samples)
                    for label, ext, flags in CODECS:
                        packed = os.path.join(folder, "a" + ext)
                        done = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", wav] + flags + [packed],
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        if done.returncode != 0:
                            continue
                        again, _rate, _info = decode.load(packed)
                        res = evaluate.note_scores(truth, [n[:3] for n in transcribe(again, "nmf")])
                        res.update(codec=label)
                        out["codecs"].append(res)
        say("  %s" % entry["file"])
    return out


def report(out):
    notes = out["notes"]
    lines = ["# Results: audio", "",
             "Generated by `python experiments/audio.py` with eigenchip %s. Do not edit by hand." % __version__, "",
             "The corpus is played by eigenchip's own reference synthesizer (`eigenchip/audio/synth.py`),",
             "so the notes that sound are known exactly. This is clean, dry, perfectly tuned audio:",
             "**an upper bound**, not a forecast for recordings. All scores run from 0 to 1.", "",
             "A transcribed note counts as right when it has the right pitch and starts within 50 ms",
             "of a true note (`eigenchip/audio/evaluate.py`).", "",
             "| column | question it answers |", "| --- | --- |",
             "| precision | How many of the notes it wrote down were really played? |",
             "| recall | How many of the notes played did it write down? |",
             "| F1 | Both at once. |",
             "| F1, octaves forgiven | The same, counting the right note in the wrong octave as right. |",
             "| frame F1 | Are the right pitches sounding at each moment (durations count, onsets do not)? |",
             "| melody | How many notes of the true melody are in the transcription? |", "",
             "## Transcribers, averaged over the corpus (no drums)", ""]
    for colour in COLOURS:
        lines += ["### Tone colour: %s" % colour, "",
                  "| transcriber | " + " | ".join(HEAD[k] for k in KEYS) + " | melody |",
                  "| --- |" + " ---: |" * (len(KEYS) + 1)]
        for name in TRANSCRIBERS:
            rows = [r for r in notes if r["colour"] == colour and r["method"] == name]
            lines.append("| %s | %s | %s |" % (name, " | ".join(cell(mean(rows, k)) for k in KEYS),
                                               cell(mean(rows, "melody"))))
        lines.append("")
    lines += ["`band` gives every channel its own tone colour. `mono` follows one line only, so its",
              "recall is low by design wherever more than one note sounds; `pads` keeps only what lasts,",
              "so it misses short notes by design.", "",
              "## Piece by piece (tone colour: band, F1)", "",
              "| piece | " + " | ".join(TRANSCRIBERS) + " |", "| --- |" + " ---: |" * len(TRANSCRIBERS)]
    for entry in out["manifest"]:
        row = []
        for name in TRANSCRIBERS:
            hit = [r for r in notes if r["piece"] == entry["file"] and r["colour"] == "band" and r["method"] == name]
            row.append(cell(hit[0]["f1"]) if hit else "-")
        lines.append("| %s | %s |" % (entry["title"], " | ".join(row)))
    lines += ["", "## Finding lines", "",
              "The channels of each MIDI file are thrown away and looked for again (`eigenchip/voices.py`).",
              "`together` is the share of notes that follow each other in a true line and are still in one",
              "line afterwards. The other columns are the melody found by the `roles` arranger: with the",
              "true channels, with none, and with the lines that were found.", "",
              "| piece | together | melody, true channels | melody, no channels | melody, lines found |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for r in out["voices"]:
        lines.append("| %s | %s | %s | %s | %s |" % (r["piece"], cell(r["consistency"]), cell(r["melody_true"]),
                                                     cell(r["melody_none"]), cell(r["melody_found"])))
    lines.append("| **average** | %s | %s | %s | %s |" % tuple(
        cell(mean(out["voices"], k)) for k in ("consistency", "melody_true", "melody_none", "melody_found")))
    lines += ["", "## Hearing drums", "",
              "Kick, snare and hi-hat found by `find_drums`, against the hits that were played",
              "(right kind, within 50 ms). The pitched parts play along in the tone colour named.", "",
              "| piece | tone colour | precision | recall | F1 |", "| --- | --- | ---: | ---: | ---: |"]
    for r in out["kit"]:
        lines.append("| %s | %s | %s | %s | %s |" % (r["piece"], r["colour"], cell(r["precision"]),
                                                     cell(r["recall"]), cell(r["f1"])))
    lines += ["", "## Sustained sound and deep tones", "",
              "`Deep drone` only: slow pads over a sub-bass down to 29 Hz. Onsets are soft, so a note",
              "counts when it starts within 250 ms. `low notes` are the three sub-bass pitches: how many",
              "were found, and how many wrong ones were reported beside them. The deep window is the",
              "second, 0.74 s analysis used below about 80 Hz.", "",
              "| tone colour | transcriber | analysis | F1 | frame F1 | low notes |",
              "| --- | --- | --- | ---: | ---: | --- |"]
    for r in out["deep"]:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (r["colour"], r["method"], r["window"], cell(r["f1"]),
                                                          cell(r["frame_f1"]), r["low"]))
    lines += ["", "## What drums do", "",
              "The two pieces with a drum track, with and without it: how much do the drums disturb",
              "the pitched notes?", "",
              "| piece | transcriber | setting | precision | recall | F1 |", "| --- | --- | --- | ---: | ---: | ---: |"]
    for r in out["drums"]:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (r["piece"], r["method"], r["setting"],
                                                         cell(r["precision"]), cell(r["recall"]), cell(r["f1"])))
    if out["codecs"]:
        lines += ["", "## Lossy formats", "",
                  "The `band` audio compressed, decoded again through ffmpeg, and transcribed with `nmf`.", "",
                  "| format | precision | recall | F1 |", "| --- | ---: | ---: | ---: |"]
        base = [r for r in notes if r["colour"] == "band" and r["method"] == "nmf"]
        lines.append("| WAV (uncompressed) | %s | %s | %s |" % tuple(cell(mean(base, k)) for k in ("precision", "recall", "f1")))
        for label, _ext, _flags in CODECS:
            rows = [r for r in out["codecs"] if r["codec"] == label]
            if rows:
                lines.append("| %s | %s | %s | %s |" % ((label,) + tuple(cell(mean(rows, k)) for k in ("precision", "recall", "f1"))))
    lines += ["", "## Tempo", "",
              "| piece | true bpm | estimated | verdict |", "| --- | ---: | ---: | --- |"]
    for r in out["tempo"]:
        lines.append("| %s | %.1f | %.1f | %s |" % (r["piece"], r["true"], r["estimated"], r["verdict"]))
    good = sum(1 for r in out["tempo"] if r["verdict"] == "ok")
    lines += ["", "%d of %d right. `double` and `half` are the same pulse counted at another level; "
              "no estimator is free of them." % (good, len(out["tempo"])), "",
              "## The whole chain: audio in, chip arrangement out", "",
              "The arrangement made from the audio (tone colour `band`, no drums, tempo estimated;",
              "a doubled or halved tempo is put right first) judged against the notes of the MIDI file,",
              "next to the same arranger working from the MIDI file itself. Columns as in `RESULTS.md`.",
              "`lines found` means the transcription was sorted into lines before arranging.", ""]
    for arranger in ("skyline", "roles-arp"):
        lines += ["### %s" % arranger, "",
                  "| source | " + " | ".join(E2E_HEAD[k] for k in E2E) + " |", "| --- |" + " ---: |" * len(E2E)]
        sources = ["midi"] + list(TRANSCRIBERS)
        if arranger != "skyline":
            sources += [t + ", lines found" for t in TRANSCRIBERS]
        for source in sources:
            rows = [r for r in out["chain"] if r["arranger"] == arranger and r["source"] == source]
            lines.append("| %s | %s |" % ("MIDI file" if source == "midi" else "audio, " + source,
                                          " | ".join(cell(mean(rows, k)) for k in E2E)))
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print("transcribing the corpus (a few minutes)...")
    result = run(print)
    with open(os.path.join(ROOT, "RESULTS-audio.md"), "w", encoding="utf-8") as f:
        f.write(report(result))
    print("wrote RESULTS-audio.md")
