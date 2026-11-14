# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Spectrogram -> notes, four ways, and drums.

``mono``   follows the single strongest pitch, frame by frame, with a
           smoothed path.  Right for an unaccompanied tune; on anything
           fuller it returns only the most prominent line.
``peaks``  harmonic summation with cancellation: find the strongest pitch in
           a frame, remove its partials, look again.  The classic multi-pitch
           baseline (after Klapuri).
``nmf``    explains every frame as a sum of fixed harmonic templates, several
           tone colours per pitch, plus a few broadband templates that soak
           up noise.  The classic matrix-factorisation baseline (after
           Smaragdis and Brown), with the templates fixed instead of learnt.
``pads``   the same templates read slowly: activations are smoothed over
           a third of a second and only what lasts is kept.  For sustained sound -
           drones, pads, slow swells - where there are no clear attacks to
           hang notes on.

All of them start from one picture of the sound (``Spectrum``): a spectrogram
with bins spaced evenly in pitch, three to the semitone, from A0 up.  Its lowest
octaves come from a second, much longer analysis window, because telling
neighbouring notes apart at 40 Hz takes most of a second of sound.

All of them end in the same place - a pitch-by-time table of activations - and
share one routine that cuts the table into notes.  None knows what an
instrument is: the result is a single piano roll.  ``find_drums`` looks for
kick, snare and hi-hat separately, from the shape of each attack.

They are baselines to measure better ideas against, not the state of the art
(which, today, is a trained neural network).
"""
from __future__ import annotations

import math

from . import RATE, analysis, need_numpy
from .decode import resample

LOW, HIGH = 21, 96              # A0 .. C7: the notes that can be reported
BPS = 3                         # spectrogram bins per semitone
N_FFT, HOP = 4096, 512          # the ordinary window: 186 ms
MAX_HZ = 5500.0
DEEP_FACTOR, DEEP_N_FFT = 8, 2048       # the deep window: 743 ms, on sound slowed to an eighth of the rate
QUIET = 1.0                     # 1: one threshold for the whole piece; lower: quiet passages get their own
NOISE_LOW = 40.0                # Hz: noise is looked for from here up
CROSS = (55.0, 80.0)            # Hz: the deep window below, the ordinary one above, blended between
SHORT_N_FFT, SHORT_HOP = 1024, 256      # the timing window: 46 ms


# How much work to spend. "bins" are spectrogram bins per semitone, "hop" the step between
# frames in samples, "passes" the rounds of template matching. The cost grows roughly with
# bins / hop. On the test corpus "fast" loses about three points of F1 against "standard"
# and "fine" gains about one: the picture is not what limits these methods there.
QUALITY = {
    "fast": {"bins": 3, "hop": 1024, "passes": 10},
    "standard": {"bins": 3, "hop": 512, "passes": 16},
    "fine": {"bins": 4, "hop": 256, "passes": 16},
}


def hz(pitch):
    return 440.0 * 2.0 ** ((pitch - 69) / 12.0)


class Spectrum:
    """The analysis every transcriber starts from."""

    def __init__(self, samples, rate=RATE, hpss=True, progress=None, deep=True, quality="standard", **override):
        np = need_numpy()
        if quality not in QUALITY:
            raise ValueError("Unknown quality '%s'. Choose from: %s" % (quality, ", ".join(QUALITY)))
        self.quality = dict(QUALITY[quality], name=quality)
        self.quality.update(override)
        BPS, HOP = int(self.quality["bins"]), int(self.quality["hop"])
        self.bps, self.hop = BPS, HOP
        self.np = np
        self.rate = rate
        self.samples = np.asarray(samples, dtype=np.float32)
        self.tell = progress or (lambda fraction, text: None)
        self.fps = rate / float(HOP)
        self.pitches = list(range(LOW, HIGH + 1))
        count = int(math.ceil(12 * BPS * math.log(MAX_HZ / hz(LOW - 1), 2)))
        self.centres = hz(LOW - 1) * 2.0 ** (np.arange(count) / (12.0 * BPS))

        self.tell(0.03, "Measuring the spectrum")
        linear = analysis.stft(self.samples, N_FFT, HOP, MAX_HZ, rate) / (N_FFT / 4.0)
        gather = analysis.log_matrix(np, linear.shape[1], rate / float(N_FFT), self.centres, BPS)
        raw = np.sqrt((linear ** 2) @ gather.T)
        # what is noise rather than tone, in bands a third of an octave wide (see analysis.noise_floor)
        self.noise_edges = [NOISE_LOW * 2.0 ** (k / 3.0) for k in range(int(3 * math.log(MAX_HZ / NOISE_LOW, 2)) + 1)]
        noise = analysis.noise_floor(np, linear, rate / float(N_FFT), self.noise_edges)
        whole = np.sqrt((linear[:, int(NOISE_LOW * N_FFT / rate):] ** 2).sum(axis=1))
        lobe = np.full(count, 2.0 * rate / N_FFT)                    # width of a spectral peak, in Hz
        if deep and len(self.samples) > DEEP_N_FFT * DEEP_FACTOR:
            slow_rate = rate / float(DEEP_FACTOR)
            slow = resample(self.samples, rate, slow_rate)
            low = analysis.stft(slow, DEEP_N_FFT, HOP // DEEP_FACTOR, None, slow_rate) / (DEEP_N_FFT / 4.0)
            gather_low = analysis.log_matrix(np, low.shape[1], slow_rate / DEEP_N_FFT, self.centres, BPS)
            frames = min(len(raw), len(low))
            fine = analysis.noise_floor(np, low, slow_rate / DEEP_N_FFT, self.noise_edges)      # the low bands need
            lows = (noise[:frames] == 0).all(axis=0) & (fine[:frames] != 0).any(axis=0)         # the long window
            noise = noise[:frames]
            noise[:, lows] = fine[:frames][:, lows]
            whole = whole[:frames]
            raw, low = raw[:frames], np.sqrt((low[:frames] ** 2) @ gather_low.T)
            share = np.clip((CROSS[1] - self.centres) / (CROSS[1] - CROSS[0]), 0.0, 1.0).astype(np.float32)
            raw = raw * (1.0 - share) + low * share
            lobe = lobe * (1.0 - share) + (2.0 * slow_rate / DEEP_N_FFT) * share
        self.raw = raw.astype(np.float32)
        self.noise = noise                                           # [frames, bands] amplitude of the noise
        self.whole = whole                                           # [frames] amplitude of everything
        step = self.centres * (2.0 ** (1.0 / (12.0 * BPS)) - 1.0)    # width of a pitch bin, in Hz
        self.sigma = np.maximum(0.7, 0.5 * lobe / step)              # width of a peak, in pitch bins

        self.tell(0.10, "Setting drums and noise aside")
        self.mag = analysis.harmonic_part(self.raw, self.fps, bins=(17 * BPS // 3) | 1) if hpss else self.raw
        self.short = analysis.stft(self.samples, SHORT_N_FFT, SHORT_HOP, rate=rate)
        self.flux = analysis.flux_of(self.short)
        self.flux_fps = rate / float(SHORT_HOP)
        self._combs = {}
        self._energy = None
        self._nmf = None
        self.kicks = []                 # times of kick drums, once find_drums has run

    def place(self, pitch, harmonic=1):
        """Where a partial falls, in (fractional) pitch bins."""
        return self.bps * (pitch - LOW + 1) + 12.0 * self.bps * math.log(harmonic, 2)

    def comb(self, weights, odd_only=False, wide=1.0, unit=False):
        """``[bins, pitches]``: where the partials of each pitch fall, with the given weights.

        A partial is a bump as wide as a spectral peak is at that height of the
        picture - broad at the bottom, narrow at the top.  For matching shapes
        that is right as it is; for *adding up* evidence each bump must weigh
        the same, whatever its width: ``unit`` gives every bump an area of one.
        """
        key = (tuple(weights), odd_only, wide, unit)
        if key not in self._combs:
            np = self.np
            bins = self.mag.shape[1]
            out = np.zeros((bins, len(self.pitches)), dtype=np.float32)
            centre = np.arange(bins)
            for j, p in enumerate(self.pitches):
                for h, w in enumerate(weights, 1):
                    if not w or (odd_only and h % 2 == 0):
                        continue
                    pos = self.place(p, h)
                    if pos >= bins - 1:
                        break
                    width = float(self.sigma[int(pos)]) * wide
                    lo, hi = max(0, int(pos - 3 * width)), min(bins, int(pos + 3 * width) + 2)
                    bump = np.exp(-0.5 * ((centre[lo:hi] - pos) / width) ** 2)
                    out[lo:hi, j] += w * (bump / (width * 2.5066) if unit else bump)
            self._combs[key] = out
        return self._combs[key]

    @property
    def energy(self):
        """``[short frames, pitches]``: level of each pitch's first partials, in the short window.

        The long window says which pitch; this says when it was struck again.
        """
        if self._energy is None:
            np = self.np
            bins = self.short.shape[1]
            pick = np.zeros((bins, len(self.pitches)), dtype=np.float32)
            for j, p in enumerate(self.pitches):
                for h in (1, 2, 3):
                    pos = int(round(hz(p) * h * SHORT_N_FFT / float(self.rate)))
                    if 3 <= pos < bins - 3:
                        pick[pos, j] += 1.0
                        pick[pos - 3, j] -= 0.5             # minus the level just beside the partial:
                        pick[pos + 3, j] -= 0.5             # a drum hit raises both and cancels out
            self._energy = np.maximum(0.0, self.short @ pick)
        return self._energy


# ---------------------------------------------------------------------- #
# activations -> notes (shared by every method)
# ---------------------------------------------------------------------- #
def cut_notes(spec, act, threshold=0.12, frame_share=0.08, min_seconds=0.07, gap_seconds=0.05,
              restrike=1.4, ghost=0.4, low_pitch=48, low_seconds=0.12, kick_seconds=0.24,
              smooth_seconds=0.0, snap=True, quiet=QUIET):
    """Turn a ``[frames, pitches]`` activation table into ``(onset, offset, pitch, strength)`` notes.

    The table is smoothed in time (a three-frame median removes one-frame
    blips; ``smooth_seconds`` adds a longer average for slow material).  A note
    starts where a pitch rises above ``threshold`` (relative to the loud moments
    of the piece) and above ``frame_share`` of that frame's strongest pitch,
    and lasts while it stays above half of that.  Short gaps are closed and
    short blips dropped.

    A held pitch is cut in two where the onset-strength curve has a peak *and*
    the pitch's own level, measured with a short window, has a notch there -
    lower just before the onset than both earlier and after, by a factor of
    ``restrike``: the same note played again.  With ``snap``, onsets are moved
    to the nearest onset peak, since the short window knows *when* far better
    than the long pitch analysis does.

    With ``quiet`` below 1 the threshold follows the music: a passage is judged
    against the loudest moment within 2.5 s of it, down to ``quiet`` times the
    level of the whole piece.  It finds the notes of quiet passages and, with
    them, more wrong ones; it is off by default (see the research log).

    Notes below ``low_pitch`` must last ``low_seconds`` - and ``kick_seconds``
    if they begin where a kick drum was found - because a kick looks like a
    very short bass note.  Last, faint notes that start together with a much
    stronger note an octave, a twelfth or two octaves below are dropped: they
    are usually its overtones.
    """
    np = spec.np
    frames = act.shape[0]
    if frames < 3 or not float(act.max()) > 0:
        return []
    act = np.median(np.stack((np.roll(act, 1, axis=0), act, np.roll(act, -1, axis=0))), axis=0)
    if smooth_seconds:
        span = max(3, int(round(smooth_seconds * spec.fps)) | 1)
        kernel = np.ones(span, dtype=np.float32) / span
        padded = np.pad(act, ((span // 2, span // 2), (0, 0)), mode="edge")
        csum = np.cumsum(np.vstack((np.zeros((1, act.shape[1]), dtype=padded.dtype), padded)), axis=0)
        act = (csum[span:] - csum[:-span]) * kernel[0]
    level = float(np.percentile(act.max(axis=1), 98)) or 1.0
    frame_top = act.max(axis=1, keepdims=True)
    bar = level
    if quiet and quiet < 1.0:                               # a quiet passage is judged against itself, within limits
        k = max(1, int(round(2.5 * spec.fps)))
        top = frame_top[:, 0]
        near = np.array([top[max(0, i - k):i + k + 1].max() for i in range(frames)])
        bar = np.maximum(quiet * level, np.minimum(level, near))[:, None]
    strong = (act >= threshold * bar) & (act >= frame_share * frame_top)
    weak = act >= 0.5 * threshold * bar
    min_len = max(2, int(round(min_seconds * spec.fps)))
    low_len = max(min_len, int(round(low_seconds * spec.fps)))
    kick_len = max(low_len, int(round(kick_seconds * spec.fps)))
    gap = max(1, int(round(gap_seconds * spec.fps)))
    ratio = spec.flux_fps / spec.fps
    peak_frames = np.asarray(analysis.peaks(np, spec.flux, 0.05), dtype=np.int64)
    onset_peaks = peak_frames / spec.flux_fps
    kicks = np.asarray(sorted(spec.kicks), dtype=np.float64)
    energy = spec.energy if restrike else None
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
        deep = pitch < low_pitch
        ahead = 0.09 + (0.25 if hz(pitch) < CROSS[1] else 0.0)      # the deep window hears a note much earlier
        for a, b in merged:
            if b - a < min_len or not strong[a:b, j].any():
                continue
            cuts = [a]
            if restrike and len(peak_frames):
                e = energy[:, j]
                first = int(np.searchsorted(peak_frames, (a + min_len) * ratio))
                last = int(np.searchsorted(peak_frames, (b - min_len) * ratio, side="right"))
                for pf in peak_frames[first:last]:              # was it struck again at one of the onsets?
                    pf = int(pf)
                    f = pf / ratio
                    if f < cuts[-1] + min_len:
                        continue
                    after = e[pf + 2:pf + 7]
                    prior = e[max(0, pf - 12):max(1, pf - 4)]   # the note as it was sounding
                    if not len(after) or not len(prior):
                        continue
                    dip = float(e[max(0, pf - 3):pf + 1].mean())           # just before the onset
                    after, prior = float(after.mean()), float(prior.mean())
                    if after > restrike * dip and (dip < 0.72 * prior or after > 1.8 * prior):
                        cuts.append(int(round(f)))
            cuts.append(b)
            for s, e2 in zip(cuts[:-1], cuts[1:]):
                t0, t1 = s / spec.fps, e2 / spec.fps
                if snap and len(onset_peaks):                   # the long window hears a note early: look ahead
                    i0 = int(np.searchsorted(onset_peaks, t0 - 0.04))
                    i1 = int(np.searchsorted(onset_peaks, t0 + ahead, side="right"))
                    if i1 > i0:
                        near = onset_peaks[i0:i1]
                        t0 = float(near[np.argmin(np.abs(near - (t0 + 0.025)))])
                    else:
                        t0 += 0.02
                need = min_len
                if deep:
                    hit = len(kicks) and float(np.min(np.abs(kicks - t0))) <= 0.06
                    need = kick_len if hit else low_len
                if (t1 - t0) * spec.fps < need - 0.5 or e2 - s < min_len:
                    continue
                t1 = max(t0 + 0.03, t1 - 0.03)
                notes.append((t0, t1, pitch, float(act[s:e2, j].mean() / level)))
    notes.sort()
    if ghost:
        kept = []
        for i, n in enumerate(notes):
            shadow = False
            for m in notes[max(0, i - 40):i + 40]:
                if abs(m[0] - n[0]) <= 0.05 and (n[2] - m[2]) in (12, 19, 24, 28) and n[3] < ghost * m[3]:
                    shadow = True
                    break
            if not shadow:
                kept.append(n)
        notes = kept
    return notes


# ---------------------------------------------------------------------- #
# the methods
# ---------------------------------------------------------------------- #
def _salience(spec, harmonics=10, decay=0.8):
    np = spec.np
    weights = [decay ** h for h in range(harmonics)]
    mag = np.sqrt(spec.mag)                                 # compress: loud partials should not drown soft ones
    return mag, weights, _rooted(spec, mag, mag @ spec.comb(weights, unit=True))


def _rooted(spec, mag, sal):
    """Scale a salience table by how much of each pitch's support is its own fundamental.

    Summing partials also rewards the octave *below* a tone (every partial of
    C4 is a partial of C3).  A real C3 has energy at its own fundamental; the
    phantom one does not.
    """
    np = spec.np
    root = mag @ spec.comb([1.0], unit=True)
    full = mag @ spec.comb([1.0] * 6, unit=True)
    return sal * np.sqrt(np.minimum(1.0, 2.5 * root / np.maximum(full, 1e-9)))


def transcribe_mono(spec, low=48, high=96, jump_cost=0.035, **cut):
    """The one most prominent line: strongest pitch per frame along a smooth path."""
    np = spec.np
    spec.tell(0.3, "Following the strongest line")
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
    spec.tell(0.8, "Cutting notes")
    return cut_notes(spec, act, **cut)


def transcribe_peaks(spec, voices=6, share=0.32, **cut):
    """Harmonic summation with cancellation: strongest pitch, remove its partials, repeat."""
    np = spec.np
    mag, weights, _ = _salience(spec)
    comb = spec.comb(weights, unit=True)
    mask = np.minimum(1.0, 1.6 * spec.comb([1.0] * len(weights), wide=2.2))    # a pitch's partials, generously
    residual = mag.copy()
    act = np.zeros((mag.shape[0], len(spec.pitches)), dtype=np.float32)
    rows = np.arange(mag.shape[0])
    first = None
    for i in range(voices):
        spec.tell(0.25 + 0.5 * i / voices, "Looking for pitches, round %d of %d" % (i + 1, voices))
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
    spec.tell(0.8, "Cutting notes")
    return cut_notes(spec, act, **cut)


def _nmf_activation(spec, iterations=None, sparsity=0.03, rooted=2.5):
    """Fixed harmonic templates, activations found by multiplicative updates (KL divergence)."""
    if spec._nmf is not None:
        return spec._nmf
    np = spec.np
    iterations = int(iterations or spec.quality["passes"])
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
    centre = np.arange(bins, dtype=np.float32) / bins
    noise = np.stack([np.exp(-centre / 0.08), np.exp(-((centre - 0.5) / 0.2) ** 2), np.ones(bins, dtype=np.float32),
                      centre ** 2], axis=1)                 # broadband shapes: rumble, body, hiss
    noise = noise / noise.sum(axis=0, keepdims=True)
    W = np.concatenate(parts + [noise.astype(np.float32)], axis=1).astype(np.float32)
    V = (spec.mag.T + 1e-7).astype(np.float32)              # [bins, frames]
    H = np.full((W.shape[1], V.shape[1]), float(V.mean()), dtype=np.float32)
    norm = (W.sum(axis=0)[:, None] + sparsity).astype(np.float32)
    for i in range(iterations):
        if i % 3 == 0:
            spec.tell(0.2 + 0.6 * i / iterations, "Matching tone colours, pass %d of %d" % (i + 1, iterations))
        H *= (W.T @ (V / (W @ H + 1e-7))) / norm
    count = len(spec.pitches)
    act = sum(H[i * count:(i + 1) * count] for i in range(len(colours))).T
    if rooted:
        # a chord is also explained, a little, by one low note whose overtones are the chord's notes;
        # such a phantom has nothing at its own fundamental
        root = spec.mag @ spec.comb([1.0])
        full = spec.mag @ spec.comb([1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        act = act * np.minimum(1.0, rooted * root / np.maximum(full, 1e-9)) ** 0.5
    spec._nmf = np.ascontiguousarray(act.astype(np.float32))
    return spec._nmf


def transcribe_nmf(spec, iterations=None, sparsity=0.03, **cut):
    """Template matching, read note by note."""
    act = _nmf_activation(spec, iterations, sparsity)
    cut.setdefault("threshold", 0.2)
    cut.setdefault("frame_share", 0.15)
    cut.setdefault("ghost", 0.55)
    spec.tell(0.82, "Cutting notes")
    return cut_notes(spec, act, **cut)


def transcribe_pads(spec, iterations=None, sparsity=0.03, **cut):
    """Template matching, read slowly: only what lasts counts, and attacks are not looked for."""
    act = _nmf_activation(spec, iterations, sparsity)
    for key, value in (("threshold", 0.25), ("frame_share", 0.2), ("min_seconds", 0.4), ("gap_seconds", 0.5),
                       ("low_seconds", 0.4), ("restrike", None), ("smooth_seconds", 0.3), ("snap", False),
                       ("ghost", 0.55)):
        cut.setdefault(key, value)
    spec.tell(0.82, "Cutting notes")
    return cut_notes(spec, act, **cut)


TRANSCRIBERS = {"mono": transcribe_mono, "peaks": transcribe_peaks, "nmf": transcribe_nmf, "pads": transcribe_pads}
DEFAULT = "nmf"


def transcribe(samples, method=DEFAULT, rate=RATE, **options):
    """Samples -> ``[(onset, offset, pitch, strength), ...]`` in seconds."""
    if method not in TRANSCRIBERS:
        raise ValueError("Unknown transcriber '%s'. Choose from: %s" % (method, ", ".join(TRANSCRIBERS)))
    spec = samples if isinstance(samples, Spectrum) else Spectrum(samples, rate)
    if not len(spec.samples) or float(abs(spec.samples).max()) < 1e-4:
        return []                                           # silence: nothing to find, and nothing to scale by
    return TRANSCRIBERS[method](spec, **options)


# ---------------------------------------------------------------------- #
# drums
# ---------------------------------------------------------------------- #
def find_drums(spec, floor=0.12):
    """Kick, snare and hi-hat from the shape of each attack. Returns ``[(seconds, "k" | "s" | "h"), ...]``.

    At every peak of the onset strength, look at what was *added* to the
    short-window spectrum.  A note adds a few narrow lines; a drum adds a broad
    smear.  A smear across the middle is called a snare, one only at the top a
    hi-hat.  A kick is a burst at the very bottom that is gone within a sixth
    of a second - a bass note would still be there.

    This is a rule of thumb fitted to simple drum sounds, not a drum
    transcriber: toms, cymbals and layered kits will be misread.
    """
    np = spec.np
    short = spec.short
    frames, bins = short.shape
    if frames < 20 or not float(short.max()) > 0:
        return []
    bin_hz = spec.rate / float(SHORT_N_FFT)
    band = lambda lo, hi: slice(max(1, int(lo / bin_hz)), min(bins, int(hi / bin_hz) + 1))      # noqa: E731
    low, mid, top = band(35, 130), band(700, 4500), band(6000, 10500)

    def flatness(v):
        v = np.maximum(v, 1e-9)                                     # noise is flat; a note is a few lines
        return float(np.exp(np.mean(np.log(v))) / np.mean(v))

    def fades(level, pf, share=0.5):
        """Is the burst mostly gone a sixth of a second later? A note would still be sounding."""
        base = float(level[max(0, pf - 3):max(1, pf - 1)].mean())
        peak = float(level[pf:pf + 4].max()) - base
        later = float(level[min(frames - 1, pf + 14):min(frames, pf + 19)].mean()) - base
        return peak > 0 and later < share * peak

    low_level = short[:, low].sum(axis=1)
    mid_level = short[:, mid].sum(axis=1)
    top_level = short[:, top].sum(axis=1)
    scale = float(np.percentile(short.sum(axis=1), 95)) or 1.0
    out = []
    for pf in analysis.peaks(np, spec.flux, floor):
        if pf + 4 >= frames:
            continue
        before = short[max(0, pf - 3):max(1, pf - 1)].mean(axis=0)
        after = short[pf:pf + 3].max(axis=0)
        rise = np.maximum(0.0, after - before)
        total = float(rise.sum())
        if total < 0.02 * scale:
            continue
        t = pf / spec.flux_fps
        mid_share, top_share = float(rise[mid].sum()) / total, float(rise[top].sum()) / total
        if flatness(rise[mid]) > 0.64 and mid_share > 0.25 and fades(mid_level, pf):
            out.append((t, "s"))
        elif flatness(rise[top]) > 0.4 and top_share > 0.1 and float(rise[top].sum()) > 0.004 * scale \
                and fades(top_level, pf):
            out.append((t, "h"))
        peak = float(low_level[pf:pf + 5].max())
        gain = peak - float(low_level[max(0, pf - 3):max(1, pf - 1)].mean())
        if gain > 0.05 * scale and gain > 0.5 * peak and fades(low_level, pf, 0.45):
            out.append((t, "k"))
    spec.kicks = [t for t, kind in out if kind == "k"]
    return sorted(out)
