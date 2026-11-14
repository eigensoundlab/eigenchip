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

import math
import os

from ..audio import RATE, analysis, decode, melody
from ..audio.clean import clean as clean_notes
from ..audio.effects import find_effects
from ..audio.transcribe import DEFAULT, Spectrum, find_drums, transcribe
from ..ir import Note, Score
from ..voices import separate


NOISE_MATTERS = 0.08                            # share of the energy that must be lasting noise to write it down
DRUM_PITCH = {"k": 36, "s": 38, "h": 42}        # General MIDI kick, snare, closed hi-hat


def read_audio(path, transcriber=DEFAULT, tempo=None, offset=None, meter=(4, 4), steps_per_beat=4,
               rate=RATE, drums=True, voices=5, progress=None, quality="standard", clean="light", effects=True,
               tune=True):
    """Transcribe a sound file.

    ``tempo`` (bpm) and ``offset`` (seconds to the first beat) override the
    estimates; give them when you know them, because a wrong tempo spoils
    everything after it.  ``drums=False`` leaves the drum detector out, and
    ``voices=0`` leaves all notes on one channel.

    ``quality`` trades time for detail (``fast``, ``standard``, ``fine``);
    ``clean`` says how hard to tidy the notes (``off``, ``light``, ``strict``);
    ``effects=False`` leaves risers, falls, swells and impacts unlooked for.
    ``tune=False`` does not look for the tune with the whole piece in view
    (``eigenchip/audio/melody.py``) and leaves it to the sorting into lines.
    """
    samples, rate, info = decode.load(path, rate)
    return score_from_samples(samples, rate, transcriber, tempo, offset, meter, steps_per_beat, info,
                              os.path.splitext(os.path.basename(path))[0], drums, voices, progress,
                              quality, clean, effects, tune)


def score_from_samples(samples, rate=RATE, transcriber=DEFAULT, tempo=None, offset=None, meter=(4, 4),
                       steps_per_beat=4, info=None, title="", drums=True, voices=5, progress=None,
                       quality="standard", clean="light", effects=True, tune=True):
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
    line, rest = [], notes
    if tune and voices and voices > 1 and transcriber != "mono":
        spec.tell(0.85, "Following the tune")
        chosen = melody.find(spec, notes)
        line = melody.mend(spec, notes, chosen)
        taken = {id(notes[i]) for i in chosen}
        rest = [n for n in notes if id(n) not in taken]
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
    lead = []
    for part, into in ((rest, out), (line, lead)):
        for t0, t1, pitch, strength in part:
            start = (t0 - phase) / beat
            end = (t1 - phase) / beat
            if end <= 0:
                continue
            start = max(0.0, start)
            vel = int(max(30, min(127, 40 + 87 * strength)))
            into.append(Note(start, max(end - start, 1.0 / (steps_per_beat * 2)), pitch, vel, 0, 0))
    for t, kind in hits:
        start = (t - phase) / beat
        if start > -0.5 / steps_per_beat:
            out.append(Note(max(0.0, start), 1.0 / steps_per_beat, DRUM_PITCH[kind], 100, 9, 0, drum=True))
    # How loud the sound is at every step, for a writer that can say so (0 to 1, against the loud
    # passages) - and separately how much of it is lasting noise (wind, rumble, wash) and how bright.
    np = spec.np
    whole = spec.whole.astype(np.float64)
    top = float(np.percentile(whole, 95)) or 1.0
    k = max(1, int(round(0.35 * spec.fps)))                 # a drum hit is noise too, but it does not last
    floor = spec.noise.astype(np.float64)
    lasting = floor.copy()
    for d in range(1, k):
        lasting[:-d] = np.minimum(lasting[:-d], floor[d:])
    lasting = np.vstack((lasting[:1].repeat(k // 2, axis=0), lasting))[:len(floor)]     # centred on its window
    for t, _kind in hits:                                   # a run of hi-hats lasts too; the kit plays those
        lasting[max(0, int((t - 0.05) * spec.fps)):int((t + 0.2) * spec.fps) + 1] = 0.0
    hiss = np.minimum(np.sqrt((lasting ** 2).sum(axis=1)), whole)
    mids = np.array([math.sqrt(a * b) for a, b in zip(spec.noise_edges[:-1], spec.noise_edges[1:])])
    weight = np.maximum((lasting ** 2).sum(axis=1), 1e-12)
    bright = 69.0 + 12.0 * np.log2(np.exp((lasting ** 2 * np.log(mids)).sum(axis=1) / weight) / 440.0)
    tones = np.sqrt(np.maximum(0.0, whole ** 2 - hiss ** 2))
    step = beat / steps_per_beat
    count = int(max(0.0, len(whole) / spec.fps - phase) / step) + 1
    edges = np.clip(((phase + step * np.arange(count + 1)) * spec.fps).astype(int), 0, len(whole))

    def per_step(curve, digits=2):
        return [round(float(curve[a:max(b, a + 1)].mean()), digits) if a < len(curve) else 0.0
                for a, b in zip(edges[:-1], edges[1:])]

    info["attacks_per_second"] = round(len(analysis.peaks(np, spec.flux, 0.3)) / max(1.0, len(whole) / spec.fps), 2)
    info["loudness"] = per_step(np.minimum(1.0, tones / top))
    info["loudness_per_beat"] = steps_per_beat
    info["noise_share"] = round(float((hiss ** 2).sum() / max((whole ** 2).sum(), 1e-12)), 3)
    if info["noise_share"] >= NOISE_MATTERS:
        info["texture"] = {"level": per_step(np.minimum(1.0, hiss / top)), "pitch": per_step(bright, 1)}
    # effects keep their own list: they are not notes, and a writer may render them or leave them out
    info["effects"] = [dict(e, start=round(max(0.0, (e["start"] - phase) / beat), 3),
                            end=round(max(0.0, (e["end"] - phase) / beat), 3)) for e in found
                       if e["end"] - phase > 0]
    score = Score(out, bpm, meter, title, {0: "transcription"}, info)
    if voices and voices > 1:
        if lead:                                            # the tune is line 0; the rest is sorted into the lines below it
            rest = separate(score, max(1, int(voices) - 1))
            moved = [Note(n.start, n.dur, n.pitch, n.vel, n.channel if n.drum else n.channel + 1, n.program, n.drum)
                     for n in rest.notes]
            names = {0: "tune"}
            names.update({ch + 1: name for ch, name in rest.names.items()})
            score = Score(lead + moved, bpm, meter, title, names, dict(rest.info, lead_channel=0))
        else:
            score = separate(score, int(voices))
        score.info["voices"] = len(score.channels())
    spec.tell(1.0, "Done listening")
    return score
