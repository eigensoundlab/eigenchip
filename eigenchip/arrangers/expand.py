# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""expand - keep the tune, write the rest anew from the harmony.

The other arrangers *reduce*: every note they play was in the source.  This one
goes the other way.  It keeps one line - the tune - and writes a bass, a chord
voice, an inner line and (from four voices up) nothing else that was heard.

It serves two cases with one method:

* **A tune and nothing else** (one melody line: a sketch, something hummed and
  transcribed).  The chords are chosen to fit the tune: a harmonisation.
* **A dense source** (a recording of an orchestra).  The transcription of the
  inner parts is the least reliable thing in the chain and, played back, the
  most disturbing.  Here every note that was heard is only *evidence* for the
  chord of each half bar; what is played is the tune and clean parts written
  from those chords.  Less faithful, far more consonant.

Method.  The key is the major scale holding most of the sound, or its relative
minor when the music rests there (where it ends, what it leans on, a raised
seventh).  Each half bar gets one chord of the key - its seven triads, and in
minor the major dominant as well - by the best path through them:

* the notes sounding in the half bar speak for a chord that contains them and
  against one that does not; the note that begins the half bar says most, a
  short note between the beats least;
* harmony likes to move at a bar line and to stay within the bar;
* chords follow each other the way they usually do (subdominant to dominant to
  tonic rather than back);
* a phrase likes to end on the dominant or the tonic, and the piece on the
  tonic, with the dominant before it: cadences.  Phrases are the parts of the
  tune when it has them (``info["phrase_starts"]``), otherwise four bars.

Bass: the root, struck again where the tune's rhythm is busy - or what the
style says, up to a walking bass that steps into every new chord.  Chords: the
triad around middle C, arpeggiated.  Inner: the chord tone next below the tune.

``STYLES`` say how the written parts move; ``MOODS`` are styles with a tempo, a
sound for the tune and a drum pattern of their own, under the names and with
the tempi, drums and lead sounds of CLIo's own composer
(``engine/audio/compose.py``), so that a mood means the same in both.

``GENRES`` go further: they also say what the chord voice *is*.  In rock, metal,
doom and industrial it is a guitar: power chords - root, fifth, octave, no third -
low down, struck in the rhythm of a riff, on a saw or a thin pulse wave through
overdrive (``"drive"``, CLIo 2.3) and a low-pass, with a bass that follows it and
drums to match.  In ambient and soundscape it is a pad: the chord held, spread
wide, with a slow attack and a long tail, over a held or droning bass, without
drums, with air around it - a track of noise that swells and fades.
"""
from __future__ import annotations

import re

from ..ir import Arrangement
from . import roles
from .common import line, map_drums, voice

NAME = "expand"
SUMMARY = "Keep the tune; write bass, chords and an inner line anew from the harmony."

SCALE = (0, 2, 4, 5, 7, 9, 11)
TRIADS = [(SCALE[i], SCALE[(i + 2) % 7], SCALE[(i + 4) % 7]) for i in range(7)]     # I ii iii IV V vi vii
# The chords of a key as (triad, how readily it is taken, what it does: Tonic, Subdominant, Dominant), counted from
# the tonic of the *major* scale; the minor key is the relative one, with the major dominant added.
MAJOR = list(zip(TRIADS, (1.0, 0.9, 0.85, 1.0, 1.0, 0.95, 0.6), "TSTSDTD"))
MINOR = list(zip(TRIADS, (0.95, 0.9, 0.85, 1.0, 0.9, 1.0, 0.6), "TSDSDTS")) + [((4, 8, 11), 0.95, "D")]
AGAINST = 0.6           # what a note outside the chord takes away, against what a note inside it gives
TUNE = 2.0              # the tune's notes weigh this much more than the others as evidence
FIRST = 1.5             # a note that begins the half bar says more about its chord
PASSING = 0.5           # a short note between the beats says less
CHANGE = 0.2            # cost of changing chord within the bar, as a share of a window's full weight
AT_BAR = 0.04           # ... and at a bar line, where harmony likes to move
STAY = 0.04             # cost of keeping the chord over a bar line
FLOW = 0.05             # what a usual succession (S to D, D to T) gains, and what going back from D to S costs
_FLOW = {"DT": 1.0, "SD": 1.0, "TS": 0.5, "TD": 0.5, "DS": -1.0}
CADENCE = 0.1           # what the tonic or the dominant gain at the end of a phrase
PHRASE = 4              # bars in a phrase when the tune does not say where its parts begin
# How much each step above the tonic belongs to a major and to a minor key, as listeners rate it (Krumhansl and
# Kessler, 1982): the tonic most, then the fifth and the third, the steps outside the scale least.
# The other modes of a scale: the step of the major scale they rest on.  They are never *found* - a tune in C major
# that leans on its e would be taken for E phrygian - but they can be asked for (``parse_key``): the chords are then
# the same seven, with another one for home, and its neighbours a step above and below leading into it (F to Em in
# E phrygian, D or F to Em... in dorian the major chord on the fourth step).
MODES = {"dorian": 1, "phrygian": 2, "lydian": 3, "mixolydian": 4, "locrian": 6}
# The chord that makes each mode sound like itself, as steps of the scale above its home chord: the major chord on
# the fourth step in dorian, the one a half step above home in phrygian and locrian, a whole step above in lydian,
# a whole step below in mixolydian.
OWN_CHORD = {"dorian": 3, "phrygian": 1, "lydian": 1, "mixolydian": 6, "locrian": 1}
PROFILE = {False: (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88),
           True: (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)}
ENDS_ON = 0.1           # what a key gains when the music ends on its tonic (half of it when it begins there)
NO_TRIAD = 0.15         # what a key loses for each note of its own triad that is never heard
MAJOR_FIRST = 0.02      # with nothing to choose between them, a key is major
SAME_SCALE = 0.02       # two scales that hold the sound this nearly alike count as holding it equally
SEVENTH_FREE = 1.0      # how much of the weight of that seventh is forgiven
SEVENTH = 5             # the scale step (as a pitch class above the major tonic) that the dominant takes as its seventh


def key_tonic(notes):
    """The tonic (0-11) of the major scale that holds most of the sound, by length and loudness."""
    weight = [0.0] * 12
    for n in notes:
        weight[n.pitch % 12] += n.dur * (0.5 + n.vel / 254.0)
    return max(range(12), key=lambda t: sum(weight[(t + s) % 12] for s in SCALE))


def key_of(notes):
    """``(home, minor)``: the tonic of the major scale holding most of the sound, and whether the music rests on
    that scale's sixth step instead - the relative minor, whose tonic is then ``(home + 9) % 12``.

    A tune often leaves out a step of its scale, and then two scales hold it equally well; of the scales that hold
    the sound about as well as the best one, and of the major and the minor key of each, the key is taken whose
    steps the sound weighs as listeners do (``PROFILE``), with a word for where the music ends and begins, and
    against a key whose own tonic, third or fifth is never heard."""
    weight = [0.0] * 12
    for n in notes:
        weight[n.pitch % 12] += n.dur * (0.5 + n.vel / 254.0)
    full = sum(weight) or 1.0
    close, open_ = max(n.end for n in notes), min(n.start for n in notes)
    last = min((n for n in notes if n.end >= close - 1), key=lambda n: n.pitch).pitch % 12
    first = min((n for n in notes if n.start <= open_), key=lambda n: n.pitch).pitch % 12

    def rests_on(tonic, minor):
        profile = PROFILE[minor]
        rest = sum(weight[(tonic + i) % 12] * profile[i] for i in range(12)) / full / profile[0]
        for pc, worth in ((last, ENDS_ON), (first, ENDS_ON / 2)):   # where it ends says most; where it begins, less
            rest += worth * (pc == tonic) + 0.4 * worth * (pc == (tonic + 7) % 12)
        return rest - NO_TRIAD * sum(1 for step in (0, 3 if minor else 4, 7) if not weight[(tonic + step) % 12])

    held = [sum(weight[(t + s) % 12] for s in SCALE) / full for t in range(12)]
    found = []
    for home in range(12):
        if held[home] >= max(held) - SAME_SCALE:
            found.append((rests_on(home, False) + MAJOR_FIRST, -home, 1, home, False))
            found.append((rests_on((home + 9) % 12, True), -home, 0, home, True))
    return max(found)[3:]


def parse_key(text):
    """'C', 'C major', 'Am', 'a minor', 'F#m', 'E phrygian', 'D dorian' -> ``(home, mode)``; None for nothing.

    ``home`` is the tonic of the major scale with the same notes, as ``key_of`` gives it; ``mode`` is False for
    major, True for minor, or the name of one of ``MODES``."""
    text = (text or "").strip()
    if not text or text.lower() in ("-", "?", "found", "auto"):
        return None
    found = re.match(r"^([A-Ga-g])([#b]?)\s*([A-Za-z]*)$", text)
    kind = found.group(3).lower() if found else None
    if kind in ("m", "min", "minor", "aeolian"):
        mode, step = True, 9
    elif kind in ("", "maj", "major", "ionian"):
        mode, step = False, 0
    elif kind in MODES:
        mode, step = kind, SCALE[MODES[kind]]
    else:
        raise ValueError("'%s' is not a key I know. Write C, G major, Am, F# minor, or a mode as in E phrygian: %s."
                         % (text, ", ".join(MODES)))
    tonic = ("C D EF G A B".index(found.group(1).upper()) + {"#": 1, "b": -1, "": 0}[found.group(2)]) % 12
    return (tonic - step) % 12, mode


def degree_of(mode):
    """The step of the major scale (0 to 6) a key rests on: 0 for major, 5 for minor, as ``MODES`` for the others."""
    return 5 if mode is True else MODES.get(mode, 0) if mode else 0


def chords(notes, tune, total, window, tonic, minor=False, bar=None, phrases=None, beat=None):
    """One triad (as three pitch classes, root first) per window: the best path through the chords of the key.

    ``tonic`` is the tonic of the major scale (``key_of``), ``minor`` says the key is its relative minor - or
    names another mode of that scale (``MODES``).  ``bar``
    and ``beat`` are in steps; ``phrases`` are the steps at which a phrase begins (every ``PHRASE`` bars if none).
    """
    lead = {id(n) for n in tune}
    bar = bar or 2 * window
    beat = beat or max(1, bar // 4)
    count = max(1, -(-total // window))
    mode, minor = minor, minor is True
    home = degree_of(mode)                                  # which of the chords is the tonic chord
    key = MINOR if minor else MAJOR
    if mode and not minor:                                  # a mode: its own chord is home, its neighbours lead there
        own = (home + OWN_CHORD[mode]) % 7
        key = [(triad, 1.0 if i == home else 0.97 if i == own else 0.6 if i == 6 else 0.9,
                "T" if i == home else "D" if abs(i - home) in (1, 6) else "S") for i, triad in enumerate(TRIADS)]
    if minor:                                               # the major dominant needs its raised seventh to be heard,
        sharp = sum(n.dur for n in notes if n.pitch % 12 == (tonic + 8) % 12)       # or at least not contradicted
        plain = sum(n.dur for n in notes if n.pitch % 12 == (tonic + 7) % 12)
        key = key[:-1] + [(key[-1][0], 0.95 if sharp else 0.5 if plain else 0.85, "D")]
    size = len(key)
    sevenths = {4: (tonic + SEVENTH) % 12, 7: (tonic + 2) % 12}     # V of the major key, V of the minor one
    begins = {int(p) // window for p in (phrases or range(0, total, PHRASE * bar))}
    fit, sounding = [], []
    for w in range(count):
        a, b = w * window, (w + 1) * window
        heard = [0.0] * 12
        for n in notes:
            over = min(n.end, b) - max(n.start, a)
            if over > 0:
                said = FIRST if n.start <= a else PASSING if n.start % beat and n.dur < beat else 1.0
                heard[n.pitch % 12] += over * (0.5 + n.vel / 254.0) * (TUNE if id(n) in lead else 1.0) * said
        full = sum(heard) or 1.0
        row = []
        for i, (triad, likely, _does) in enumerate(key):
            pcs = {(tonic + p) % 12 for p in triad}
            inside = sum(heard[pc] for pc in pcs)
            outside = sum(heard) - inside
            if i in sevenths and (i == 7 or mode is False): # the dominant may carry its seventh: an f does not speak
                outside -= SEVENTH_FREE * heard[sevenths[i]]    # against G as it does against the others
            row.append(likely * (inside - AGAINST * outside) / full)
        fit.append(row if sum(heard) > 0 else None)
        if sum(heard) > 0:
            sounding.append(w)
    for w in sounding:                                      # cadences: how phrases and the piece come to rest
        ends_phrase = (w + 1) in begins or w == sounding[-1]
        for i, (_triad, _likely, does) in enumerate(key):
            if w == sounding[-1]:
                fit[w][i] += 2 * CADENCE * (i == home)
            elif ends_phrase:
                fit[w][i] += CADENCE * (i == home or does == "D")
            elif w + 1 == sounding[-1]:
                fit[w][i] += CADENCE * (does == "D")
            elif w == sounding[0]:
                fit[w][i] += CADENCE * (i == home)

    def move(j, i, w):
        """What going from chord ``j`` to chord ``i`` at window ``w`` costs."""
        at_bar = (w * window) % bar == 0
        if i == j:
            return STAY if at_bar else 0.0
        return (AT_BAR if at_bar else CHANGE) - FLOW * _FLOW.get(key[j][2] + key[i][2], 0.0)

    best, back, begun = [0.0] * size, [], False
    for w, row in enumerate(fit):                           # the best path: Viterbi over the chords of the key
        if row is None:
            back.append(list(range(size)))                  # silence: the chord stays what it was
            continue
        if not begun:
            best, begun = list(row), True
            back.append(list(range(size)))
            continue
        came = [max(range(size), key=lambda j: best[j] - move(j, i, w)) for i in range(size)]
        best = [best[came[i]] - move(came[i], i, w) + row[i] for i in range(size)]
        back.append(came)
    at = max(range(size), key=best.__getitem__)
    path = []
    for came in reversed(back):
        path.append(at)
        at = came[at]
    path.reverse()
    return [tuple((tonic + p) % 12 for p in key[d][0]) for d in path]


NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
KINDS = {"": (4, 7), "m": (3, 7), "dim": (3, 6), "7": (4, 7, 10), "m7": (3, 7, 10), "maj7": (4, 7, 11)}
_CHORD = re.compile(r"^([A-Ga-g])([#b]?)(maj7|m7|dim|m|7)?$")

# How the written parts move.  ``bass``: held / beats (root and fifth by beats) / eighths / bar (once a bar).
# ``arp``: steps per note of the chord voice.  ``drums``: one bar of sixteen steps, used in four-four; other meters
# get a kick on the first beat and a hat on the others.
STYLES = {
    "plain": {"about": "Held bass, rolling chords, no drums.", "bass": "held", "arp": 1, "drums": ""},
    "ballad": {"about": "Long bass, slow chords, a quiet hat.", "bass": "held", "arp": 2, "drums": "....h.......h..."},
    "march": {"about": "Bass on every beat, root and fifth; snare on two and four.", "bass": "beats", "arp": 2,
              "drums": "k...s...k...s..."},
    "drive": {"about": "Bass in eighths, busy hats.", "bass": "eighths", "arp": 1, "drums": "k.h.s.h.k.hks.h."},
    "waltz": {"about": "Bass once a bar, the chord on every beat.", "bass": "bar", "arp": 4, "drums": ""},
    "walk": {"about": "A walking bass: a step on every beat, into each new chord.", "bass": "walk", "arp": 2,
             "drums": "....h.......h.h."},
}

# Moods: a style, and with it a tempo, the sound of the tune and the drums.  Names, tempo (the middle of the
# composer's range), drums and lead wave are those of CLIo's composer; ``bass`` and ``arp`` are chosen here to suit.
_KITS = {"none": "", "soft": "k...h...k...h.h.", "sparse": "k...........t...", "drive": "k.h.s.hkk.h.s.hh",
         "march": "k.h.s.h.kkh.s.sh"}
MOODS = {
    "calm": {"about": "Unhurried and warm.", "bass": "held", "arp": 2, "kit": "soft", "lead": "triangle", "tempo": 80},
    "mystery": {"about": "Sparse, something is hidden.", "bass": "bar", "arp": 2, "kit": "sparse", "lead": "soft",
                "tempo": 84},
    "dark": {"about": "Slow and heavy.", "bass": "held", "arp": 4, "kit": "sparse", "lead": "square", "tempo": 75},
    "tense": {"about": "Something is about to happen.", "bass": "eighths", "arp": 1, "kit": "drive", "lead": "square",
              "tempo": 114},
    "battle": {"about": "Fast, driving, no rest.", "bass": "eighths", "arp": 1, "kit": "drive", "lead": "square",
               "tempo": 142},
    "heroic": {"about": "A march with its head up.", "bass": "beats", "arp": 2, "kit": "march", "lead": "square",
               "tempo": 117},
    "shop": {"about": "Friendly, strolling along.", "bass": "walk", "arp": 2, "kit": "soft", "lead": "triangle",
             "tempo": 108},
    "space": {"about": "Wide and still, no drums.", "bass": "held", "arp": 4, "kit": "none", "lead": "soft",
              "tempo": 72},
    "victory": {"about": "Bright and quick, a fanfare.", "bass": "beats", "arp": 1, "kit": "march", "lead": "square",
                "tempo": 124},
    "defeat": {"about": "Slow, low, it is over.", "bass": "bar", "arp": 4, "kit": "none", "lead": "triangle",
               "tempo": 66},
}
for _mood in MOODS.values():
    _mood["drums"] = _KITS[_mood["kit"]]


# Genres.  ``chords``: ``power`` (root, fifth and octave from ``low`` up, struck as ``riff`` says) or ``pad`` (the
# chord held and spread wide); without it the chord voice is the arpeggio of the styles.  ``riff``: one or two bars
# of sixteen steps - ``x`` strikes, ``-`` lets it ring, ``.`` is silent.  ``bass``: as in the styles, or ``chug``
# (the root wherever the guitar strikes), ``long`` (the root for as long as the chord lasts) or ``pedal`` (the
# tonic of the key, whatever the chord).  ``sound``: what
# each voice is played with, laid over the usual instrument (``None`` takes a setting away); ``kit_sound`` the same
# for the drums.  The volumes are set so that the tune stays in front: overdrive makes a track much louder.  ``air``: the levels (0 to 9) between which a bed of noise swells and fades, two bars at a time.
# ``steam``: a falling hiss on the last beat of every second bar.  ``crash``: an open hat where a phrase begins.
_GUITAR = {"wave": "saw", "arp": None, "attack": 0.004, "decay": 0.12, "sustain": 0.75, "release": 0.06}
_SOLO = {"wave": "saw", "duty": None, "attack": 0.01, "decay": 0.1, "sustain": 0.8, "release": 0.12}
_PAD = {"arp": None, "gate": 1.0, "decay": 0.3, "sustain": 0.85}
GENRES = {
    "rock": {
        "about": "Power chords in eighths, a backbeat, a lead with some bite.", "tempo": 126,
        "chords": "power", "low": 40, "riff": "x-x-x-x-x-x-x-x-", "bass": "eighths", "arp": 1,
        "drums": "k.h.s.h.k.k.s.h.", "crash": True,
        "sound": {"chords": dict(_GUITAR, drive=0.55, lowpass=0.45, gate=0.85, volume=0.14),
                  "lead": dict(_SOLO, drive=0.4, lowpass=0.3, vibrato=[5.5, 0.006], volume=0.235),
                  "inner": {"wave": "square", "duty": 0.5, "volume": 0.1},
                  "bass": {"volume": 0.4}},
        "kit_sound": {"volume": 0.7}},
    "metal": {
        "about": "A galloping riff, hard overdrive, two kicks to the beat.", "tempo": 150,
        "chords": "power", "low": 40, "riff": "x-xxx-xxx-xxx-xx", "bass": "chug", "arp": 1,
        "drums": "khkkshkkkhkkshkk", "crash": True,
        "sound": {"chords": dict(_GUITAR, drive=0.9, lowpass=0.4, gate=0.75, sustain=0.6, volume=0.13),
                  "lead": dict(_SOLO, drive=0.6, lowpass=0.25, vibrato=[6, 0.007], volume=0.21),
                  "inner": dict(_SOLO, drive=0.4, lowpass=0.3, volume=0.06),
                  "bass": {"wave": "saw", "drive": 0.4, "lowpass": 0.6, "gate": 0.8, "volume": 0.17}},
        "kit_sound": {"volume": 0.5}},
    "doom": {
        "about": "Slow and very heavy: low chords left to ring, a drum now and then.", "tempo": 60,
        "chords": "power", "low": 36, "riff": "x---------------x-------x-----x-", "bass": "chug", "arp": 1,
        "drums": "k...h...s...h.k.", "crash": True,
        "sound": {"chords": dict(_GUITAR, drive=1.0, lowpass=0.55, gate=1.0, sustain=0.9, release=0.25, volume=0.09),
                  "lead": dict(_SOLO, wave="soft", drive=0.3, lowpass=0.3, vibrato=[4.5, 0.006], release=0.4,
                               echo=[0.375, 0.3], volume=0.165),
                  "inner": {"wave": "soft", "release": 0.3, "volume": 0.1},
                  "bass": {"wave": "saw", "drive": 0.5, "lowpass": 0.7, "gate": 1.0, "sustain": 0.9, "volume": 0.14}},
        "kit_sound": {"volume": 0.8}},
    "industrial": {
        "about": "A machine: clipped chords in sixteenths, a hammering kit, steam.", "tempo": 104,
        "chords": "power", "low": 38, "riff": "xx.x.xx.xx.x.xx.", "bass": "eighths", "arp": 1,
        "drums": "k.hhc.hhk.khc.hh", "steam": True,
        "sound": {"chords": dict(_GUITAR, wave="square", duty=0.125, drive=1.0, lowpass=0.3, gate=0.6, sustain=0.5,
                                 volume=0.14),
                  "lead": dict(_SOLO, drive=0.7, lowpass=0.2, volume=0.22),
                  "inner": {"wave": "square", "duty": 0.125, "volume": 0.09},
                  "bass": {"wave": "saw", "drive": 0.6, "lowpass": 0.65, "gate": 0.7, "volume": 0.22}},
        "kit_sound": {"drive": 0.6, "volume": 0.37}},
    "ambient": {
        "about": "Soft chords held wide, a bass that takes its time, air, no drums.", "tempo": 66,
        "chords": "pad", "bass": "long", "arp": 1, "drums": "", "air": (1, 4),
        "sound": {"chords": dict(_PAD, wave="soft", attack=0.5, release=1.2, lowpass=0.5, echo=[0.4, 0.3], volume=0.13),
                  "lead": {"wave": "soft", "duty": None, "attack": 0.06, "sustain": 0.7, "release": 0.6,
                           "vibrato": [4.5, 0.004], "echo": [0.45, 0.35], "volume": 0.24},
                  "inner": {"wave": "sine", "attack": 0.1, "release": 0.6, "volume": 0.12},
                  "bass": {"wave": "triangle", "attack": 0.25, "sustain": 0.9, "release": 0.8, "gate": 1.0,
                           "volume": 0.3}}},
    "soundscape": {
        "about": "A drone under everything, slow swells of noise, the tune far away.", "tempo": 60,
        "chords": "pad", "bass": "pedal", "arp": 1, "drums": "", "air": (3, 7), "inner": False,
        "sound": {"chords": dict(_PAD, wave="sine", attack=1.0, release=2.0, echo=[0.6, 0.4], volume=0.15),
                  "lead": {"wave": "sine", "duty": None, "attack": 0.12, "sustain": 0.7, "release": 0.9,
                           "vibrato": [4, 0.004], "echo": [0.5, 0.45], "volume": 0.2},
                  "bass": {"wave": "triangle", "attack": 0.8, "sustain": 1.0, "release": 1.5, "gate": 1.0,
                           "lowpass": 0.5, "volume": 0.3}}},
}
AIR = {"wave": "noise", "attack": 0.6, "decay": 0.05, "sustain": 1.0, "release": 0.8, "gate": 1.0, "lowpass": 0.35,
       "volume": 0.22}
STEAM = {"wave": "noise", "attack": 0.005, "decay": 0.05, "sustain": 1.0, "release": 0.05, "gate": 1.0, "volume": 0.35}


def way(style):
    """How the parts move for a style, a genre or a mood, by name."""
    how = STYLES.get(style) or GENRES.get(style) or MOODS.get(style)
    if how is None:
        raise ValueError("Unknown style '%s'. Styles: %s. Genres: %s. Moods: %s."
                         % (style, ", ".join(STYLES), ", ".join(GENRES), ", ".join(MOODS)))
    return how


def _strikes(riff, start, end, bar, beat):
    """Where a riff strikes between ``start`` and ``end``, as ``(step, steps)``: a chord that begins is always
    struck, whatever the riff says there.  In a meter that is not four-four the riff is a strike on every beat."""
    def sign(s):
        return riff[s % len(riff)] if bar == 16 else ("x" if s % beat == 0 else "-")
    out = []
    for s in range(start, end):
        c = "x" if s == start and sign(s) == "-" else sign(s)
        if c == "x":
            out.append([s, 1])
        elif c == "-" and out and out[-1][0] + out[-1][1] == s:
            out[-1][1] += 1
    return [tuple(o) for o in out]


def _voiced(chord, how):
    """The pitches the chord voice plays for a chord (pitch classes, root first), as the style has it."""
    if how.get("chords") == "power":                        # root, fifth, octave: no third to be major or minor
        root = _place(chord[0], how.get("low", 40))
        return [root, _place(chord[2], root), root + 12]
    if how.get("chords") == "pad":                          # spread wide: root, fifth, and the third above them
        root = _place(chord[0], 48)
        high = [_place(pc, root + 12) for pc in chord[1:2] + chord[3:]]
        return sorted([root, _place(chord[2], root)] + high)
    return sorted(_place(pc, 55) for pc in chord)           # close, around middle C: for an arpeggio


def chord_name(chord):
    """('C', 'E', 'G' as pitch classes, root first) -> 'C'."""
    shape = tuple(sorted((pc - chord[0]) % 12 for pc in chord[1:]))
    kind = next((k for k, v in KINDS.items() if v == shape), "")
    return NAMES[chord[0]] + kind


def parse_chord(name):
    """'Am' -> pitch classes, root first; None for '-' or nothing (leave it to the arranger)."""
    name = (name or "").strip()
    if name in ("", "-", "?"):
        return None
    found = _CHORD.match(name)
    if not found:
        raise ValueError("'%s' is not a chord I know. Write C, Am, G7, Dm7, Fmaj7 or Bdim; '-' to leave one to me." % name)
    root = ("C D EF G A B".index(found.group(1).upper()) + {"#": 1, "b": -1, "": 0}[found.group(2)]) % 12
    return (root,) + tuple((root + step) % 12 for step in KINDS[found.group(3) or ""])


def parse_chords(text, per_bar=2):
    """'C | G | Am F | -' -> one entry per half bar (None where the arranger is to choose)."""
    out = []
    for bar in (text or "").split("|"):
        names = bar.split()
        if len(names) > per_bar:
            raise ValueError("'%s': at most %d chords in a bar." % (bar.strip(), per_bar))
        chosen = [parse_chord(n) for n in names] or [None]
        out += chosen if len(chosen) == per_bar else chosen * per_bar
    return out


def chords_text(path, per_bar=2):
    bars = []
    for i in range(0, len(path), per_bar):
        names = [chord_name(c) for c in path[i:i + per_bar]]
        bars.append(names[0] if len(set(names)) == 1 else " ".join(names))
    return " | ".join(bars)


def _place(pc, low):
    """The pitch of class ``pc`` at or above ``low``."""
    return low + (pc - low) % 12


def _walk(runs, beat, scale):
    """A walking bass over ``runs`` of ``(start, steps, chord)``: the root where a chord begins, then up through the
    chord, and on the last beat before a new chord the note of the scale next to its root - a step into it."""
    out = []
    for r, (start, steps, chord) in enumerate(runs):
        root = _place(chord[0], 36)
        tones = [root, _place(chord[1], root), _place(chord[2], root)]
        after = _place(runs[r + 1][2][0], 36) if r + 1 < len(runs) else None
        beats = list(range(start, start + steps, beat))
        for k, s in enumerate(beats):
            pitch = tones[(0, 1, 2, 1)[k % 4]]
            if k and k == len(beats) - 1 and after is not None and after != root:
                step = -1 if after > out[-1][2][0] else 1          # from below when the line is going up
                pitch = after + step
                while pitch % 12 not in scale:
                    pitch += step
            out.append((s, min(beat, start + steps - s), [pitch]))
    return out


def arrange(grid, voices=4, style="plain", chords_given=None, ending=False, key=None):
    """``style`` is one of ``STYLES`` or ``MOODS``; ``chords_given`` as ``parse_chords`` returns them, to overrule
    the choice; with ``ending`` a closing bar on the tonic is written after the last one, and the song does not loop;
    ``key`` as ``parse_key`` returns it, when the key found is not the one meant - or a mode is: E phrygian."""
    how = way(style)
    notes = grid.pitched
    if not notes:
        return Arrangement([], map_drums(grid.drums), NAME, {})
    parts = roles._split(grid)
    if parts is None:                                       # one line: it is the tune
        tune_events, used = line(notes, top=True)
        remarks = {"tune": "the only line"}
    else:
        tune_events, _bass, _rest, remarks = parts
        used = [n for n in notes if n.channel == remarks.get("lead_channel")]
    total = grid.length
    window = max(1, grid.steps_per_bar // 2)
    tonic, mode = key or key_of(notes)
    minor = mode is True
    spb = grid.steps_per_beat
    phrases = [int(round(b * spb)) for b in grid.info.get("phrase_starts") or []] or None
    path = chords(notes, used, total, window, tonic, mode, grid.steps_per_bar, phrases, spb)
    for i, given in enumerate(chords_given or []):
        if given and i < len(path):
            path[i] = tuple(given)
    key_note = (tonic + SCALE[degree_of(mode)]) % 12
    remarks.update(tonic=tonic, minor=minor, key="%s %s" % (NAMES[key_note], "minor" if minor else mode or "major"),
                   chords=len({c for c in path}), written="bass, chords and inner line are new",
                   style=style, chords_text=chords_text(path))

    def runs():
        """(start, steps, chord) with the same chord in neighbouring windows put together, bar by bar."""
        out = []
        for w, chord in enumerate(path):
            start = w * window
            if out and out[-1][2] == chord and start % grid.steps_per_bar != 0:
                out[-1] = (out[-1][0], out[-1][1] + window, chord)
            else:
                out.append((start, min(window, total - start), chord))
        return [r for r in out if r[1] > 0]

    busy = len(tune_events) / max(1.0, total / float(grid.steps_per_beat)) >= 0.75      # tune notes per beat
    beat, bar = grid.steps_per_beat, grid.steps_per_bar
    bass, harmony = [], []
    riff = how.get("riff") or "x---------------"
    if how["bass"] == "walk":
        bass = _walk(runs(), beat, {(tonic + s) % 12 for s in SCALE})
    elif how["bass"] == "pedal":                            # the tonic, whatever the chord: a drone, struck every two bars
        bass = [(s, min(2 * bar, total - s), [_place(key_note, 36)]) for s in range(0, total, 2 * bar)]
    for start, steps, chord in runs():
        root, fifth = _place(chord[0], 36), _place(chord[2], 36)                        # C2 and up
        end = start + steps
        if how["bass"] in ("walk", "pedal"):
            pass
        elif how["bass"] == "chug":                         # with the guitar, an octave below it
            low = max(28, _voiced(chord, how)[0] - 12)
            bass += [(s, d, [low]) for s, d in _strikes(riff, start, end, bar, beat)]
        elif how["bass"] == "long":                         # the root for as long as the chord lasts
            bass.append((start, steps, [root]))
        elif how["bass"] == "beats":                        # root and fifth, beat by beat
            for k, s in enumerate(range(start, end, beat)):
                bass.append((s, min(beat, end - s), [fifth if k % 2 else root]))
        elif how["bass"] == "eighths":                      # the root in eighths, every other one an octave up
            half = max(1, beat // 2)
            for k, s in enumerate(range(start, end, half)):
                bass.append((s, min(half, end - s), [root + 12 if k % 4 == 3 else root]))
        elif how["bass"] == "bar":                          # once a bar, and let it ring
            for s in range(start, end, bar):
                bass.append((s, min(bar, end - s), [root]))
        elif busy and steps >= window:                      # held, but a moving tune has the bass mark every half bar
            for s in range(start, end, window):
                bass.append((s, min(window, end - s), [fifth if s != start and (s // window) % 2 == 1 else root]))
        else:
            bass.append((start, steps, [root]))
        if how.get("chords") == "power":
            harmony += [(s, d, _voiced(chord, how)) for s, d in _strikes(riff, start, end, bar, beat)]
        else:
            harmony.append((start, steps, _voiced(chord, how)))
    inner = []
    for start, steps, pitches in tune_events:               # the chord tone next below the tune, a third or more away
        chord = path[min(len(path) - 1, start // window)]
        under = max((p for p in (_place(pc, pitches[0] - 12) for pc in chord) if p <= pitches[0] - 3),
                    default=None)
        if under is not None and under >= 48 and how.get("inner", True):
            inner.append((start, steps, [under]))
    drums = map_drums(grid.drums)
    if not drums and how["drums"]:                          # the source had none: the style's own
        pattern = how["drums"] if bar == 16 else "".join(
            ("k" if s == 0 else "h" if s % beat == 0 else ".") for s in range(bar))
        drums = [(s, [pattern[s % len(pattern)]]) for s in range(total) if pattern[s % len(pattern)] != "."]
        if how.get("crash"):                                # where a phrase begins
            for s in (phrases or range(0, total, PHRASE * bar)):
                drums = [(at, hits + ["o"] if at == s else hits) for at, hits in drums]
                if not any(at == s for at, _hits in drums):
                    drums.append((s, ["o"]))
            drums.sort()
    tracks = {}
    if how.get("air"):                                      # a bed of noise that swells and fades, two bars at a time
        low, high = how["air"]
        air = []
        for s in range(0, total, 2 * bar):
            for a, b, bend in ((s, s + bar, ((60.0, 70.0), (low, high))), (s + bar, s + 2 * bar, ((70.0, 60.0), (high, low)))):
                if a < total:
                    air.append((a, min(b, total) - a, [int(bend[0][0])], bend))
        tracks["air"] = (air, dict(AIR))
    if how.get("steam"):                                    # a hiss that falls, on the last beat of every second bar
        tracks["steam"] = ([(s - beat, beat, [86], ((86.0, 54.0), (6, 1))) for s in range(2 * bar, total + 1, 2 * bar)],
                           dict(STEAM))
    if ending:                                              # one more bar: everything comes to rest on the tonic
        close = -(-total // bar) * bar
        home = tuple((tonic + p) % 12 for p in TRIADS[degree_of(mode)])
        last = tune_events[-1]
        if last[2][0] % 12 != key_note or last[1] < window:  # the tune did not come home by itself
            tune_events = list(tune_events) + [(close, bar, [min((_place(key_note, last[2][0] - 6),), key=abs)])]
        low = max(28, _voiced(home, how)[0] - 12) if how["bass"] == "chug" else _place(key_note, 36)
        bass.append((close, bar, [low]))
        harmony.append((close, bar, _voiced(home, how)))
        if drums:
            drums.append((close, ["k", "o"]))
        remarks["ending"] = True
    out = [voice("lead", tune_events)]
    if how.get("lead"):                                     # a mood has its own sound for the tune
        sound = dict(out[0].instrument, wave=how["lead"])
        if how["lead"] != "square":
            sound.pop("duty", None)
        out[0].instrument = sound
    if voices >= 2:
        out.append(voice("bass", bass))
    if voices >= 3:
        rolling = voice("chords", harmony)
        rolling.instrument = dict(rolling.instrument, arp=how["arp"])
        out.append(rolling)
    if voices >= 4 and inner:
        out.insert(2, voice("inner", inner))
    for v in out:                                           # a genre has its own sound for every voice
        over = (how.get("sound") or {}).get(v.role)
        if over:
            v.instrument = {k: val for k, val in dict(v.instrument, **over).items() if val is not None}
    if how.get("kit_sound"):
        remarks["kit"] = dict(how["kit_sound"])
    return Arrangement(out, drums, NAME, remarks, tracks)
