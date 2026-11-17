# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "corpus"))
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import build as corpus_build                                    # noqa: E402
import run as experiment                                        # noqa: E402
from eigenchip import cli, metrics                              # noqa: E402
from eigenchip.arrangers import ARRANGERS, arrange              # noqa: E402
from eigenchip.ir import Note, Score, pitch_name, pitch_number, quantize    # noqa: E402
from eigenchip.midi import MidiError, read_midi, write_midi     # noqa: E402
from eigenchip.readers import read                              # noqa: E402
from eigenchip.writers import clio                              # noqa: E402

CORPUS = os.path.join(ROOT, "corpus")


def grid_of(name):
    return quantize(read(os.path.join(CORPUS, name + ".mid")))


def manifest():
    with open(os.path.join(CORPUS, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


class PitchTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(pitch_name(60), "c4")
        self.assertEqual(pitch_name(69), "a4")
        self.assertEqual(pitch_number("c4"), 60)
        self.assertEqual(pitch_number("Eb3"), pitch_number("d#3"))
        for n in range(24, 100):
            self.assertEqual(pitch_number(pitch_name(n)), n)


class MidiTests(unittest.TestCase):
    def test_round_trip(self):
        notes = [Note(0, 1, 60, 90, 0, 5), Note(0.5, 0.25, 64, 80, 1, 40), Note(1, 2, 36, 100, 9, 0, drum=True),
                 Note(1 / 3.0, 1 / 3.0, 67, 70, 0, 5)]
        score = Score(notes, 97, (3, 4), "Round trip", {0: "tune", 1: "other"})
        path = os.path.join(tempfile.mkdtemp(), "t.mid")
        write_midi(path, score)
        back = read_midi(path)
        self.assertAlmostEqual(back.tempo, 97, places=1)
        self.assertEqual(back.meter, (3, 4))
        self.assertEqual(back.title, "Round trip")
        self.assertEqual(back.names[0], "tune")
        self.assertEqual(sorted((round(n.start, 3), round(n.dur, 3), n.pitch, n.channel, n.drum) for n in back.notes),
                         sorted((round(n.start, 3), round(n.dur, 3), n.pitch, n.channel, n.drum) for n in notes))
        self.assertEqual([n.program for n in back.notes if n.channel == 1], [40])

    def test_running_status_and_velocity_zero_note_off(self):
        # format 0, 96 ticks per beat: two notes sent with running status, ended by "note on, velocity 0"
        track = bytes([0x00, 0x90, 60, 100,      # note on C4
                       0x60, 60, 0,              # 96 ticks later: running status, velocity 0 = off
                       0x00, 64, 90,             # note on E4 (still running status)
                       0x30, 64, 0,              # 48 ticks later: off
                       0x00, 0xFF, 0x2F, 0x00])
        data = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 96) + b"MTrk" + struct.pack(">I", len(track)) + track
        path = os.path.join(tempfile.mkdtemp(), "r.mid")
        with open(path, "wb") as f:
            f.write(data)
        notes = read_midi(path).notes
        self.assertEqual([(n.start, n.dur, n.pitch) for n in notes], [(0.0, 1.0, 60), (1.0, 0.5, 64)])

    def test_rejects_other_files(self):
        path = os.path.join(tempfile.mkdtemp(), "x.mid")
        with open(path, "wb") as f:
            f.write(b"RIFF....WAVE")
        self.assertRaises(MidiError, read_midi, path)
        self.assertRaises(ValueError, read, "song.mp3")


class QuantizeTests(unittest.TestCase):
    def test_grid_and_error(self):
        g = quantize(Score([Note(0, 1, 60), Note(1.0 / 3, 1.0 / 3, 62), Note(0.99, 0.01, 64)]), 4)
        self.assertEqual([(n.start, n.dur) for n in sorted(g.notes, key=lambda n: n.pitch)], [(0, 4), (1, 2), (4, 1)])
        self.assertGreater(g.error, 0.1)
        self.assertEqual(quantize(Score([Note(0, 1, 60)], meter=(3, 4))).steps_per_bar, 12)
        self.assertEqual(quantize(Score([Note(0, 1, 60)], meter=(6, 8))).steps_per_bar, 12)


class ArrangerTests(unittest.TestCase):
    def test_every_arranger_on_every_piece_gives_a_valid_song(self):
        for entry in manifest():
            grid = grid_of(entry["file"][:-4])
            for name in ARRANGERS:
                arr = arrange(grid, name)
                self.assertLessEqual(len(arr.voices), 3)
                for v in arr.voices:
                    for (s1, d1, _p1), (s2, _d2, _p2) in zip(v.events, v.events[1:]):
                        self.assertLessEqual(s1 + d1, s2, "%s/%s voice %s overlaps" % (entry["file"], name, v.name))
                song = clio.to_song(arr, grid)
                self.assertEqual(clio.validate(song), [], "%s/%s" % (entry["file"], name))
                bar = grid.steps_per_bar
                for pname, tracks in song["patterns"].items():
                    for text in tracks.values():
                        self.assertEqual(clio.track_length(text) % bar, 0)
                total = sum(clio.track_length(next(iter(song["patterns"][p].values()))) for p in song["sequence"])
                self.assertGreaterEqual(total, grid.length)
                self.assertLess(total, grid.length + bar)

    def test_fewer_voices(self):
        grid = grid_of("ode_to_joy")
        for name in ARRANGERS:
            self.assertEqual(len(arrange(grid, name, voices=1).voices), 1)
            self.assertEqual(len(arrange(grid, name, voices=2).voices), 2)

    def test_what_each_strategy_is_known_to_do(self):
        """The findings the README talks about. If one changes, the README is out of date."""
        def score(piece, arranger, truth):
            grid = grid_of(piece)
            arr = arrange(grid, arranger)
            return metrics.evaluate(grid, arr, clio.to_song(arr, grid), truth)
        cross = {"melody": 0, "bass": 2}
        self.assertEqual(score("crossing", "skyline", cross)["melody_recall"], 0.0)     # fooled by the pad
        self.assertEqual(score("crossing", "roles", cross)["melody_recall"], 1.0)
        self.assertEqual(score("twinkle", "skyline", {"melody": 0})["melody_recall"], 1.0)
        self.assertEqual(score("twinkle", "roles", {"melody": 0})["melody_recall"], 1.0)  # a tune walks, a broken chord leaps
        dense = {"melody": 0, "bass": 2}
        self.assertGreater(score("dense_chords", "roles-arp", dense)["pitch_recall"],
                           score("dense_chords", "roles", dense)["pitch_recall"])
        self.assertEqual(score("ode_to_joy", "roles-arp", {"melody": 0, "bass": 2})["pitch_recall"], 1.0)

    def test_drums_are_mapped(self):
        arr = arrange(grid_of("groove"), "skyline")
        hits = {h for _s, hs in arr.drums for h in hs}
        self.assertEqual(hits, {"k", "s", "h", "o"})
        song = clio.to_song(arr, grid_of("groove"))
        self.assertIn("kit", song["instruments"])
        self.assertTrue(all("kit" in t for t in song["patterns"].values()))


class WriterTests(unittest.TestCase):
    def test_notation(self):
        from eigenchip.ir import Arrangement, Grid, Voice
        grid = Grid([Note(0, 20, 60)], 4, 120, (4, 4))
        v = Voice("lead", "lead", [(0, 2, [60]), (4, 20, [64, 67]), (30, 1, [72])])
        song = clio.to_song(Arrangement([v]), grid, bars_per_pattern=2)
        self.assertEqual(song["sequence"], ["A"])
        self.assertEqual(song["patterns"]["A"]["lead"],
                         "c4:2 .:2 [e4 g4]:12 | -:8 .:6 c5 .")
        self.assertEqual(clio.track_length(song["patterns"]["A"]["lead"]), 32)

    def test_identical_patterns_are_stored_once(self):
        from eigenchip.ir import Arrangement, Grid, Voice
        events = [(bar * 16, 4, [60]) for bar in range(4)]
        song = clio.to_song(Arrangement([Voice("lead", "lead", events)]), Grid([], 4, 120, (4, 4)), bars_per_pattern=1)
        self.assertEqual(song["sequence"], ["A", "A", "A", "A"])
        self.assertEqual(len(song["patterns"]), 1)


class MoreVoicesAndExpressionTests(unittest.TestCase):
    def test_four_to_six_voices(self):
        grid = grid_of("dense_chords")
        for name in ARRANGERS:
            kept = []
            for voices in (3, 4, 6):
                arr = arrange(grid, name, voices)
                self.assertLessEqual(len(arr.voices), voices)
                song = clio.to_song(arr, grid)
                self.assertEqual(clio.validate(song), [])
                self.assertEqual(len(song["instruments"]), len(set(song["instruments"])))
                for v in arr.voices:                                # still lines a chip channel can play
                    for (s0, d0, _p0), (s1, _d1, _p1) in zip(v.events, v.events[1:]):
                        self.assertLessEqual(s0 + d0, s1)
                kept.append(metrics.evaluate(grid, arr, song)["pitch_recall"])
            self.assertGreaterEqual(kept[1], kept[0], name)
            self.assertGreaterEqual(kept[2], kept[1], name)
        six = arrange(grid, "roles", 6)
        self.assertEqual([v.name for v in six.voices][:4], ["lead", "bass", "inner", "inner2"])
        self.assertGreater(metrics.evaluate(grid, six)["pitch_recall"],
                           metrics.evaluate(grid, arrange(grid, "roles", 3))["pitch_recall"] + 0.15)
        self.assertEqual(arrange(grid, "roles-arp", 5).voices[-1].role, "chords")      # the chords take what is left
        self.assertLess(len(arrange(grid_of("twinkle"), "skyline", 6).voices), 4)      # no more lines than there are

    def test_levels_follow_the_source(self):
        loud = Score([Note(i, 1, 60 + i, 20 + 15 * i, 0) for i in range(8)], 120)      # a crescendo
        grid = quantize(loud)
        arr = arrange(grid, "skyline", 1)
        song = clio.to_song(arr, grid)
        text = " ".join(t["lead"] for t in song["patterns"].values())
        marks = [int(tok.split("@")[1].split(":")[0]) for tok in text.split() if "@" in tok]
        self.assertEqual(marks, sorted(marks))
        self.assertTrue(marks[0] <= 2 and len(marks) >= 6, text)
        self.assertNotIn("@", text.split()[-1])                     # the loudest note is simply full
        self.assertIn("needs", song)
        plain = clio.to_song(arr, grid, expression="plain")
        self.assertNotIn("@", json.dumps(plain["patterns"]))
        self.assertNotIn("needs", plain)
        even = clio.to_song(arrange(grid_of("waltz"), "roles", 3), grid_of("waltz"))  # one velocity: nothing to say
        self.assertNotIn("@", json.dumps(even["patterns"]))
        self.assertNotIn("needs", even)
        self.assertEqual(even, clio.to_song(arrange(grid_of("waltz"), "roles", 3), grid_of("waltz"), expression="plain"))

    def test_slides_survive_a_pattern_edge(self):
        tracks = clio.effect_slides([{"kind": "riser", "start": 2.0, "end": 6.0, "low": 48.0, "high": 72.0,
                                      "noise": False, "strength": 1.0},
                                     {"kind": "swell", "start": 6.0, "end": 8.0, "low": 60.2, "high": 60.2, "noise": True},
                                     {"kind": "impact", "start": 8.0, "end": 8.2, "low": 33.0, "high": 33.0}], 4)
        self.assertEqual(sorted(tracks), ["boom", "fx", "hiss"])
        (start, steps, pitches, bend), = tracks["fx"]
        self.assertEqual((start, steps, pitches, bend), (8, 16, [48], ((48.0, 72.0), (2, 9))))
        first, _ = clio._track(tracks["fx"], 0, 16, 16)             # the pattern ends half way up
        second, _ = clio._track(tracks["fx"], 16, 16, 16)
        self.assertEqual(first, ".:8 c3>c4@2>6:8")
        self.assertEqual(second, "c4>c5@6>9:8 .:8")
        self.assertEqual(clio._track(tracks["hiss"], 16, 16, 16)[0], ".:8 c4@1>9:8")
        self.assertEqual(clio.track_length(first), 16)

    def test_noise_bed(self):
        texture = {"level": [0.0, 0.0, 0.3, 0.5, 0.7, 0.9, 0.9, 0.1, 0.0, 0.0], "pitch": [60.0] * 5 + [80.0] * 5}
        full = clio.texture_events(texture, 1.0, 10)
        # lasting noise is evened out over about two beats before it is written: one note, no flicker
        self.assertEqual([(s0, d) for s0, d, _p, _b in full], [(0, 10)])
        (p0, p1), (l0, l1) = full[0][3]
        self.assertTrue(p1 >= p0 and 1 <= l0 <= 4 and 1 <= l1 <= 4)
        # a long steady stretch is one long note, a break in it starts another
        steady = {"level": [0.5] * 40 + [0.0] * 40 + [0.6] * 40, "pitch": [60.0] * 120}
        notes = clio.texture_events(steady, 1.0, 120)
        self.assertLessEqual(len(notes), 8)
        self.assertEqual(max(d for _s, d, _p, _b in notes), clio.BED_LONGEST)
        self.assertFalse([n for n in notes if 52 <= n[0] < 64])                 # the silence in the middle stays silent
        song_bed = dict(clio.BED, **clio.BED_SMOOTH)
        self.assertGreater(song_bed["attack"], 0.25)                            # wind does not click
        plain = clio.texture_events(texture, 1.0, 10, full=False)
        self.assertEqual([(s0, d, b) for s0, d, _p, b in plain], [(2, 4, None), (6, 1, None)])
        self.assertEqual(clio.texture_events(None, 1.0, 10), [])


class ExpandTests(unittest.TestCase):
    """From fewer voices to more: the tune kept, the rest written from the harmony."""

    def tune_of(self, name):
        from eigenchip.ir import Score
        full = read(os.path.join(CORPUS, name + ".mid"))
        return full, quantize(Score([n for n in full.notes if n.channel == 0 and not n.drum],
                                    full.tempo, full.meter, full.title))

    def test_a_tune_alone_gets_a_bass_chords_and_an_inner_line(self):
        from eigenchip.arrangers import expand
        full, alone = self.tune_of("ode_to_joy")
        arr = arrange(alone, "expand", 4)
        self.assertEqual([v.role for v in arr.voices], ["lead", "bass", "inner", "chords"])
        self.assertEqual(arr.notes["tonic"], 0)                                  # C major
        lead = {(s, p) for s, _d, ps in arr.voice("lead").events for p in ps}
        self.assertEqual(lead, {(n.start, n.pitch) for n in alone.pitched})      # the tune is untouched
        key = {(arr.notes["tonic"] + s) % 12 for s in expand.SCALE}
        for role in ("bass", "inner", "chords"):
            for _s, _d, pitches in arr.voice(role).events:
                self.assertTrue(all(p % 12 in key for p in pitches), role)       # nothing written leaves the key
        roots = [ps[0] % 12 for _s, _d, ps in arr.voice("bass").events]
        self.assertGreater(roots.count(0) + roots.count(7), len(roots) // 2)     # mostly C and G under this tune
        for s, _d, ps in arr.voice("inner").events:                              # below the tune, never on it
            self.assertLess(ps[0], max(p for t, p in lead if t == s))
        self.assertEqual([v.role for v in arrange(alone, "expand", 2).voices], ["lead", "bass"])
        clio.validate(clio.to_song(arr, alone))
        # judged against the piece the tune was taken from: closer in harmony than the tune by itself
        whole = quantize(full)
        with_parts = metrics.evaluate(whole, arr, None, {})["chroma"]
        by_itself = metrics.evaluate(whole, arrange(alone, "skyline", 1), None, {})["chroma"]
        self.assertGreater(with_parts, by_itself + 0.05)

    def test_a_tune_is_written_as_text(self):
        from eigenchip.readers.tune import read_tune
        score = read_tune("e4 e4:2 . f#4:.5 eb3:1.5 | [c4 e4]@5:2 - g4>c5:1", tempo=96, meter=(3, 4))
        got = [(n.start, n.dur, n.pitch) for n in score.notes]
        self.assertEqual(got, [(0.0, 1.0, 64), (1.0, 2.0, 64), (4.0, 0.5, 66), (4.5, 1.5, 51),
                               (6.0, 3.0, 60), (6.0, 3.0, 64), (9.0, 1.0, 67)])       # the hold lengthens both of the pair
        self.assertEqual((score.tempo, score.meter), (96.0, (3, 4)))
        self.assertEqual([n.vel for n in score.notes][4:6], [80, 80])                   # @5: softer
        for bad, word in (("e4 h4", "not a note"), ("- c4", "holds"), ("", "no notes"), ("c4:x", "number of beats"),
                          ("c4:99", "between"), ("c11", "not a note")):
            with self.assertRaisesRegex(ValueError, word):
                read_tune(bad)

    def test_a_tune_as_notes_and_back_as_text(self):
        from eigenchip.readers.tune import read_notes, read_tune, write_tune
        for text in ("e4 e4 f4 g4 | g4 f4 e4 d4 | c4 c4 d4 e4 | e4:1.5 d4:.5 d4:2", "c4 . e4:.5 g4:.5 [c4 e4]:2 . a4"):
            self.assertEqual(write_tune(read_tune(text)), text)                    # what was written is read back the same
        score = read_notes([[2, 1, 67], [0, 1, 64], [1, 0.5, 64], [3.5, 2, 72]], tempo=110, meter=(3, 4))
        self.assertEqual([(n.start, n.pitch) for n in score.notes], [(0.0, 64), (1.0, 64), (2.0, 67), (3.5, 72)])
        self.assertEqual(write_tune(score), "e4 e4:.5 .:.5 g4 | .:.5 c5:2")
        self.assertEqual(write_tune(read_tune("c4:3 d4 | - e4")), "c4:3 d4:2 e4")   # a hold becomes a length
        held = read_notes([[0, 4, 60], [1, 1, 64]])                                 # still sounding when the next starts
        self.assertEqual(write_tune(held), "c4 e4")
        for bad in ([], [[0, 0, 60]], [[-1, 1, 60]], [[0, 1, 200]]):
            with self.assertRaises(ValueError):
                read_notes(bad)

    def test_styles_and_chords_of_ones_own(self):
        from eigenchip.arrangers import expand
        from eigenchip.readers.tune import read_tune
        grid = quantize(read_tune("e4 e4 f4 g4 | g4 f4 e4 d4 | c4 c4 d4 e4 | e4:1.5 d4:.5 d4:2", 120))
        bass = {}
        for style in expand.STYLES:
            arr = arrange(grid, "expand", 4, style=style)
            bass[style] = len(arr.voice("bass").events)
            self.assertEqual(arr.notes["style"], style)
            self.assertEqual(bool(arr.drums), bool(expand.STYLES[style]["drums"]), style)
            self.assertEqual(arr.voice("chords").instrument["arp"], expand.STYLES[style]["arp"], style)
            self.assertEqual(clio.validate(clio.to_song(arr, grid)), [], style)
        self.assertEqual((bass["march"], bass["drive"]), (16, 32))                      # every beat; every half beat
        self.assertLess(bass["waltz"], bass["march"])
        with self.assertRaisesRegex(ValueError, "Unknown style"):
            arrange(grid, "expand", 4, style="polka")
        # chords: read, named, and put in place of the arranger's own
        self.assertEqual(expand.parse_chords("C | G7 | Am F | -"),
                         [(0, 4, 7), (0, 4, 7), (7, 11, 2, 5), (7, 11, 2, 5), (9, 0, 4), (5, 9, 0), None, None])
        self.assertEqual([expand.chord_name(expand.parse_chord(n)) for n in ("C", "am".capitalize(), "Bb", "F#m7", "Bdim", "Fmaj7")],
                         ["C", "Am", "Bb", "F#m7", "Bdim", "Fmaj7"])
        for bad in ("H", "Cm9", "C G Am"):
            with self.assertRaises(ValueError):
                expand.parse_chords(bad)
        arr = arrange(grid, "expand", 4, chords_given=expand.parse_chords("C | G7 | Am F | -"))
        self.assertEqual(arr.notes["chords_text"].split(" | ")[:3], ["C", "G7", "Am F"])
        self.assertEqual([ps[0] % 12 for s, _d, ps in arr.voice("bass").events if s in (16, 32, 40)], [7, 9, 5])
        self.assertTrue(any(len(ps) == 4 for _s, _d, ps in arr.voice("chords").events))  # the seventh is played

    def test_parts_and_a_form(self):
        from eigenchip.readers.tune import parts_of, play_form, read_notes, read_tune, write_tune
        text = "e4 e4 f4 g4 | g4 f4 e4 d4 || c4 c4 d4 e4 | e4:1.5 d4:.5 d4:2 || g4:2"
        tune = read_tune(text)
        self.assertEqual(parts_of(tune), [("A", 0.0, 8.0), ("B", 8.0, 8.0), ("C", 16.0, 4.0)])
        self.assertEqual(write_tune(tune), text)                                     # the double bar lines are kept
        self.assertEqual([p[0] for p in parts_of(read_tune("c4 d4 e4 f4"))], ["A"])  # no double bar line: one part
        self.assertEqual(parts_of(read_tune("c4 d4 || e4")), [("A", 0.0, 4.0), ("B", 4.0, 4.0)])   # a part begins on a bar line
        played = play_form(tune, "a a b a c")
        self.assertEqual(played.info["form"], "A A B A C")
        self.assertEqual(played.info["parts"], [["A", 0.0, 0.0, 8.0], ["A", 8.0, 0.0, 8.0], ["B", 16.0, 8.0, 8.0],
                                                ["A", 24.0, 0.0, 8.0], ["C", 32.0, 16.0, 4.0]])
        self.assertEqual(len(played.notes), 3 * 8 + 7 + 1)
        self.assertEqual([n.pitch for n in played.notes if 8 <= n.start < 10], [64, 64])    # A again, from its beginning
        self.assertEqual(play_form(tune).info["form"], "A B C")                      # no form: every part once, in order
        self.assertEqual(play_form(tune, "AABA").info["form"], "A A B A")
        with self.assertRaisesRegex(ValueError, "names a part D"):
            play_form(tune, "A D")
        with self.assertRaisesRegex(ValueError, "letters of the parts"):
            play_form(tune, "A + B")
        drawn = read_notes([[0, 1, 60], [8, 1, 62]], sections=[1, 2])                # from a piano roll: parts by bar
        self.assertEqual([p[0] for p in parts_of(drawn)], ["A", "B", "C"])
        self.assertEqual(write_tune(drawn), "c4 .:3 || .:4 || d4")

    def test_minor_keys_cadences_and_a_key_of_ones_own(self):
        from eigenchip.arrangers import expand
        from eigenchip.readers.tune import play_form, read_tune
        keys = {"c4 e4 g4 e4 | f4 a4 g4:2": "C major",
                "a4 c5 e5 c5 | d5 f5 e5:2 | a4 c5 e5 a5 | g#5 e5 a5:2": "A minor",
                "d4 f4 a4 f4 | g4 bb4 a4:2 | d5 c5 bb4 a4 | g4 e4 d4:2": "D minor",
                "e4 g4 a4 b4 | d5 b4 a4 g4 | e4:4": "E minor"}
        for text, key in keys.items():
            self.assertEqual(arrange(quantize(read_tune(text)), "expand", 4).notes["key"], key, text)
        # the major dominant belongs to a minor key whose raised seventh is heard, and the piece comes home at the end
        harmonic = arrange(quantize(read_tune("a4 c5 e5 c5 | d5 f5 e5:2 | a4 c5 e5 a5 | g#5 e5 a5:2")), "expand", 4)
        self.assertEqual(harmonic.notes["chords_text"].split(" | ")[-1], "E Am")
        natural = arrange(quantize(read_tune("a4 c5 e5 c5 | d5 f5 e5:2 | a4 c5 e5 a5 | g5 e5 a5:2")), "expand", 4)
        self.assertNotIn("E ", natural.notes["chords_text"] + " ")                   # g natural: no E major here
        # a tune that never says b or b flat fits two scales; it is not taken for the minor key of the wrong one
        ode = "e4 e4 f4 g4 | g4 f4 e4 d4 | c4 c4 d4 e4 | e4:1.5 d4:.5 d4:2 || d4 d4 e4 c4 | d4 e4:.5 f4:.5 e4 c4 | " \
              "d4 e4:.5 f4:.5 e4 d4 | c4 d4 g3:2"
        for form in ("A", "A B", "A A B A"):
            self.assertEqual(arrange(quantize(play_form(read_tune(ode), form)), "expand", 4).notes["key"], "C major", form)
        # harmony moves: more than tonic and dominant, and not the same chord all the way
        chosen = arrange(quantize(play_form(read_tune(ode), "A")), "expand", 4).notes["chords_text"]
        self.assertGreaterEqual(len(set(chosen.replace("|", " ").split())), 3, chosen)
        self.assertEqual(chosen.split(" | ")[0].split()[0], "C")                     # it begins at home
        # the key can be given
        self.assertEqual(expand.parse_key("Am"), (0, True))
        self.assertEqual(expand.parse_key("F# minor"), (9, True))
        self.assertEqual(expand.parse_key("G major"), (7, False))
        # a mode can be asked for: the same seven chords, another one for home, and the chord that is the mode's own
        self.assertEqual(expand.parse_key("E phrygian"), (0, "phrygian"))
        self.assertEqual(expand.parse_key("d dorian"), (0, "dorian"))
        self.assertEqual((expand.parse_key("A aeolian"), expand.parse_key("C ionian")), ((0, True), (0, False)))
        dark = quantize(read_tune("e4:2 g4 e4 | f4:2 e4:2 | e4:2 g4 a4 | b4:3 a4 || b4:2 a4 g4 | a4:2 g4 f4 | "
                                  "e4:2 f4 g4 | e4:4"))
        found = arrange(dark, "expand", 4)
        self.assertEqual(found.notes["key"], "A minor")                              # a mode is never found by itself
        modal = arrange(dark, "expand", 4, key=expand.parse_key("E phrygian"), ending=True)
        self.assertEqual(modal.notes["key"], "E phrygian")
        bars = modal.notes["chords_text"].split(" | ")
        self.assertEqual((bars[0], bars[1], bars[-1]), ("Em", "F Em", "Em"))         # home, the flat second, home
        self.assertEqual(modal.voice("chords").events[-1][2], [55, 59, 64])          # the closing bar is on E minor
        self.assertIsNone(expand.parse_key(""))
        with self.assertRaisesRegex(ValueError, "not a key"):
            expand.parse_key("H")
        given = arrange(quantize(play_form(read_tune(ode), "A")), "expand", 4, key=expand.parse_key("Am"))
        self.assertEqual(given.notes["key"], "A minor")
        self.assertEqual(given.notes["chords_text"].split()[0], "Am")

    def test_a_walking_bass_moods_and_an_ending(self):
        from eigenchip.arrangers import expand
        from eigenchip.readers.tune import read_tune
        grid = quantize(read_tune("e4 e4 f4 g4 | g4 f4 e4 d4 | c4 c4 d4 e4 | e4:1.5 d4:.5 d4:2", 120))
        walk = arrange(grid, "expand", 4, style="walk")
        bass = walk.voice("bass").events
        self.assertEqual([(s, d) for s, d, _p in bass], [(4 * k, 4) for k in range(16)])    # a step on every beat
        key = {(walk.notes["tonic"] + s) % 12 for s in expand.SCALE}
        self.assertTrue(all(p[0] % 12 in key for _s, _d, p in bass))
        path = [c for bar in walk.notes["chords_text"].split(" | ") for c in (bar.split() * 2)[:2]]
        for w in range(1, len(path)):                                                # into each new chord by a step
            if path[w] != path[w - 1]:
                before, root = bass[2 * w - 1][2][0], bass[2 * w][2][0]
                self.assertIn(abs(before - root), (1, 2), (w, path[w - 1], path[w]))
                self.assertEqual(root % 12, expand.parse_chord(path[w])[0])
        for mood, how in expand.MOODS.items():
            arr = arrange(grid, "expand", 4, style=mood)
            song = clio.to_song(arr, grid)
            self.assertEqual(clio.validate(song), [], mood)
            self.assertEqual(arr.voice("lead").instrument["wave"], how["lead"], mood)
            self.assertEqual(bool(arr.drums), how["kit"] != "none", mood)
            self.assertTrue(30 <= how["tempo"] <= 200 and how["about"], mood)
            self.assertTrue(song["loop"])
        self.assertNotIn("duty", arrange(grid, "expand", 4, style="calm").voice("lead").instrument)
        self.assertFalse(set(expand.MOODS) & set(expand.STYLES))
        # an ending: one more bar on the tonic, and the song is played once
        ended = arrange(grid, "expand", 4, style="march", ending=True)
        self.assertEqual(ended.voice("bass").events[-1], (64, 16, [36]))
        self.assertEqual(ended.voice("chords").events[-1], (64, 16, [55, 60, 64]))
        self.assertEqual(ended.voice("lead").events[-1], (64, 16, [60]))             # the tune ended on d: it is brought home
        self.assertEqual(ended.drums[-1], (64, ["k", "o"]))
        song = clio.to_song(ended, grid)
        self.assertFalse(song["loop"])
        self.assertEqual(clio.validate(song), [])
        home = quantize(read_tune("e4 d4 c4:2 | d4 e4 c4:2", 120))                   # a tune that comes home by itself
        self.assertEqual(len(arrange(home, "expand", 4, ending=True).voice("lead").events), 6)

    def test_genres(self):
        from eigenchip.arrangers import expand
        from eigenchip.readers.tune import read_tune
        grid = quantize(read_tune("a4 c5 e5 c5 | d5 f5 e5:2 | a4 c5 e5 a5 | g#5 e5 a5:2", 100))
        self.assertEqual(list(expand.GENRES), ["rock", "metal", "doom", "industrial", "ambient", "soundscape"])
        self.assertFalse(set(expand.GENRES) & (set(expand.STYLES) | set(expand.MOODS)))
        tune = [(s, tuple(p)) for s, _d, p in arrange(grid, "expand", 4).voice("lead").events]
        for name, how in expand.GENRES.items():
            arr = arrange(grid, "expand", 4, style=name, ending=True)
            song = clio.to_song(arr, grid)
            self.assertEqual(clio.validate(song), [], name)
            self.assertEqual([(s, tuple(p)) for s, _d, p in arr.voice("lead").events][:len(tune)], tune, name)   # the tune is kept
            self.assertEqual(bool(arr.drums), bool(how["drums"]), name)
            self.assertNotIn("arp", song["instruments"]["chords"], name)          # a guitar or a pad: no arpeggio
            self.assertTrue(40 <= how["tempo"] <= 200 and how["about"], name)
            chords = arr.voice("chords").events
            if how["chords"] == "power":                                          # root, fifth, octave: no third
                self.assertTrue(all([p - ps[0] for p in ps] == [0, 7, 12] for _s, _d, ps in chords), name)
                self.assertTrue(all(how["low"] <= ps[0] < how["low"] + 12 for _s, _d, ps in chords), name)
                self.assertGreater(song["instruments"]["chords"]["drive"], 0.5, name)
                self.assertIn("2.3 for the overdrive", song["needs"], name)
            else:                                                                 # a pad: held, spread over more than an octave
                self.assertTrue(all(ps[-1] - ps[0] > 12 for _s, _d, ps in chords), name)
                self.assertGreaterEqual(song["instruments"]["chords"]["attack"], 0.5, name)
                self.assertNotIn("drive", song["instruments"]["chords"], name)
                self.assertIn("air", song["instruments"], name)
                self.assertNotIn("overdrive", song["needs"], name)
        strikes = lambda name: [s for s, _d, _p in arrange(grid, "expand", 4, style=name).voice("chords").events if s < 16]
        self.assertEqual(strikes("rock"), [0, 2, 4, 6, 8, 10, 12, 14])            # eighths
        self.assertEqual(strikes("metal"), [0, 2, 3, 4, 6, 7, 8, 10, 11, 12, 14, 15])     # a gallop
        self.assertEqual(strikes("doom"), [0])                                    # and left to ring
        self.assertEqual(strikes("industrial"), [0, 1, 3, 5, 6, 8, 9, 11, 13, 14])
        metal = arrange(grid, "expand", 4, style="metal")
        self.assertEqual([s for s, _d, _p in metal.voice("bass").events], [s for s, _d, _p in metal.voice("chords").events])
        self.assertTrue(all(b[2][0] == c[2][0] - 12 for b, c in zip(metal.voice("bass").events, metal.voice("chords").events)))
        self.assertIn("o", dict(metal.drums)[0])                                  # a crash where the phrase begins
        scape = arrange(grid, "expand", 4, style="soundscape")
        self.assertEqual({p[0] for _s, _d, p in scape.voice("bass").events}, {45})      # a drone on the tonic, a
        self.assertIsNone(scape.voice("inner"))
        air, sound = scape.tracks["air"]
        self.assertEqual((air[0][:2], air[0][3][1], air[1][3][1]), ((0, 16), (3, 7), (7, 3)))   # it swells and fades
        self.assertEqual(sound["wave"], "noise")
        song = clio.to_song(scape, grid)
        self.assertIn("@3>7:16", song["patterns"][song["sequence"][0]]["air"])
        plain = clio.to_song(scape, grid, expression="plain")                     # for CLIo 2.0: the air without its swell
        self.assertNotIn(">", plain["patterns"][plain["sequence"][0]]["air"])
        self.assertNotIn("needs", plain)
        steam = arrange(grid, "expand", 4, style="industrial").tracks["steam"][0]
        self.assertEqual([e[:2] for e in steam], [(28, 4), (60, 4)])              # the last beat of every second bar
        self.assertEqual(clio.to_song(arrange(grid, "expand", 4, style="industrial"), grid)["instruments"]["kit"]["drive"], 0.6)
        waltz = quantize(read_tune("c4 e4 g4 | f4 a4 c5 | g4 b4 d5 | c5:3", 120, (3, 4)))     # not four-four: a strike a beat
        self.assertEqual([s for s, _d, _p in arrange(waltz, "expand", 4, style="rock").voice("chords").events][:4], [0, 4, 8, 12])
        self.assertEqual(expand._strikes("x-x.", 0, 8, 16, 4), [(0, 2), (2, 1), (4, 2), (6, 1)])
        self.assertEqual(expand._strikes("x---", 2, 6, 16, 4), [(2, 2), (4, 2)])  # a chord that begins is struck

    @unittest.skipUnless(os.path.exists(os.path.join(os.environ.get("CLIO", os.path.join(ROOT, "..", "eryxgames", "clio")),
                                                     "engine", "audio", "compose.py")),
                         "no CLIo beside this folder (set CLIO to its folder to compare the moods)")
    def test_the_moods_are_those_of_clios_composer(self):
        from eigenchip.arrangers import expand
        home = os.environ.get("CLIO", os.path.join(ROOT, "..", "eryxgames", "clio"))
        sys.path.insert(0, home)
        try:
            import importlib
            compose = importlib.import_module("engine.audio.compose")
        finally:
            sys.path.remove(home)
        self.assertEqual(list(expand.MOODS), list(compose.MOODS))
        for name, (_scales, (slow, fast), _progressions, kit, lead, _density) in compose.MOODS.items():
            mood = expand.MOODS[name]
            self.assertEqual((mood["kit"], mood["lead"]), (kit, lead), name)
            self.assertEqual(mood["drums"], compose._DRUMS[kit].replace(" ", "") if kit != "none" else "", name)
            self.assertTrue(slow <= mood["tempo"] <= fast, name)

    def test_a_whole_piece_is_evidence_for_the_chords(self):
        for name in ("crossing", "long_tune", "ode_to_joy"):
            whole = quantize(read(os.path.join(CORPUS, name + ".mid")))
            arr = arrange(whole, "expand", 3)
            self.assertGreaterEqual(metrics.evaluate(whole, arr, None, {})["chroma"], 0.9, name)
            self.assertEqual(arr.notes["lead_channel"], 0, name)


class MetricTests(unittest.TestCase):
    def test_a_perfect_copy_scores_one(self):
        from eigenchip.ir import Arrangement, Voice
        grid = grid_of("triplets")
        lead = Voice("lead", "lead", [(n.start, n.dur, [n.pitch]) for n in grid.pitched if n.channel == 0])
        bass = Voice("bass", "bass", [(n.start, n.dur, [n.pitch]) for n in grid.pitched if n.channel == 1])
        res = metrics.evaluate(grid, Arrangement([lead, bass]), None, {"melody": 0, "bass": 1})
        for key in ("melody_recall", "bass_recall", "pitch_recall", "pitch_precision", "onset_f1"):
            self.assertAlmostEqual(res[key], 1.0, msg=key)
        self.assertAlmostEqual(res["chroma"], 1.0, places=6)

    def test_wrong_notes_score_low(self):
        from eigenchip.ir import Arrangement, Voice
        grid = grid_of("triplets")
        wrong = Voice("lead", "lead", [(n.start, n.dur, [n.pitch + 1]) for n in grid.pitched if n.channel == 0])
        res = metrics.evaluate(grid, Arrangement([wrong]), None, {"melody": 0})
        self.assertEqual(res["melody_recall"], 0.0)
        self.assertLess(res["pitch_precision"], 0.2)


class ProjectTests(unittest.TestCase):
    def test_corpus_files_match_the_builder(self):
        out = tempfile.mkdtemp()
        corpus_build.build(out)
        for entry in manifest():
            with open(os.path.join(out, entry["file"]), "rb") as a, open(os.path.join(CORPUS, entry["file"]), "rb") as b:
                self.assertEqual(hashlib.sha256(a.read()).hexdigest(), hashlib.sha256(b.read()).hexdigest(),
                                 entry["file"] + " is stale: run python corpus/build.py")

    def test_results_file_is_current(self):
        m, rows, problems = experiment.run()
        self.assertEqual(problems, [])
        with open(os.path.join(ROOT, "RESULTS.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), experiment.report(m, rows), "RESULTS.md is stale: run python experiments/run.py")

    def test_command_line(self):
        out = os.path.join(tempfile.mkdtemp(), "song.json")
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli.main(["convert", os.path.join(CORPUS, "waltz.mid"), "-o", out, "--name", "waltz",
                             "--arranger", "roles"])
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(list(data), ["waltz"])
        self.assertEqual(clio.validate(data["waltz"]), [])
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["compare", os.path.join(CORPUS, "crossing.mid"), "--melody", "0"]), 0)
            self.assertEqual(cli.main(["info", os.path.join(CORPUS, "groove.mid")]), 0)
        self.assertIn("roles-arp", buf.getvalue())
        with redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["convert", "nope.mid"]), 1)

    @unittest.skipUnless(os.environ.get("CLIO_HOME"), "set CLIO_HOME to a CLIo checkout to test real playback")
    def test_songs_play_in_clio(self):
        sys.path.insert(0, os.environ["CLIO_HOME"])
        from engine.audio import synth
        for entry in manifest():
            grid = grid_of(entry["file"][:-4])
            for name in ARRANGERS:
                song = clio.to_song(arrange(grid, name), grid)
                for tracks in song["patterns"].values():
                    for text in tracks.values():
                        self.assertEqual(synth.parse_track(text)[1], clio.track_length(text))
                self.assertGreater(max(abs(x) for x in synth.render_song(song)), 0.05)


if __name__ == "__main__":
    unittest.main()
