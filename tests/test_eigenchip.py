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
        self.assertEqual(score("twinkle", "roles", {"melody": 0})["melody_recall"], 0.0)  # fooled by the Alberti bass
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
