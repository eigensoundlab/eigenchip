# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Audio reader: a sound file in, a Score out.

    decode -> spectrogram -> transcriber -> notes in seconds
           -> tempo and beat phase -> notes in beats

What comes out is much poorer than a MIDI file: one channel (no instruments),
no drums, a guessed tempo, an assumed meter, and the mistakes of the
transcriber on top.  Everything the reader guessed is recorded in
``score.info`` so that later stages - and people - can see how far to trust it.
"""
from __future__ import annotations

import os

from ..audio import RATE, analysis, decode
from ..audio.transcribe import DEFAULT, Spectrum, transcribe
from ..ir import Note, Score


def read_audio(path, transcriber=DEFAULT, tempo=None, offset=None, meter=(4, 4), steps_per_beat=4,
               rate=RATE):
    """Transcribe a sound file.

    ``tempo`` (bpm) and ``offset`` (seconds to the first beat) override the
    estimates; give them when you know them, because a wrong tempo spoils
    everything after it.
    """
    samples, rate, info = decode.load(path, rate)
    return score_from_samples(samples, rate, transcriber, tempo, offset, meter, steps_per_beat, info,
                              os.path.splitext(os.path.basename(path))[0])


def score_from_samples(samples, rate=RATE, transcriber=DEFAULT, tempo=None, offset=None, meter=(4, 4),
                       steps_per_beat=4, info=None, title=""):
    spec = Spectrum(samples, rate)
    notes = transcribe(spec, transcriber)
    info = dict(info or {})
    info.update(source="audio", transcriber=transcriber, tempo_given=tempo is not None)
    guess, phase, confidence = analysis.estimate_tempo(spec.flux, spec.flux_fps)
    if tempo is None:
        bpm = guess
        info["tempo_confidence"] = round(confidence, 2)
    else:
        bpm = float(tempo)
        phase = analysis.beat_phase(spec.flux, spec.flux_fps, bpm)
    onsets = [n[0] for n in notes]
    bpm, phase, agreement = analysis.fit_grid(onsets, bpm, phase, steps_per_beat,
                                              span=0.03 if tempo is None else 0.0)
    if onsets:
        phase = analysis.settle_phase(spec.flux, spec.flux_fps, bpm, phase, min(onsets), steps_per_beat)
    if offset is not None:
        phase = float(offset)
    info.update(offset=round(phase, 4), grid_agreement=round(agreement, 2))
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
    return Score(out, bpm, meter, title, {0: "transcription"}, info)
