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
import sys
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
        self.tune = False           # the source is a tune of the user's own (text, piano roll, keyboard, humming)
        self.written = None         # ... and that tune as it was written; ``score`` is it played through its form
        self.song = None
        self.grid = None
        self.likeness = None        # the chip sound compared with the sound that was opened, once both exist

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
        self.tune = False
        self.reference = self.samples = self.song = self.grid = self.played = self.likeness = None
        return self.facts()

    def open_tune(self, text="", tempo=100.0, meter=(4, 4), title="A tune", notes=None, sections=None):
        """Open a tune written as text, or given as ``notes`` - ``(start, length, pitch)`` in beats, as a piano roll
        or a keyboard hands them over (``eigenchip/readers/tune.py``): the composer's way in.  A new part of the
        tune begins at ``||`` in the text, or at the bars (counted from 0) in ``sections``."""
        from .readers.tune import play_form, read_notes, read_tune
        written = (read_notes(notes, tempo, meter, title, sections) if notes is not None
                   else read_tune(text, tempo, meter, title))
        self.tune, self.written = True, written
        self.score, self.truth, self.kind = play_form(written), {"melody": 0}, "midi"
        self.reference = self.samples = self.song = self.grid = self.played = self.likeness = None
        return self.facts()

    def open_hum(self, samples, rate=22050, tempo=100.0, meter=(4, 4), title="A hummed tune", progress=None,
                 grid=0.25):
        """Open a tune that was hummed, sung or whistled: mono float samples (``eigenchip/audio/hum.py``).
        The facts say which tempo the humming was found to have, near the one given.  ``grid``: the note value
        in beats that every note is put on - 0.25 a sixteenth, 0.5 an eighth, 1 a quarter."""
        from .audio import hum, need_numpy
        np = need_numpy()
        samples = np.ascontiguousarray(np.asarray(samples, dtype=np.float32).ravel())
        if not len(samples):
            raise ValueError("Nothing was recorded.")
        found, tempo = hum.notes(samples, int(rate), float(tempo), progress, float(grid))
        facts = self.open_tune(tempo=round(tempo), meter=meter, title=title, notes=found)
        facts["hummed"] = len(found)
        facts["written"] = [list(n) for n in found]
        return facts

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
        self.tune = False
        self.song = self.grid = self.likeness = None
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
    def arrange(self, arranger=DEFAULT, voices=3, steps_per_beat=4, bars_per_pattern=4, expression="full",
                style="plain", chords=None, form=None, ending=False, key=None, lead=None, chip=False):
        """Arrange the opened piece. Returns everything the page draws and offers for download.

        ``expression`` is ``full`` (levels and slides; the song needs CLIo 2.1)
        or ``plain`` (one level, sweeps in steps; plays on CLIo 2.0).  ``style``
        (a style, a genre or a mood), ``chords`` (text such as ``"C | G | Am F"``; ``-``
        leaves a bar to the arranger), ``ending`` (a closing bar, and the song is
        played once) and ``key`` (``"Am"``, when the key found is not the one
        meant) are for ``expand``, which writes parts instead of reducing them.
        ``form`` (``"A A B A"``) is for a tune of the user's own: the order in
        which its parts are played, and with marks how - ``(A)`` without the
        tune, ``A-`` quiet, ``A+`` a tone higher (``arrangers/plan.py``).
        ``chip`` plays a genre on the plain chip instruments.  ``lead`` names another sound for the tune
        (``arrangers.common.LEADS``: soft, flute, strings), for any arranger.
        """
        from .arrangers import plan
        from .arrangers.common import LEADS
        if lead and lead not in LEADS:
            raise ValueError("Unknown sound for the tune '%s'. Available: %s" % (lead, ", ".join(LEADS)))
        from .arrangers import expand
        written = {"style": style, "chords_given": expand.parse_chords(chords) if chords else None,
                   "ending": bool(ending), "key": expand.parse_key(key), "chip": bool(chip)}
        if self.score is None:
            raise ValueError("Open a file first.")
        if self.tune:
            from .readers.tune import play_form
            self.score = play_form(self.written, form)
        grid = quantize(self.score, int(steps_per_beat))
        # judge against the notes that were really played when they are known and the tempo was found
        judge, against = grid, "heard" if self.kind == "audio" else "file"
        if self.played is not None and abs(self.score.tempo / self.played.tempo - 1.0) <= 0.02:
            judge, against = quantize(self.played, int(steps_per_beat)), "played"
        truth = self.truth if against != "heard" else {}
        chosen = None
        table = []
        for name in ARRANGERS:
            arr = arrange(grid, name, int(voices), **(written if name == "expand" else {}))
            if lead and arr.voice("lead") is not None:
                sound = dict(LEADS[lead]["sound"])
                if chip and any(key in sound for key in clio.SHAPED):       # the plain chip has no such sounds:
                    sound = {k: v for k, v in sound.items() if k not in clio.SHAPED}
                    sound["volume"] = min(sound.get("volume", 0.3), 0.3)    # the wave alone, at a plain level
                arr.voice("lead").instrument = sound
            if self.tune and self.score.info.get("plan"):   # how each part of the form is played
                plan.apply(arr, self.score.info["parts"], self.score.info["plan"], grid.steps_per_beat)
            song = clio.to_song(arr, grid, int(bars_per_pattern), expression=expression)
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
        self.grid, self.song, self.likeness = grid, song, None
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
            "effects": effects, "expression": expression, "needs": song.get("needs"),
            "bed": any("bed" in tracks for tracks in song["patterns"].values()),
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
            "instruments": list(song["instruments"]),
            "chords_text": arr.notes.get("chords_text"), "style": arr.notes.get("style"),
            "key": arr.notes.get("key"), "ending": bool(arr.notes.get("ending")),
            "tune_text": self._tune_text(),
            "styles": [[name, how["about"]] for name, how in expand.STYLES.items()],
            "genres": [[name, how["about"], how["tempo"], expand.GROUPS[how["group"]]]
                       for group in expand.GROUPS for name, how in expand.GENRES.items() if how["group"] == group],
            "chip": bool(arr.notes.get("chip")),
            "moods": [[name, how["about"], how["tempo"]] for name, how in expand.MOODS.items()],
            "leads": [[name, how["about"]] for name, how in LEADS.items()], "lead": lead or "",
            "driven": any(inst.get(key) for inst in song["instruments"].values() for key in clio.SHAPED),
            **self._form(grid),
        }

    # ------------------------------------------------------------------ #
    # sound and files
    # ------------------------------------------------------------------ #
    def _tune_text(self):
        if not getattr(self, "tune", False):
            return None
        from .readers.tune import write_tune
        return write_tune(self.written)

    def _form(self, grid):
        """For a tune of the user's own: the tune as written and how its parts are played, for the page.

        ``written``: its notes ``[start, length, pitch]`` in beats; ``sections``: the bars (from 0) at which a part
        begins; ``form``: ``"A A B A"``; ``parts``: ``[name, start, start as written, length]`` in steps, one for
        each part played."""
        if not getattr(self, "tune", False):
            return {"written": None, "sections": None, "form": None, "parts": None, "longer": None, "plan": None}
        from .readers.tune import bar_beats, parts_of
        spb, bar = grid.steps_per_beat, bar_beats(self.written.meter)
        return {
            "written": [[n.start, n.dur, n.pitch] for n in self.written.notes],
            "sections": [int(round(start / bar)) for _name, start, _beats in parts_of(self.written)],
            "form": self.score.info.get("form"), "longer": self.score.info.get("longer"),
            "plan": list(self.score.info.get("plan") or []),
            "parts": [[name, int(round(at * spb)), int(round(start * spb)), int(round(beats * spb))]
                      for name, at, start, beats in self.score.info.get("parts") or []],
        }

    def song_json(self, mute=()):
        """The arranged song as JSON text, without the instruments named in ``mute``: what is switched off on the
        page is left out of the song that is taken away - a backing without its tune, say."""
        if self.song is None:
            raise ValueError("Arrange the piece first.")
        mute = set(mute or ())
        if not mute:
            return clio.dumps(self.song)
        left = [name for name in self.song["instruments"] if name not in mute]
        if not left:
            raise ValueError("Every voice is switched off: there is nothing to take away.")
        patterns = {}
        for name, tracks in self.song["patterns"].items():
            kept = {t: text for t, text in tracks.items() if t not in mute}
            if not kept:                                    # a stretch where only muted voices played still takes its time
                kept = {left[0]: ".:%d" % clio.track_length(next(iter(tracks.values())))}
            patterns[name] = kept
        return clio.dumps(dict(self.song, instruments={n: self.song["instruments"][n] for n in left}, patterns=patterns))

    def chip_stems(self, synth):
        """The arranged song voice by voice, for a player that switches voices on and off while it plays.

        One block of bytes: four bytes holding the length of a JSON header (little-endian), the header -
        ``{"rate", "length", "names"}`` - and then, for every name, ``length`` samples of 16-bit sound.  Together
        the voices add up to ``chip_wav``.  Needs a synthesizer that has ``render_tracks`` (CLIo 2.2.2)."""
        import struct
        if self.song is None:
            raise ValueError("Arrange the piece first.")
        tracks = synth.render_tracks(self.song)
        names = [name for name in self.song["instruments"] if name in tracks]
        length = max([len(tracks[name]) for name in names] + [0])
        rate = getattr(synth, "RATE", 22050)
        self.likeness = None
        try:
            import numpy as np
        except ImportError:
            np = None
        if self.samples is not None and names:              # there is a sound to compare with: do it now
            try:
                from .audio import compare
                whole = np.sum([np.asarray(tracks[name], dtype=np.float32) for name in names], axis=0)
                lead = float(self.score.info.get("offset", 0.0) or 0.0) if self.kind == "audio" else 0.0
                heard = compare.compare(self.samples, whole, rate, lead)
                self.likeness = {k: heard[k] for k in compare.KEYS + ("seconds",)}
            except Exception as err:                        # a comparison that fails must not cost the sound
                self.likeness = {"error": str(err)}
        header = json.dumps({"rate": rate, "length": length, "names": names}).encode("utf-8")
        out = [struct.pack("<I", len(header)), header]
        for name in names:
            if np is not None:
                out.append(np.clip(np.asarray(tracks[name], dtype=np.float64) * 32767.0, -32768, 32767)
                           .astype("<i2").tobytes())
            else:
                pcm = synth.to_pcm(tracks[name])
                if sys.byteorder == "big":
                    pcm.byteswap()
                out.append(pcm.tobytes())
        return b"".join(out)

    def chip_wav(self, synth, mute=()):
        """The arranged song played by CLIo's synthesizer (``engine.audio.synth``), as WAV bytes.

        ``mute`` names instruments of the song to leave out (a voice soloed is the others muted).
        """
        if self.song is None:
            raise ValueError("Arrange the piece first.")
        mute = set(mute or ())
        song = self.song if not mute else dict(self.song, instruments={
            name: (dict(inst, volume=0.0) if name in mute else inst) for name, inst in self.song["instruments"].items()})
        samples = synth.render_song(song)
        if not mute:
            self.likeness = None
        if self.samples is not None and not mute:           # there is a sound to compare with: do it now
            try:
                from .audio import compare
                rate = getattr(synth, "RATE", 22050)
                lead = float(self.score.info.get("offset", 0.0) or 0.0) if self.kind == "audio" else 0.0
                heard = compare.compare(self.samples, samples, rate, lead)
                self.likeness = {k: heard[k] for k in compare.KEYS + ("seconds",)}
            except Exception as err:                        # a comparison that fails must not cost the sound
                self.likeness = {"error": str(err)}
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
