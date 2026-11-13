# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Spectrogram -> notes, three ways.

``mono``   follows the single strongest pitch, frame by frame, with a
           smoothed path.  Right for an unaccompanied tune; on anything
           fuller it returns only the most prominent line.
``peaks``  harmonic summation with cancellation: find the strongest pitch in
           a frame, remove its partials, look again.  The classic multi-pitch
           baseline (after Klapuri).
``nmf``    explains every frame as a sum of fixed harmonic templates, several
           tone colours per pitch, plus a few broadband templates that soak
           up drums.  The classic matrix-factorisation baseline (after
           Smaragdis and Brown), with the templates fixed instead of learnt.

All three end in the same place - a pitch-by-time table of activations - and
share one routine that cuts the table into notes.  None of them knows what an
instrument is: the result is a single piano roll, with no channels and no
drums.  They are baselines to measure better ideas against, not the state of
the art (which, today, is a trained neural network).
"""
from __future__ import annotations

import math

from . import RATE, analysis, need_numpy

LOW, HIGH = 28, 96          # E1 .. C7
N_FFT, HOP = 4096, 512
MAX_HZ = 5500.0


def hz(pitch):
    return 440.0 * 2.0 ** ((pitch - 69) / 12.0)


class Spectrum:
    """The analysis every transcriber starts from."""

    def __init__(self, samples, rate=RATE, hpss=True):
        np = need_numpy()
        self.np = np
        self.rate = rate
        self.samples = samples
        self.fps = rate / float(HOP)
        self.raw = analysis.stft(samples, N_FFT, HOP, MAX_HZ, rate)
        self.mag = analysis.harmonic_part(self.raw, self.fps) if hpss else self.raw
        self.bin_hz = rate / float(N_FFT)
        self.pitches = list(range(LOW, HIGH + 1))
        self.flux, self.flux_fps = analysis.onset_strength(samples, rate)
        self._combs = {}
        self._energy = None

    @property
    def energy(self):
        """``[short frames, pitches]``: level of each pitch's first partials, in the short window.

        The long window says which pitch; this says when it was struck again.
        """
        if self._energy is None:
            np = self.np
            n_fft, hop = 1024, 256
            mag = analysis.stft(self.samples, n_fft, hop, MAX_HZ, self.rate)
            bins = mag.shape[1]
            pick = np.zeros((bins, len(self.pitches)), dtype=np.float32)
            for j, p in enumerate(self.pitches):
                for h in (1, 2, 3):
                    pos = int(round(hz(p) * h * n_fft / float(self.rate)))
                    if 3 <= pos < bins - 3:
                        pick[pos, j] += 1.0
                        pick[pos - 3, j] -= 0.5             # minus the level just beside the partial:
                        pick[pos + 3, j] -= 0.5             # a drum hit raises both and cancels out
            self._energy = np.maximum(0.0, mag @ pick)
        return self._energy

    def comb(self, weights, odd_only=False, wide=1.0):
        """``[bins, pitches]``: where the partials of each pitch fall, with the given weights."""
        key = (tuple(weights), odd_only, wide)
        if key not in self._combs:
            np = self.np
            bins = self.mag.shape[1]
            out = np.zeros((bins, len(self.pitches)), dtype=np.float32)
            centre = np.arange(bins)
            for j, p in enumerate(self.pitches):
                f0 = hz(p)
                for h, w in enumerate(weights, 1):
                    if not w or (odd_only and h % 2 == 0):
                        continue
                    pos = f0 * h / self.bin_hz
                    if pos >= bins - 1:
                        break
                    width = (0.9 + 0.012 * pos) * wide      # a partial is a narrow bump, wider higher up
                    lo, hi = max(0, int(pos - 3 * width)), min(bins, int(pos + 3 * width) + 2)
                    out[lo:hi, j] += w * np.exp(-0.5 * ((centre[lo:hi] - pos) / width) ** 2)
            self._combs[key] = out
        return self._combs[key]


# ---------------------------------------------------------------------- #
# activations -> notes (shared by every method)
# ---------------------------------------------------------------------- #
def cut_notes(spec, act, threshold=0.12, frame_share=0.08, min_seconds=0.07, gap_seconds=0.05,
              restrike=1.4, ghost=0.4, low_pitch=48, low_seconds=0.12):
    """Turn a ``[frames, pitches]`` activation table into ``(onset, offset, pitch, strength)`` notes.

    The table is smoothed in time (a three-frame median removes one-frame
    blips).  A note starts where a pitch rises above ``threshold`` (relative
    to the loud moments of the piece) and above ``frame_share`` of that
    frame's strongest pitch, and lasts while it stays above half of that.
    Short gaps are closed and short blips dropped.

    A held pitch is cut in two where the onset-strength curve has a peak *and*
    the pitch's own level, measured with a short window, has a notch there -
    lower just before the onset than both earlier and after, by a factor of
    ``restrike``: the same note played again.  Onsets are moved
    to the nearest onset peak, since the short window knows *when* far better
    than the long pitch analysis does.

    Notes below ``low_pitch`` must last ``low_seconds``: a kick drum looks like
    a very short bass note.  Last, faint notes that start together with a much
    stronger note an octave, a twelfth or two octaves below are dropped: they
    are usually its overtones.
    """
    np = spec.np
    frames = act.shape[0]
    if frames < 3 or not float(act.max()) > 0:
        return []
    act = np.median(np.stack((np.roll(act, 1, axis=0), act, np.roll(act, -1, axis=0))), axis=0)
    level = float(np.percentile(act.max(axis=1), 98)) or 1.0
    frame_top = act.max(axis=1, keepdims=True)
    strong = (act >= threshold * level) & (act >= frame_share * frame_top)
    weak = act >= 0.5 * threshold * level
    min_len = max(2, int(round(min_seconds * spec.fps)))
    low_len = max(min_len, int(round(low_seconds * spec.fps)))
    gap = max(1, int(round(gap_seconds * spec.fps)))
    ratio = spec.flux_fps / spec.fps
    peak_frames = analysis.peaks(np, spec.flux, 0.05)
    onset_peaks = np.asarray(peak_frames, dtype=np.float64) / spec.flux_fps
    energy = spec.energy
    notes = []
    for j, pitch in enumerate(spec.pitches):
        if not strong[:, j].any():
            continue
        col = weak[:, j]
        edges = np.flatnonzero(np.diff(np.concatenate(([0], col.view(np.int8), [0]))))
        merged = []
        for a, b in zip(edges[0::2], edges[1::2]):
            a, b = int(a), int(b)
            if merged and a - merged[-1][1] <= gap:
                merged[-1][1] = b
            else:
                merged.append([a, b])
        for a, b in merged:
            if b - a < min_len or not strong[a:b, j].any():
                continue
            cuts = [a]
            e = energy[:, j]
            for pf in peak_frames:                          # was it struck again at one of the onsets?
                f = pf / ratio
                if f < cuts[-1] + min_len or f > b - min_len:
                    continue
                dip = float(e[max(0, pf - 3):pf + 1].mean())           # just before the onset
                after = e[pf + 2:pf + 7]
                prior = e[max(0, pf - 12):max(1, pf - 4)]               # the note as it was sounding
                if not len(after) or not len(prior):
                    continue
                after, prior = float(after.mean()), float(prior.mean())
                if after > restrike * dip and (dip < 0.72 * prior or after > 1.8 * prior):
                    cuts.append(int(round(f)))
            cuts.append(b)
            for s, e2 in zip(cuts[:-1], cuts[1:]):
                if e2 - s < (low_len if pitch < low_pitch else min_len):
                    continue
                t0, t1 = s / spec.fps, e2 / spec.fps
                if len(onset_peaks):                        # the long window hears a note early: look ahead
                    near = onset_peaks[(onset_peaks >= t0 - 0.04) & (onset_peaks <= t0 + 0.09)]
                    if len(near):
                        t0 = float(near[np.argmin(np.abs(near - (t0 + 0.025)))])
                    else:
                        t0 += 0.02
                t1 = max(t0 + 0.03, t1 - 0.03)
                notes.append((t0, t1, pitch, float(act[s:e2, j].mean() / level)))
    notes.sort()
    if ghost:
        kept = []
        for n in notes:
            shadow = False
            for m in notes:
                if m[0] > n[0] + 0.05:
                    break
                if abs(m[0] - n[0]) <= 0.05 and (n[2] - m[2]) in (12, 19, 24, 28) and n[3] < ghost * m[3]:
                    shadow = True
                    break
            if not shadow:
                kept.append(n)
        notes = kept
    return notes


# ---------------------------------------------------------------------- #
# the three methods
# ---------------------------------------------------------------------- #
def _salience(spec, harmonics=10, decay=0.8):
    np = spec.np
    weights = [decay ** h for h in range(harmonics)]
    mag = np.sqrt(spec.mag)                                 # compress: loud partials should not drown soft ones
    return mag, weights, _rooted(spec, mag, mag @ spec.comb(weights))


def _rooted(spec, mag, sal):
    """Scale a salience table by how much of each pitch's support is its own fundamental.

    Summing partials also rewards the octave *below* a tone (every partial of
    C4 is a partial of C3).  A real C3 has energy at its own fundamental; the
    phantom one does not.
    """
    np = spec.np
    root = mag @ spec.comb([1.0])
    full = mag @ spec.comb([1.0] * 6)
    return sal * np.sqrt(np.minimum(1.0, 2.5 * root / np.maximum(full, 1e-9)))


def transcribe_mono(spec, low=48, high=96, jump_cost=0.035, **cut):
    """The one most prominent line: strongest pitch per frame along a smooth path."""
    np = spec.np
    _mag, _w, sal = _salience(spec)
    a, b = max(0, low - LOW), min(len(spec.pitches), high - LOW + 1)
    s = sal[:, a:b]
    top = float(np.percentile(s.max(axis=1), 98)) or 1.0
    s = s / top
    frames, count = s.shape
    if frames == 0:
        return []
    steps = np.abs(np.arange(count)[:, None] - np.arange(count)[None, :]).astype(np.float32)
    penalty = jump_cost * np.minimum(steps, 12.0)           # staying put is free, leaps cost
    score = s[0].copy()
    back = np.zeros((frames, count), dtype=np.int32)
    for t in range(1, frames):
        cand = score[:, None] - penalty
        back[t] = cand.argmax(axis=0)
        score = cand.max(axis=0) + s[t]
    path = np.zeros(frames, dtype=np.int32)
    path[-1] = int(score.argmax())
    for t in range(frames - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    act = np.zeros_like(sal)
    rows = np.arange(frames)
    act[rows, a + path] = sal[rows, a + path]
    cut.setdefault("threshold", 0.3)
    return cut_notes(spec, act, **cut)


def transcribe_peaks(spec, voices=6, share=0.32, **cut):
    """Harmonic summation with cancellation: strongest pitch, remove its partials, repeat."""
    np = spec.np
    mag, weights, _ = _salience(spec)
    comb = spec.comb(weights)
    mask = np.minimum(1.0, 1.6 * spec.comb([1.0] * len(weights), wide=2.2))    # a pitch's partials, generously
    residual = mag.copy()
    act = np.zeros((mag.shape[0], len(spec.pitches)), dtype=np.float32)
    rows = np.arange(mag.shape[0])
    first = None
    for _ in range(voices):
        sal = _rooted(spec, residual, residual @ comb)
        best = sal.argmax(axis=1)
        value = sal[rows, best]
        if first is None:
            first = np.maximum(value, 1e-9)
        keep = value >= share * first
        if not keep.any():
            break
        act[rows[keep], best[keep]] = np.maximum(act[rows[keep], best[keep]], value[keep])
        residual[keep] *= (1.0 - mask[:, best[keep]].T)
    cut.setdefault("threshold", 0.2)
    return cut_notes(spec, act, **cut)


def transcribe_nmf(spec, iterations=40, sparsity=0.03, **cut):
    """Fixed harmonic templates, activations found by multiplicative updates (KL divergence)."""
    np = spec.np
    colours = [                                             # several tone colours for every pitch
        ([1.0 / h ** 2.2 for h in range(1, 7)], False),     # dull: almost a sine
        ([1.0 / h for h in range(1, 13)], False),           # bright: saw-like
        ([1.0 / h ** 0.6 for h in range(1, 9)], False),     # organ-like
        ([1.0 / h for h in range(1, 14)], True),            # hollow: odd partials only
    ]
    bins = spec.mag.shape[1]
    parts = []
    for weights, odd in colours:
        c = spec.comb(weights, odd).copy()
        parts.append(c / np.maximum(c.sum(axis=0, keepdims=True), 1e-9))
    centre = np.arange(bins, dtype=np.float32)
    noise = np.stack([np.exp(-centre / (bins * s)) for s in (0.03, 0.15)] + [np.ones(bins, dtype=np.float32),
                     centre / bins], axis=1)                # broadband shapes: thumps, hiss
    noise = noise / noise.sum(axis=0, keepdims=True)
    W = np.concatenate(parts + [noise.astype(np.float32)], axis=1)
    V = spec.mag.T + 1e-7                                   # [bins, frames]
    H = np.full((W.shape[1], V.shape[1]), float(V.mean()), dtype=np.float32)
    norm = W.sum(axis=0)[:, None] + sparsity
    for _ in range(iterations):
        H *= (W.T @ (V / (W @ H + 1e-7))) / norm
    count = len(spec.pitches)
    act = sum(H[i * count:(i + 1) * count] for i in range(len(colours))).T
    cut.setdefault("threshold", 0.15)
    cut.setdefault("frame_share", 0.12)
    return cut_notes(spec, np.ascontiguousarray(act), **cut)


TRANSCRIBERS = {"mono": transcribe_mono, "peaks": transcribe_peaks, "nmf": transcribe_nmf}
DEFAULT = "nmf"


def transcribe(samples, method=DEFAULT, rate=RATE, **options):
    """Samples -> ``[(onset, offset, pitch, strength), ...]`` in seconds."""
    if method not in TRANSCRIBERS:
        raise ValueError("Unknown transcriber '%s'. Choose from: %s" % (method, ", ".join(TRANSCRIBERS)))
    spec = samples if isinstance(samples, Spectrum) else Spectrum(samples, rate)
    if not len(spec.samples) or float(abs(spec.samples).max()) < 1e-4:
        return []                                           # silence: nothing to find, and nothing to scale by
    return TRANSCRIBERS[method](spec, **options)
