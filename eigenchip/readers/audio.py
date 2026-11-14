# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Audio reader: a sound file in, a Score out.

    decode -> spectrogram -> transcriber -> notes in seconds
           -> tempo and beat phase -> notes in beats

What comes out is much poorer than a MIDI file: no instruments (the notes are
sorted into lines by pitch alone), drums read by a rule of thumb, a guessed
tempo, an assumed meter, and the mistakes of the transcriber on top.  Everything the reader guessed is recorded in
``score.info`` so that later stages - and people - can see how far to trust it.
"""
from __future__ import annotations

import os

from ..audio import RATE, analysis, decode
from ..audio.clean import clean as clean_notes
from ..audio.effects import find_effects
from ..audio.transcribe import DEFAULT, Spectrum, find_drums, transcribe
from ..ir import Note, Score
from ..voices import separate


DRUM_PITCH = {"k": 36, "s": 38, "h": 42}        # General MIDI kick, snare, closed hi-hat


def read_audio(path, transcriber=DEFAULT, tempo=None, offset=None, meter=(4, 4), steps_per_beat=4,
               rate=RATE, drums=True, voices=5, progress=None, quality="standard", clean="light", effects=True):
    """Transcribe a sound file.

    ``tempo`` (bpm) and ``offset`` (seconds to the first beat) override the
    estimates; give them when you know them, because a wrong tempo spoils
    everything after it.  ``drums=False`` leaves the drum detector out, and
    ``voices=0`` leaves all notes on one channel.

    ``quality`` trades time for detail (``fast``, ``standard``, ``fine``);
    ``clean`` says how hard to tidy the notes (``off``, ``light``, ``strict``);
    ``effects=False`` leaves risers, falls, swells and impacts unlooked for.
    """
    samples, rate, info = decode.load(path, rate)
    return score_from_samples(samples, rate, transcriber, tempo, offset, meter, steps_per_beat, info,
                              os.path.splitext(os.path.basename(path))[0], drums, voices, progress,
                              quality, clean, effects)


def score_from_samples(samples, rate=RATE, transcriber=DEFAULT, tempo=None, offset=None, meter=(4, 4),
                       steps_per_beat=4, info=None, title="", drums=True, voices=5, progress=None,
                       quality="standard", clean="light", effects=True):
    spec = Spectrum(samples, rate, progress=progress, quality=quality)
    hits = find_drums(spec) if drums else []            # first: the note cutter wants to know where the kicks are
    found = []
    if effects:
        spec.tell(0.15, "Looking for sweeps and swells")
        found = find_effects(spec)
        booms = [e["start"] for e in found if e["kind"] == "impact"]
        hits = [h for h in hits if not any(abs(h[0] - t) < 0.08 for t in booms)]       # the impact owns its own crack
    heard = transcribe(spec, transcriber, **({"restrike": 2.4} if clean == "strict" and transcriber != "pads" else {}))
    notes = clean_notes(heard, clean, found, hits)
    spec.tell(0.9, "Finding the beat")
    info = dict(info or {})
    info.update(source="audio", transcriber=transcriber, tempo_given=tempo is not None, quality=quality,
                clean=clean, cleaned_away=len(heard) - len(notes))
    guess, phase, confidence = analysis.estimate_tempo(spec.flux, spec.flux_fps)
    if tempo is None:
        bpm = guess
        info["tempo_confidence"] = round(confidence, 2)
    else:
        bpm = float(tempo)
        phase = analysis.beat_phase(spec.flux, spec.flux_fps, bpm)
    # drum hits are the sharpest evidence of the grid; slow material has no usable onsets of its own
    onsets = [t for t, _kind in hits] + ([] if transcriber == "pads" else [n[0] for n in notes])
    bpm, phase, agreement = analysis.fit_grid(onsets, bpm, phase, steps_per_beat,
                                              span=0.03 if tempo is None else 0.0)
    starts = [n[0] for n in notes] + [t for t, _kind in hits]
    if starts:
        phase = analysis.settle_phase(spec.flux, spec.flux_fps, bpm, phase, min(starts), steps_per_beat)
    if offset is not None:
        phase = float(offset)
    info.update(offset=round(phase, 4), grid_agreement=round(agreement, 2), drum_hits=len(hits))
    beat = 60.0 / bpm
    out = []
    for t0, t1, pitch, strength in notes:
        start = (t0 - phase) / beat
        end = (t1 - phase) / beat
        if end <= 0:
            continue
        start = max(0.0, start)
        vel = int(max(30, min(127, 40 + 87 * strength)))
        out.append(Note(start, max(end - start, 1.0 / (steps_per_beat * 2)), pitch, vel, 0, 0))
    for t, kind in hits:
        start = (t - phase) / beat
        if start > -0.5 / steps_per_beat:
            out.append(Note(max(0.0, start), 1.0 / steps_per_beat, DRUM_PITCH[kind], 100, 9, 0, drum=True))
    # effects keep their own list: they are not notes, and a writer may render them or leave them out
    info["effects"] = [dict(e, start=round(max(0.0, (e["start"] - phase) / beat), 3),
                            end=round(max(0.0, (e["end"] - phase) / beat), 3)) for e in found
                       if e["end"] - phase > 0]
    score = Score(out, bpm, meter, title, {0: "transcription"}, info)
    if voices and voices > 1:
        score = separate(score, int(voices))
        score.info["voices"] = len(score.channels())
    spec.tell(1.0, "Done listening")
    return score
