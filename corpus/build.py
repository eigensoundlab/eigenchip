#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Build the test corpus: small multi-channel MIDI files with known answers.

    python corpus/build.py

Every piece is written here as note lists, so the "ground truth" (which
channel is the melody, which is the bass) is known exactly, and the files can
be regenerated bit for bit. Tunes are either in the public domain or written
for this corpus; nothing is copied from a recording or a published arrangement.
"""
import json
import os
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from eigenchip.ir import Note, Score, pitch_number      # noqa: E402
from eigenchip.midi import write_midi                   # noqa: E402

KICK, SNARE, HAT, OPEN_HAT = 36, 38, 42, 46


def part(text, channel, program=0, vel=96, start=0.0):
    """Notes from 'E4 F4:2 r:.5 [C3 E3 G3]:4 | ...' (lengths in beats, default 1)."""
    notes, t = [], Fraction(start).limit_denominator(96)
    buf, depth, tokens = "", 0, []
    for ch in text:
        depth += ch == "["
        depth -= ch == "]"
        if ch.isspace() and depth == 0:
            if buf:
                tokens.append(buf)
            buf = ""
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    for tok in tokens:
        if tok == "|":
            continue
        if tok.startswith("["):
            close = tok.rindex("]")
            body, length = tok[:close + 1], tok[close + 2:]
        else:
            body, _, length = tok.partition(":")
        dur = Fraction(length) if length else Fraction(1)
        if body != "r":
            names = body[1:-1].split() if body.startswith("[") else [body]
            for name in names:
                notes.append(Note(float(t), float(dur), pitch_number(name), vel, channel, program))
        t += dur
    return notes


def drums(pattern, bars, beats_per_bar=4):
    """pattern: {pitch: [beat positions within a bar]}"""
    notes = []
    for bar in range(bars):
        for pitch, beats in pattern.items():
            for b in beats:
                notes.append(Note(bar * beats_per_bar + b, 0.25, pitch, 100, 9, 0, drum=True))
    return notes


def ode_to_joy():
    a1 = "E4 E4 F4 G4 | G4 F4 E4 D4 | C4 C4 D4 E4 | E4:3/2 D4:1/2 D4:2"
    a2 = "E4 E4 F4 G4 | G4 F4 E4 D4 | C4 C4 D4 E4 | D4:3/2 C4:1/2 C4:2"
    b = "D4 D4 E4 C4 | D4 E4:1/2 F4:1/2 E4 C4 | D4 E4:1/2 F4:1/2 E4 D4 | C4 D4 G3:2"
    c, g = "[C3 E3 G3]", "[B2 D3 G3]"
    chords = " ".join([c + ":4", g + ":4", c + ":4", g + ":4",
                       c + ":4", g + ":4", c + ":4", g + ":2", c + ":2",
                       g + ":4", c + ":4", g + ":4", g + ":4",
                       c + ":4", g + ":4", c + ":4", g + ":2", c + ":2"])
    bass = " ".join(["C2:2 C2:2", "G2:2 G2:2", "C2:2 C2:2", "G2:2 G2:2",
                     "C2:2 C2:2", "G2:2 G2:2", "C2:2 C2:2", "G2:2 C2:2",
                     "G2:2 G2:2", "C2:2 C2:2", "G2:2 G2:2", "G2:2 G2:2",
                     "C2:2 C2:2", "G2:2 G2:2", "C2:2 C2:2", "G2:2 C2:2"])
    notes = (part(" | ".join([a1, a2, b, a2]), 0, 73) + part(chords, 1, 48, 70) + part(bass, 2, 32, 90)
             + drums({KICK: [0, 2], SNARE: [1, 3], HAT: [0, .5, 1, 1.5, 2, 2.5, 3, 3.5]}, 16))
    return Score(notes, 104, (4, 4), "Ode to Joy", {0: "melody", 1: "chords", 2: "bass", 9: "drums"})


def twinkle():
    tune = ("C4 C4 G4 G4 | A4 A4 G4:2 | F4 F4 E4 E4 | D4 D4 C4:2 | G4 G4 F4 F4 | E4 E4 D4:2 | "
            "G4 G4 F4 F4 | E4 E4 D4:2 | C4 C4 G4 G4 | A4 A4 G4:2 | F4 F4 E4 E4 | D4 D4 C4:2")
    alberti = {"C": "C3:1/2 G3:1/2 E3:1/2 G3:1/2", "F": "C3:1/2 A3:1/2 F3:1/2 A3:1/2",
               "G": "B2:1/2 G3:1/2 D3:1/2 G3:1/2"}
    harmony = "CC FC FC GC CF CG CF CG CC FC FC GC".split()
    left = " ".join(alberti[h] for bar in harmony for h in bar)
    notes = part(tune, 0, 0) + part(left, 1, 0, 72)
    return Score(notes, 96, (4, 4), "Twinkle (Alberti bass)", {0: "melody", 1: "left hand"})


def bach_prelude():
    bars = ["C4 E4 G4 C5 E5", "C4 D4 A4 D5 F5", "B3 D4 G4 D5 F5", "C4 E4 G4 C5 E5"]
    text = []
    for bar in bars:
        n = bar.split()
        figure = [n[0], n[1], n[2], n[3], n[4], n[2], n[3], n[4]]
        text.append(" ".join(x + ":1/4" for x in figure * 2))
    return Score(part(" | ".join(text), 0, 6), 72, (4, 4), "Prelude in C, opening (simplified)", {0: "keyboard"})


def frere_jacques():
    def tune(octave):
        up = lambda s: " ".join(t if t in ("|",) else                                    # noqa: E731
                                (t[0] + str(int(t[1]) + octave) + t[2:]) for t in s.split())
        return up("C4 D4 E4 C4 | C4 D4 E4 C4 | E4 F4 G4:2 | E4 F4 G4:2 | "
                  "G4:1/2 A4:1/2 G4:1/2 F4:1/2 E4 C4 | G4:1/2 A4:1/2 G4:1/2 F4:1/2 E4 C4 | "
                  "C4 G3 C4:2 | C4 G3 C4:2")
    v1 = part(tune(0) + " | " + tune(0), 0, 73)
    v2 = part(tune(1), 1, 71, 84, start=8) + part(" | ".join(tune(1).split(" | ")[:6]), 1, 71, 84, start=40)
    v3 = part(tune(-1), 2, 70, 84, start=16) + part(" | ".join(tune(-1).split(" | ")[:4]), 2, 70, 84, start=48)
    return Score(v1 + v2 + v3, 108, (4, 4), "Frere Jacques (three-part round)",
                 {0: "voice 1", 1: "voice 2", 2: "voice 3"})


def crossing():
    tune = "A4 C5 B4 A4 | E4:2 A4:2 | G4 A4 B4 C5 | B4:3 r | A4 C5 E5 D5 | C5:2 B4:2 | A4 G4 E4 G4 | A4:4"
    pad = {"Am": "[A5 C6 E6]", "F": "[A5 C6 F6]", "G": "[G5 B5 D6]", "Em": "[G5 B5 E6]"}
    pads = " ".join(pad[c] + ":4" for c in "Am F G Em Am F G Am".split())
    bass = "A2:4 F2:4 G2:4 E2:4 A2:4 F2:4 G2:4 A2:4"
    notes = part(tune, 0, 80) + part(pads, 1, 89, 64) + part(bass, 2, 33, 90)
    return Score(notes, 92, (4, 4), "Crossing (pad above the tune)", {0: "melody", 1: "high pad", 2: "bass"})


def dense_chords():
    tune = "E5:2 G5:2 | A5:3 G5 | F5:2 E5:2 | D5:4 | E5:2 C5:2 | D5:3 E5 | F5 E5 D5 B4 | C5:4"
    ch = {"C": "[C3 G3 B3 D4 E4 G4]", "Am": "[A2 E3 G3 B3 C4 E4]", "F": "[F2 C3 E3 G3 A3 C4]",
          "G": "[G2 D3 F3 A3 B3 E4]"}
    chords = " ".join([ch["C"] + ":4", ch["Am"] + ":4", ch["F"] + ":4", ch["G"] + ":4",
                       ch["C"] + ":4", ch["Am"] + ":4", ch["F"] + ":2", ch["G"] + ":2", ch["C"] + ":4"])
    bass = "C2:2 C2:2 A1:2 A1:2 F1:2 F1:2 G1:2 G1:2 C2:2 C2:2 A1:2 A1:2 F1:2 G1:2 C2:4"
    notes = part(tune, 0, 11) + part(chords, 1, 4, 66) + part(bass, 2, 32, 92)
    return Score(notes, 84, (4, 4), "Dense chords (six-note voicings)", {0: "melody", 1: "keys", 2: "bass"})


def waltz():
    tune = "G4:2 A4 | B4:2 G4 | C5:2 B4 | A4:3 | F#4:2 G4 | A4:2 F#4 | G4:3 | G4:2 r"
    pah = {"G": "r [B3 D4] [B3 D4]", "C": "r [C4 E4] [C4 E4]", "D": "r [A3 C4] [A3 C4]"}
    harmony = "G G C D D D G G".split()
    oom = {"G": "G2 r r", "C": "C3 r r", "D": "D3 r r"}
    notes = (part(tune, 0, 40) + part(" ".join(pah[h] for h in harmony), 1, 0, 64)
             + part(" ".join(oom[h] for h in harmony), 2, 32, 92))
    return Score(notes, 144, (3, 4), "Little Waltz (3/4)", {0: "melody", 1: "chords", 2: "bass"})


def triplets():
    t = lambda *names: " ".join(n + ":1/3" for n in names)       # noqa: E731
    tune = " | ".join([
        t("C5", "D5", "E5") + " " + t("G5", "E5", "D5") + " " + t("C5", "D5", "E5") + " G5",
        t("A5", "G5", "E5") + " " + t("G5", "E5", "D5") + " " + t("E5", "D5", "C5") + " D5",
        t("C5", "D5", "E5") + " " + t("G5", "E5", "D5") + " " + t("C5", "D5", "E5") + " G5",
        t("A5", "G5", "E5") + " " + t("D5", "E5", "D5") + " C5:2"])
    bass = "C3 C3 G2 G2 | F2 F2 G2 G2 | C3 C3 G2 G2 | F2 G2 C3:2"
    return Score(part(tune, 0, 73) + part(bass, 1, 32, 90), 100, (4, 4), "Triplets (off the grid)",
                 {0: "melody", 1: "bass"})


def groove():
    r1 = "E4:3/4 G4:3/4 A4:1/2 B4:1/2 r:1/2 D5:1/2 B4:1/2"
    r2 = "A4:3/4 G4:3/4 E4:1/2 D4 E4"
    r3 = "A4:3/4 G4:3/4 E4:1/2 G4:1/2 A4:1/2 B4"
    lead = " | ".join([r1, r2, r1, r3])
    bass = " | ".join(["E2:1/2 " * 8, "C2:1/2 " * 4 + "D2:1/2 " * 4, "E2:1/2 " * 8, "C2:1/2 " * 4 + "D2:1/2 " * 4])
    pad = "[E3 G3 B3]:4 [C3 E3 G3]:2 [D3 F#3 A3]:2 [E3 G3 B3]:4 [C3 E3 G3]:2 [D3 F#3 A3]:2"
    kit = drums({KICK: [0, 1.5, 2], SNARE: [1, 3], HAT: [x / 4.0 for x in range(16) if x != 14], OPEN_HAT: [3.5]}, 4)
    notes = part(lead, 0, 81) + part(bass, 1, 38, 96) + part(pad, 2, 89, 60) + kit
    return Score(notes, 110, (4, 4), "Groove (syncopation and drums)",
                 {0: "lead", 1: "bass", 2: "pad", 9: "drums"})


def deep_drone():
    pads = ("[D3 A3 F4]:8 [D3 Bb3 F4]:8 [C3 G3 E4]:8 [D3 A3 F4]:8")
    sub = "D1:8 Bb0:8 C1:8 D1:8"
    high = "r:4 A4:4 r:2 D5:6 r:4 G4:4 r:2 A4:6"
    notes = part(pads, 0, 89, 70) + part(sub, 1, 39, 100) + part(high, 2, 91, 55)
    return Score(notes, 60, (4, 4), "Deep drone (pads and sub-bass)", {0: "pad", 1: "sub", 2: "glass"})


def long_tune():
    # the texture of slow orchestral writing: the tune in long notes in the middle, a figure moving above it,
    # held chords around it and a bass below
    tune = "D4:3 E4 | F4:4 | A4:3 G4 | E4:4 | F4:3 G4 | A4:2 D5:2 | C5:3 A4 | D4:4"
    figure = {"Dm": "A5:.5 D6:.5 F6:.5 D6:.5", "Bb": "Bb5:.5 D6:.5 F6:.5 D6:.5", "F": "A5:.5 C6:.5 F6:.5 C6:.5",
              "C": "G5:.5 C6:.5 E6:.5 C6:.5", "Am": "A5:.5 C6:.5 E6:.5 C6:.5"}
    held = {"Dm": "[F3 A3]", "Bb": "[F3 Bb3]", "F": "[F3 C4]", "C": "[E3 G3]", "Am": "[E3 A3]"}
    low = {"Dm": "D2", "Bb": "Bb1", "F": "F2", "C": "C2", "Am": "A1"}
    chords = "Dm Bb F C Dm F Am Dm".split()
    notes = (part(tune, 0, 48, 100) + part(" ".join(figure[c] + " " + figure[c] for c in chords), 1, 46, 64)
             + part(" ".join(held[c] + ":4" for c in chords), 2, 89, 56) + part(" ".join(low[c] + ":4" for c in chords), 3, 43, 88))
    return Score(notes, 76, (4, 4), "Long tune (slow melody under a moving figure)",
                 {0: "melody", 1: "figure", 2: "held chords", 3: "bass"})


def octaves():
    # a tune played by two instruments an octave apart, as an orchestra doubles it, over a rocking inner part
    tune = "G4:2 A4 B4 | D5:3 B4 | C5:2 B4 A4 | G4:4 | E4:2 G4 C5 | B4:3 G4 | A4:2 F#4 D4 | G4:4"
    above = tune.replace("5", "6").replace("4", "5")
    inner = {"G": "B3:.5 D4:.5", "C": "C4:.5 E4:.5", "D": "A3:.5 D4:.5", "Em": "B3:.5 E4:.5"}
    low = {"G": "G2", "C": "C3", "D": "D2", "Em": "E2"}
    chords = "G G C G C Em D G".split()
    notes = (part(tune, 0, 48, 104) + part(above, 1, 73, 84)
             + part(" ".join(" ".join([inner[c]] * 4) for c in chords), 2, 46, 56) + part(" ".join(low[c] + ":4" for c in chords), 3, 43, 88))
    return Score(notes, 84, (4, 4), "Octaves (a tune doubled an octave above)",
                 {0: "melody", 1: "the same, an octave above", 2: "inner part", 3: "bass"})


PIECES = [
    ("ode_to_joy", ode_to_joy, {"melody": 0, "bass": 2},
     "Beethoven's theme (public domain) with block chords, bass and drums.",
     "The ordinary case: tune on top, chords in the middle, bass below."),
    ("twinkle", twinkle, {"melody": 0},
     "Traditional tune (public domain) over an Alberti bass.",
     "Two channels only; the accompaniment is a broken chord, not a bass line."),
    ("bach_prelude", bach_prelude, {},
     "Opening bars of Bach's Prelude in C, BWV 846 (public domain), simplified to plain sixteenths.",
     "One channel, no melody at all: pure arpeggio. Is the harmony recovered?"),
    ("frere_jacques", frere_jacques, {"melody": 0},
     "Traditional round (public domain) in three parts, the second part an octave above the first.",
     "Voices imitate and cross; the first voice is not the highest."),
    ("crossing", crossing, {"melody": 0, "bass": 2},
     "Written for this corpus.",
     "A sustained pad sits above the tune. Pitch-only methods take the pad for the melody."),
    ("dense_chords", dense_chords, {"melody": 0, "bass": 2},
     "Written for this corpus.",
     "Six-note chords: far more harmony than three voices can carry."),
    ("waltz", waltz, {"melody": 0, "bass": 2},
     "Written for this corpus.",
     "3/4 time, bass on the first beat only."),
    ("triplets", triplets, {"melody": 0, "bass": 1},
     "Written for this corpus.",
     "Eighth-note triplets do not fit a sixteenth-note grid."),
    ("groove", groove, {"melody": 0, "bass": 1},
     "Written for this corpus.",
     "Syncopated sixteenths, a busy bass and a drum kit."),
    ("deep_drone", deep_drone, {"bass": 1},
     "Written for this corpus.",
     "Slow pads over a sub-bass that goes down to 29 Hz. No tune, no attacks to count: a soundscape in small."),
    ("long_tune", long_tune, {"melody": 0, "bass": 3},
     "Written for this corpus.",
     "The tune moves slowly, in long notes, in the middle of the texture; the busiest and the highest part is not the tune."),
    ("octaves", octaves, {"melody": 0, "bass": 3},
     "Written for this corpus.",
     "The tune sounds in two octaves at once. Either octave is the tune; a line that hops between them is not."),
]


def build(out_dir=HERE):
    manifest = []
    for name, make, truth, source, stresses in PIECES:
        score = make()
        write_midi(os.path.join(out_dir, name + ".mid"), score)
        manifest.append({"file": name + ".mid", "title": score.title, "meter": "%d/%d" % score.meter,
                         "tempo": score.tempo, "truth": truth, "source": source, "stresses": stresses})
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return manifest


if __name__ == "__main__":
    for entry in build():
        print("%-18s %-5s %s" % (entry["file"], entry["meter"], entry["stresses"]))
