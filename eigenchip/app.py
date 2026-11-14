# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""A small, stateful front door to the whole pipeline.

The web page (``web/``) drives eigenchip through this module, one call per
thing a person can do there: open a file, choose how to arrange it, ask for
the sound.  Everything that comes back is plain data - dicts, lists, numbers,
bytes - so it crosses into JavaScript, JSON or a notebook without ceremony.

    from eigenchip.app import Session
    s = Session()
    s.open_midi(open("song.mid", "rb").read(), "song")
    view = s.arrange("roles-arp")          # notes, voices, scores, the CLIo song
    wav = s.chip_wav(clio_synth_module)    # needs CLIo's synthesizer

Opening a MIDI file needs nothing but the standard library.  Opening audio,
and playing a MIDI file with the reference synthesizer, need NumPy.
"""
from __future__ import annotations

import json
import os
import tempfile

from . import __version__, metrics
from .arrangers import ARRANGERS, DEFAULT, arrange
from .ir import pitch_name, quantize
from .midi import read_midi, write_midi
from .writers import clio

SCORE_KEYS = ["melody_recall", "bass_recall", "pitch_recall", "pitch_precision", "chroma", "onset_f1"]


def _plain(value):
    """Make reader notes safe for JSON."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _temp(suffix):
    handle, path = tempfile.mkstemp(suffix=suffix)
    os.close(handle)
    return path


class Session:
    """One piece of music being worked on."""

    def __init__(self):
        self.score = None
        self.truth = {}             # channels of the melody and bass, when known
        self.reference = None       # the notes that were really played, when known (seconds)
        self.samples = None         # the audio that was opened or rendered, mono at 22050 Hz
        self.played = None          # the Score that was played, when the audio came from one
        self.kind = None            # "midi" or "audio"
        self.song = None
        self.grid = None

    # ------------------------------------------------------------------ #
    # opening
    # ------------------------------------------------------------------ #
    def open_midi(self, data, title="", truth=None):
        """Open a Standard MIDI File given as bytes."""
        path = _temp(".mid")
        try:
            with open(path, "wb") as f:
                f.write(bytes(data))
            score = read_midi(path)
        finally:
            os.remove(path)
        if title and not score.title:
            score.title = title
        self.score, self.truth, self.kind = score, dict(truth or {}), "midi"
        self.reference = self.samples = self.song = self.grid = self.played = None
        return self.facts()

    def open_audio(self, samples, rate=22050, title="", transcriber=None, tempo=None, offset=None,
                   meter=(4, 4), steps_per_beat=4, drums=True, voices=5, progress=None,
                   quality="standard", clean="light", effects=True):
        """Open sound: mono float samples. They are transcribed into notes.

        ``progress(fraction, text)`` is called as the work goes on.  ``quality``
        (fast, standard, fine), ``clean`` (off, light, strict) and ``effects``
        are passed to the reader.
        """
        from .audio import need_numpy
        from .audio.transcribe import DEFAULT as T_DEFAULT
        from .readers.audio import score_from_samples
        np = need_numpy()
        samples = np.ascontiguousarray(np.asarray(samples, dtype=np.float32).ravel())
        if not len(samples):
            raise ValueError("There is no sound in that file.")
        self.samples = samples
        self.score = score_from_samples(samples, int(rate), transcriber or T_DEFAULT, tempo, offset,
                                        tuple(meter), int(steps_per_beat), {"seconds": len(samples) / float(rate)},
                                        title, bool(drums), int(voices or 0), progress,
                                        quality or "standard", clean or "light", bool(effects))
        self.kind, self.truth, self.reference, self.played = "audio", {}, None, None
        self.song = self.grid = None
        return self.facts()

    def open_midi_as_audio(self, data, title="", colour="band", drums=True, truth=None, **options):
        """Play a MIDI file with the reference synthesizer, then open that sound.

        The notes of the file are kept as the right answer, so the transcription
        can be scored: this is how the page shows what the ear gets wrong.
        """
        from .audio import evaluate, synth
        self.open_midi(data, title)
        played = self.score
        if options.get("progress"):
            options["progress"](0.01, "Playing it on the test synthesizer")
        samples = synth.render(played, colour, drums=bool(drums))
        if "tempo" not in options or options.get("tempo") is None:
            options.pop("tempo", None)
        options["meter"] = played.meter           # an example knows its own meter; the ear would not
        facts = self.open_audio(samples, title=played.title or title, **options)
        self.reference = synth.truth(played)
        self.played, self.truth = played, dict(truth or {})
        heard = self.heard_seconds()
        scores = evaluate.note_scores(self.reference, heard)
        beat = 60.0 / played.tempo
        kinds = {35: "k", 36: "k", 37: "s", 38: "s", 39: "s", 40: "s"}
        true_drums = [(n.start * beat, kinds.get(n.pitch, "h")) for n in played.notes if n.drum]
        if true_drums and drums:
            shift = float(self.score.info.get("offset", 0.0) or 0.0)
            heard_drums = [(n.start * 60.0 / self.score.tempo + shift, kinds.get(n.pitch, "h"))
                           for n in self.score.notes if n.drum]
            d = evaluate.drum_scores(true_drums, heard_drums)
            facts["drums"] = {k: (round(d[k], 3) if isinstance(d[k], float) else d[k]) for k in d}
        facts["transcription"] = {k: round(scores[k], 3) for k in ("precision", "recall", "f1", "f1_class")}
        facts["transcription"]["true_notes"] = scores["true_notes"]
        facts["tempo_true"] = round(played.tempo, 2)
        facts["tempo_verdict"] = evaluate.tempo_verdict(self.score.tempo, played.tempo)
        facts["colour"] = colour
        return facts

    def heard_seconds(self):
        """The notes of the current score as ``(onset, offset, pitch)`` in seconds of the audio."""
        score = self.score
        beat = 60.0 / score.tempo
        shift = float(score.info.get("offset", 0.0) or 0.0)
        return sorted((n.start * beat + shift, n.end * beat + shift, n.pitch) for n in score.notes if not n.drum)

    def facts(self):
        """What is known about the opened piece."""
        score = self.score
        if score is None:
            raise ValueError("Open a file first.")
        pitched = [n.pitch for n in score.notes if not n.drum]
        out = {
            "kind": self.kind, "title": score.title, "tempo": round(score.tempo, 2), "meter": list(score.meter),
            "notes": len(pitched), "drum_hits": sum(1 for n in score.notes if n.drum),
            "beats": round(score.length, 2), "seconds": round(score.length * 60.0 / score.tempo, 2),
            "channels": len(score.channels()),
            "lowest": pitch_name(min(pitched)) if pitched else None,
            "highest": pitch_name(max(pitched)) if pitched else None,
            "info": _plain(score.info), "version": __version__,
        }
        if not pitched:
            out["warning"] = "No notes were found."
        return out

    # ------------------------------------------------------------------ #
    # arranging
    # ------------------------------------------------------------------ #
    def arrange(self, arranger=DEFAULT, voices=3, steps_per_beat=4, bars_per_pattern=4):
        """Reduce the opened piece. Returns everything the page draws and offers for download."""
        if self.score is None:
            raise ValueError("Open a file first.")
        grid = quantize(self.score, int(steps_per_beat))
        # judge against the notes that were really played when they are known and the tempo was found
        judge, against = grid, "heard" if self.kind == "audio" else "file"
        if self.played is not None and abs(self.score.tempo / self.played.tempo - 1.0) <= 0.02:
            judge, against = quantize(self.played, int(steps_per_beat)), "played"
        truth = self.truth if against != "heard" else {}
        chosen = None
        table = []
        for name in ARRANGERS:
            arr = arrange(grid, name, int(voices))
            song = clio.to_song(arr, grid, int(bars_per_pattern))
            res = metrics.evaluate(judge, arr, song, truth)
            res["compression"] = metrics.evaluate(grid, arr, song)["compression"]
            row = {"arranger": name, "voices": len(arr.voices), "summary": getattr(ARRANGERS[name], "SUMMARY", "")}
            for key in SCORE_KEYS + ["compression"]:
                row[key] = None if res.get(key) is None else round(res[key], 3)
            table.append(row)
            if name == arranger:
                chosen = (arr, song)
        if chosen is None:
            raise ValueError("Unknown arranger '%s'. Available: %s" % (arranger, ", ".join(ARRANGERS)))
        arr, song = chosen
        problems = clio.validate(song)
        if problems:
            raise ValueError("The song came out invalid: " + "; ".join(problems))
        self.grid, self.song = grid, song
        mean_poly, max_poly = metrics.polyphony(grid)
        pitches = [n.pitch for n in grid.pitched] + [p for v in arr.voices for _s, _d, ps in v.events for p in ps]
        spb = grid.steps_per_beat
        effects = [{"kind": e["kind"], "start": round(e["start"] * spb, 2), "end": round(e["end"] * spb, 2),
                    "low": e["low"], "high": e["high"], "noise": bool(e.get("noise"))}
                   for e in grid.info.get("effects") or []]
        pitches += [int(round(e[k])) for e in effects if e["kind"] != "impact" for k in ("low", "high")]
        seq = song.get("sequence", [])
        return {
            "arranger": arranger, "title": self.score.title, "kind": self.kind,
            "tempo": round(grid.tempo, 2), "meter": list(grid.meter),
            "steps_per_beat": grid.steps_per_beat, "steps_per_bar": grid.steps_per_bar,
            "steps": max([grid.length] + [s + d for v in arr.voices for s, d, _p in v.events]
                         + [int(e["end"]) + 1 for e in effects]),
            "effects": effects,
            "step_seconds": 60.0 / grid.tempo / grid.steps_per_beat,
            "offset": float(self.score.info.get("offset", 0.0) or 0.0) if self.kind == "audio" else 0.0,
            "source": [[n.start, n.dur, n.pitch, n.channel] for n in grid.pitched],
            "source_drums": sorted({n.start for n in grid.drums}),
            "voices": [{"name": v.name, "role": v.role, "wave": (v.instrument or {}).get("wave"),
                        "notes": [[s, d, p] for s, d, ps in v.events for p in ps],
                        "chords": any(len(ps) > 1 for _s, _d, ps in v.events)} for v in arr.voices],
            "drums": [[s, "".join(h)] for s, h in arr.drums],
            "pitch_range": [min(pitches), max(pitches)] if pitches else [48, 72],
            "polyphony": [round(mean_poly, 2), max_poly],
            "quantisation_error": round(grid.error, 3),
            "patterns": [len(seq), len(set(seq))],
            "scores": table, "truth": dict(truth), "judged_against": against,
            "played": [[n.start, n.dur, n.pitch] for n in judge.pitched] if against == "played" else None,
            "song_json": clio.dumps(song), "song_name": _slug(self.score.title),
        }

    # ------------------------------------------------------------------ #
    # sound and files
    # ------------------------------------------------------------------ #
    def chip_wav(self, synth):
        """The arranged song played by CLIo's synthesizer (``engine.audio.synth``), as WAV bytes."""
        if self.song is None:
            raise ValueError("Arrange the piece first.")
        samples = synth.render_song(self.song)
        path = _temp(".wav")
        try:
            synth.write_wav(path, samples)
            with open(path, "rb") as f:
                return f.read()
        finally:
            os.remove(path)

    def original_wav(self, colour="band"):
        """The source as sound: the audio that was opened, or the MIDI file on the reference synthesizer."""
        from .audio import decode, synth
        if self.score is None:
            raise ValueError("Open a file first.")
        samples = self.samples if self.samples is not None else synth.render(self.score, colour)
        path = _temp(".wav")
        try:
            decode.write_wav(path, samples)
            with open(path, "rb") as f:
                return f.read()
        finally:
            os.remove(path)

    def midi_bytes(self):
        """The opened piece as a MIDI file: for audio, this is what was heard."""
        if self.score is None:
            raise ValueError("Open a file first.")
        path = _temp(".mid")
        try:
            write_midi(path, self.score)
            with open(path, "rb") as f:
                return f.read()
        finally:
            os.remove(path)


def _slug(text):
    out = "".join(c.lower() if c.isalnum() else "_" for c in (text or "song")).strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return out or "song"


def to_json(value):
    return json.dumps(value, separators=(",", ":"))
