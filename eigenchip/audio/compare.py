# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Comparing two sounds: how much of the original is in the chip version?

The scores in ``metrics`` compare notes with notes.  For a recording there are
no true notes, only the notes the transcriber heard - and judging an
arrangement against those says nothing about what the transcriber got wrong.
This module compares sound with sound instead, in four respects that do not
depend on tone colour:

harmony    which of the twelve pitch classes sound, moment by moment
bass       the same for the low register only
loudness   how the level rises and falls
movement   where attacks are, and how the centre of the sound moves up and down

Each is a correlation, so 0 means "no more alike than two unrelated sounds"
and 1 "the same in this respect".  They are rough.  A chip cannot sound like an
orchestra and these numbers do not say that it does; they say whether the
right notes are sounding at the right times at about the right level.
"""
from __future__ import annotations

from . import RATE, need_numpy
from .transcribe import LOW, Spectrum

BLOCK = 0.25            # seconds: the grain of the comparison
LOW_REGISTER = 52       # MIDI pitch (E3): below it is "bass"
KEYS = ("harmony", "bass", "loudness", "movement")


def profile(samples, rate=RATE):
    """What is compared: per quarter second, the pitch classes, the bass pitch classes, level and centre."""
    np = need_numpy()
    if len(samples) < rate:
        raise ValueError("Too short to compare: less than a second of sound.")
    spec = Spectrum(samples, rate, hpss=False, deep=False, quality="fast")
    power = spec.raw.astype(np.float64) ** 2
    frames, bins = power.shape
    bps = spec.bps
    semis = bins // bps
    by_semi = power[:, :semis * bps].reshape(frames, semis, bps).sum(axis=2)
    per = max(1, int(round(BLOCK * spec.fps)))
    n = frames // per
    if n < 2:
        raise ValueError("Too short to compare: less than half a second.")
    blocks = by_semi[:n * per].reshape(n, per, semis).mean(axis=1)
    pitch = (LOW - 1) + np.arange(semis)

    def classes(sel):
        out = np.zeros((n, 12))
        for k in range(12):
            out[:, k] = blocks[:, sel & (pitch % 12 == k)].sum(axis=1)
        return np.sqrt(out)

    total = blocks.sum(axis=1)
    centre = (blocks * pitch).sum(axis=1) / np.maximum(total, 1e-12)
    whole = spec.whole.astype(np.float64) ** 2                      # tones only: where there is just noise,
    noise = np.minimum((spec.noise.astype(np.float64) ** 2).sum(axis=1), whole)       # there is no harmony to keep
    frames_n = (min(len(whole), frames) // per) * per
    tones = np.sqrt(np.maximum(0.0, whole - noise)[:frames_n].reshape(-1, per).mean(axis=1))
    tones = np.concatenate((tones, np.zeros(max(0, n - len(tones)))))[:n]
    flux = spec.flux
    per_f = max(1, int(round(BLOCK / 5 * spec.flux_fps)))            # attacks want a finer grain
    m = len(flux) // per_f
    return {"chroma": classes(pitch >= 0), "low": classes(pitch < LOW_REGISTER), "level": np.sqrt(total),
            "tones": tones,
            "centre": centre, "attacks": flux[:m * per_f].reshape(m, per_f).max(axis=1)}


def _corr(np, a, b, weight=None):
    n = min(len(a), len(b))
    a, b = np.asarray(a[:n], dtype=np.float64), np.asarray(b[:n], dtype=np.float64)
    w = np.ones(n) if weight is None else np.asarray(weight[:n], dtype=np.float64)
    if w.sum() <= 0:
        return 0.0
    a = a - (a * w).sum() / w.sum()
    b = b - (b * w).sum() / w.sum()
    den = float(np.sqrt((w * a * a).sum() * (w * b * b).sum()))
    return float((w * a * b).sum() / den) if den > 0 else 0.0


def _rows(np, a, b, weight):
    """Mean correlation of matching rows (each row a set of twelve pitch classes)."""
    n = min(len(a), len(b))
    a, b, w = a[:n], b[:n], weight[:n]
    a = a - a.mean(axis=1, keepdims=True)
    b = b - b.mean(axis=1, keepdims=True)
    mine = (a * a).sum(axis=1)
    den = np.sqrt(mine * (b * b).sum(axis=1))
    ok = (mine > 0) & (w > 0)                               # where the original has something to compare
    if not ok.any():
        return 0.0
    sim = np.where(den[ok] > 0, (a * b).sum(axis=1)[ok] / np.maximum(den[ok], 1e-30), 0.0)     # silence is no likeness
    return float((sim * w[ok]).sum() / w[ok].sum())


def compare(original, version, rate=RATE, lead=0.0):
    """Likeness of ``version`` to ``original`` (both mono samples), each score from 0 to 1.

    ``lead`` is how many seconds of the original pass before the version
    starts (the first beat of a recording is seldom at zero).
    """
    np = need_numpy()
    skip = int(round(max(0.0, lead) * rate))
    a, b = profile(np.asarray(original)[skip:], rate), profile(version, rate)
    n = min(len(a["level"]), len(b["level"]))
    w = a["level"][:n] / max(float(a["level"][:n].max()), 1e-12)     # quiet moments count less
    w = np.where(w > 0.05, w, 0.0)
    wt = a["tones"][:n] / max(float(a["tones"][:n].max()), 1e-12)   # harmony is judged where there are tones
    wt = np.where(wt > 0.05, wt, 0.0)
    loud = _corr(np, np.log(a["level"][:n] + 1e-3 * a["level"][:n].max() + 1e-12),
                 np.log(b["level"][:n] + 1e-3 * max(float(b["level"][:n].max()), 1e-12) + 1e-12))
    attacks = max(_corr(np, a["attacks"][max(0, k):], b["attacks"][max(0, -k):]) for k in (-1, 0, 1))
    centre = _corr(np, a["centre"][:n], b["centre"][:n], w)
    out = {"harmony": _rows(np, a["chroma"], b["chroma"], wt), "bass": _rows(np, a["low"], b["low"], wt),
           "loudness": loud, "movement": 0.5 * (max(0.0, attacks) + max(0.0, centre)),
           "attacks": attacks, "centre": centre, "seconds": n * BLOCK}
    for key in KEYS:
        out[key] = round(min(1.0, max(0.0, out[key])), 3)
    return out
