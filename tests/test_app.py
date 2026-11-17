# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Tests for the front door the web page uses, and for the files of the page itself."""
import importlib.util
import json
import os
import re
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))

try:
    import numpy as np
except ImportError:                                             # pragma: no cover
    np = None

import build_manifest                                           # noqa: E402
from eigenchip import __version__                               # noqa: E402
from eigenchip.app import Session, to_json                      # noqa: E402
from eigenchip.readers import read                              # noqa: E402

CORPUS = os.path.join(ROOT, "corpus")
WEB = os.path.join(ROOT, "web")
needs_numpy = unittest.skipIf(np is None, "NumPy is not installed")


def corpus_bytes(name):
    with open(os.path.join(CORPUS, name + ".mid"), "rb") as f:
        return f.read()


def clio_synth():
    spec = importlib.util.spec_from_file_location("clio_synth", os.path.join(WEB, "vendor", "clio", "clio_synth.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ComposerTests(unittest.TestCase):
    """The composer's way through the session: a tune as text, a style, chords, and voices switched off."""

    def test_a_tune_a_style_chords_and_muted_voices(self):
        session = Session()
        facts = session.open_tune("e4 e4 f4 g4 | g4 f4 e4 d4 | c4 c4 d4 e4 | e4:1.5 d4:.5 d4:2", tempo=120)
        self.assertEqual((facts["kind"], facts["notes"], facts["tempo"]), ("midi", 15, 120.0))
        view = session.arrange("expand", 4, style="march", chords="C | G7 | - | -")
        self.assertEqual(view["arranger"], "expand")
        self.assertEqual((view["style"], view["chords_text"].split(" | ")[:2]), ("march", ["C", "G7"]))
        self.assertEqual(view["instruments"], ["lead", "bass", "inner", "chords", "kit"])
        self.assertEqual([name for name, _about in view["styles"]], ["plain", "ballad", "march", "drive", "waltz", "walk"])
        self.assertIsNone(session.arrange("roles-arp", 3)["chords_text"])      # a reducing arranger has none to show
        with self.assertRaisesRegex(ValueError, "not a chord"):
            session.arrange("expand", 4, chords="C | H")
        self.assertEqual(view["tune_text"], "e4 e4 f4 g4 | g4 f4 e4 d4 | c4 c4 d4 e4 | e4:1.5 d4:.5 d4:2")
        session.arrange("expand", 4, style="march")

        # the same way in for a piano roll or a keyboard: notes in beats
        other = Session()
        other.open_tune(notes=[[0, 1, 64], [1, 1, 64], [2, 0.5, 65], [3, 1, 67]], tempo=110)
        drawn = other.arrange("expand", 4)
        self.assertEqual(drawn["tune_text"], "e4 e4 f4:.5 .:.5 g4")
        self.assertEqual([n[:3] for n in drawn["source"]], [[0, 4, 64], [4, 4, 64], [8, 2, 65], [12, 4, 67]])
        other.open_midi(corpus_bytes("ode_to_joy"))
        self.assertIsNone(other.arrange("roles-arp", 3)["tune_text"])             # a file is not a tune of one's own

        def loudness(wav):
            count = (len(wav) - 44) // 2
            values = struct.unpack("<%dh" % count, wav[44:44 + 2 * count])
            return (sum(v * v for v in values) / float(count)) ** 0.5

        synth = clio_synth()
        whole = loudness(session.chip_wav(synth))
        alone = loudness(session.chip_wav(synth, mute=["bass", "inner", "chords", "kit"]))
        self.assertTrue(0 < alone < whole)
        self.assertEqual(loudness(session.chip_wav(synth, mute=view["instruments"])), 0.0)
        self.assertEqual(session.song["instruments"]["bass"]["volume"], 0.5)   # muting leaves the song as it is


    def test_form_ending_key_and_moods(self):
        session = Session()
        tune = "e4 e4 f4 g4 | g4 f4 e4 d4 | c4 c4 d4 e4 | e4:1.5 d4:.5 d4:2 || d4 d4 e4 c4 | d4 e4:.5 f4:.5 e4 c4 | " \
               "d4 e4:.5 f4:.5 e4 d4 | c4 d4 g3:2"
        session.open_tune(tune, tempo=110)
        plain = session.arrange("expand", 4)
        self.assertEqual((plain["form"], plain["sections"], plain["steps"]), ("A B", [0, 4], 128))
        self.assertEqual((plain["key"], plain["ending"], json.loads(plain["song_json"])["loop"]), ("C major", False, True))
        view = session.arrange("expand", 4, style="heroic", form="a a b a", ending=True)
        self.assertEqual(view["form"], "A A B A")
        self.assertEqual(view["parts"], [["A", 0, 0, 64], ["A", 64, 0, 64], ["B", 128, 64, 64], ["A", 192, 0, 64]])
        self.assertEqual(view["steps"], 4 * 64 + 16)                              # and the closing bar
        self.assertFalse(json.loads(view["song_json"])["loop"])
        self.assertEqual(view["tune_text"], tune)                                 # the tune stays as it was written,
        self.assertEqual(len(view["written"]), 32)                                # however often its parts are played
        self.assertEqual(len(view["source"]), 15 * 3 + 17)
        self.assertEqual((view["style"], view["voices"][0]["wave"]), ("heroic", "square"))
        self.assertEqual([m[0] for m in view["moods"]][:3], ["calm", "mystery", "dark"])
        self.assertEqual([g[0] for g in view["genres"]][:6], ["rock", "metal", "doom", "industrial", "ambient", "soundscape"])
        self.assertEqual(len(view["genres"]), 11)
        self.assertFalse(view["driven"])
        heavy = session.arrange("expand", 4, style="doom")
        self.assertTrue(heavy["driven"])
        self.assertIn("CLIo 2.3 (drive, detune, filter, room)", heavy["needs"])
        self.assertTrue(session.arrange("expand", 4, style="dark orchestral")["driven"])  # no overdrive, but detune and a filter
        session.arrange("expand", 4, style="doom")
        synth = clio_synth()
        self.assertGreater(len(session.chip_wav(synth)), 44)                      # the vendored synthesizer has the overdrive
        self.assertTrue(hasattr(synth, "drive"))
        wide = session.arrange("expand", 4, style="soundscape")
        self.assertEqual(wide["instruments"], ["lead", "bass", "chords", "air"])
        self.assertGreater(len(session.chip_wav(synth, mute=["lead", "bass", "chords"])), 44)     # the air alone
        self.assertEqual(session.arrange("expand", 4, key="Am")["key"], "A minor")
        with self.assertRaisesRegex(ValueError, "names a part C"):
            session.arrange("expand", 4, form="A C")
        with self.assertRaisesRegex(ValueError, "not a key"):
            session.arrange("expand", 4, key="X")
        # parts from a piano roll, by bar; and a file has neither parts nor a form
        session.open_tune(notes=[[0, 1, 60], [4, 2, 64], [8, 4, 67]], sections=[1, 2])
        rolled = session.arrange("expand", 4, form="C A")
        self.assertEqual((rolled["sections"], rolled["tune_text"]), ([0, 1, 2], "c4 .:3 || e4:2 .:2 || g4:4"))
        self.assertEqual(rolled["parts"], [["C", 0, 32, 16], ["A", 16, 0, 16]])
        session.open_midi(corpus_bytes("ode_to_joy"))
        filed = session.arrange("expand", 4, form="A A", ending=True)
        self.assertEqual((filed["form"], filed["parts"], filed["written"], filed["ending"]), (None, None, None, True))


    def test_another_sound_for_the_tune_and_a_song_without_its_muted_voices(self):
        session = Session()
        session.open_tune("e4 e4 f4 g4 | g4 f4 e4 d4", tempo=100)
        view = session.arrange("expand", 4, style="march")
        self.assertEqual(([name for name, _about in view["leads"]], view["lead"]), (["soft", "flute", "strings"], ""))
        self.assertEqual(json.loads(view["song_json"])["instruments"]["lead"]["wave"], "square")
        flute = session.arrange("expand", 4, style="march", lead="flute")
        self.assertEqual((flute["lead"], json.loads(flute["song_json"])["instruments"]["lead"]["wave"]), ("flute", "sine"))
        self.assertEqual(json.loads(session.arrange("roles-arp", 3, lead="soft")["song_json"])["instruments"]["lead"]["wave"],
                         "soft")                                                  # for any arranger
        strings = session.arrange("expand", 4, lead="strings")
        self.assertTrue(strings["driven"])                                        # detune, a filter, a room: CLIo 2.3
        with self.assertRaisesRegex(ValueError, "Unknown sound for the tune"):
            session.arrange("expand", 4, lead="kazoo")
        # what is switched off is left out of the song that is taken away
        view = session.arrange("expand", 4, style="march")
        self.assertEqual(session.song_json(), view["song_json"])
        backing = json.loads(session.song_json(["lead", "inner"]))
        self.assertEqual(list(backing["instruments"]), ["bass", "chords", "kit"])
        self.assertTrue(all(set(tracks) <= {"bass", "chords", "kit"} for tracks in backing["patterns"].values()))
        from eigenchip.writers import clio
        self.assertEqual(clio.validate(backing), [])
        self.assertEqual(backing["sequence"], json.loads(view["song_json"])["sequence"])    # as long as it was
        alone = json.loads(session.song_json(["bass", "inner", "chords", "kit"]))
        self.assertEqual(list(alone["instruments"]), ["lead"])
        with self.assertRaisesRegex(ValueError, "Every voice is switched off"):
            session.song_json(view["instruments"])
        self.assertEqual(session.song["instruments"].keys(), json.loads(view["song_json"])["instruments"].keys())


class SessionTests(unittest.TestCase):
    def test_midi_from_bytes_to_song_and_sound(self):
        s = Session()
        facts = s.open_midi(corpus_bytes("ode_to_joy"), "ode", {"melody": 0, "bass": 2})
        self.assertEqual((facts["kind"], facts["notes"], facts["channels"], facts["version"]), ("midi", 148, 3, __version__))
        self.assertEqual((facts["lowest"], facts["highest"]), ("c2", "g4"))
        view = s.arrange("roles-arp")
        json.loads(to_json(view))                               # everything crosses into JavaScript as JSON
        self.assertEqual((view["judged_against"], view["offset"], view["played"]), ("file", 0.0, None))
        self.assertEqual([v["role"] for v in view["voices"]], ["lead", "bass", "chords"])
        self.assertEqual([r["arranger"] for r in view["scores"]], ["skyline", "roles", "roles-arp", "expand"])
        chosen = view["scores"][2]
        self.assertEqual((chosen["melody_recall"], chosen["bass_recall"]), (1.0, 1.0))
        self.assertEqual(view["steps"], 256)
        self.assertIn('"patterns"', view["song_json"])
        self.assertEqual(view["song_name"], "ode_to_joy")
        wav = s.chip_wav(clio_synth())
        self.assertEqual((wav[:4], wav[8:12]), (b"RIFF", b"WAVE"))
        seconds = (len(wav) - 44) / 2.0 / 22050
        self.assertAlmostEqual(seconds, view["steps"] * view["step_seconds"], delta=2.0)
        path = os.path.join(ROOT, "tests", "_roundtrip.mid")
        try:
            with open(path, "wb") as f:
                f.write(s.midi_bytes())
            self.assertEqual(len(read(path).notes), 148 + 192)
        finally:
            os.remove(path)

    def test_fewer_voices_and_other_arrangers(self):
        s = Session()
        s.open_midi(corpus_bytes("crossing"), truth={"melody": 0, "bass": 2})
        one = s.arrange("skyline", voices=1)
        self.assertEqual(len(one["voices"]), 1)
        three = s.arrange("roles")
        self.assertGreater(three["scores"][1]["melody_recall"], three["scores"][0]["melody_recall"])    # the pad piece

    def test_mistakes_are_plain_messages(self):
        s = Session()
        for call in (s.facts, s.arrange, s.midi_bytes, lambda: s.chip_wav(None)):
            with self.assertRaises(ValueError):
                call()
        s.open_midi(corpus_bytes("waltz"))
        with self.assertRaises(ValueError):
            s.arrange("magic")
        with self.assertRaises(ValueError):
            s.open_midi(b"not a midi file")

    @needs_numpy
    def test_an_example_played_and_heard(self):
        s = Session()
        facts = s.open_midi_as_audio(corpus_bytes("waltz"), "waltz", "band", True, {"melody": 0, "bass": 2},
                                     transcriber="nmf", tempo=None, meter=[4, 4])
        self.assertEqual((facts["kind"], facts["tempo_verdict"], facts["meter"]), ("audio", "ok", [3, 4]))
        self.assertGreaterEqual(facts["transcription"]["f1"], 0.9)
        self.assertEqual(facts["transcription"]["true_notes"], 53)
        view = s.arrange("roles-arp")
        json.loads(to_json(view))
        self.assertEqual(view["judged_against"], "played")
        self.assertEqual(len(view["played"]), 53)
        self.assertIsNotNone(view["scores"][0]["melody_recall"])
        self.assertGreaterEqual(view["scores"][2]["pitch_recall"], 0.9)
        wav = s.original_wav()
        self.assertEqual(wav[:4], b"RIFF")
        self.assertAlmostEqual((len(wav) - 44) / 2.0 / 22050, 10.4, delta=0.5)

    @needs_numpy
    def test_sound_of_unknown_origin(self):
        from eigenchip.audio import synth
        samples = synth.render(read(os.path.join(CORPUS, "triplets.mid")), "pluck")
        s = Session()
        facts = s.open_audio(samples, 22050, "clip", transcriber="peaks", tempo=100, meter=[4, 4])
        self.assertEqual((facts["info"]["tempo_given"], facts["tempo"], facts["info"]["transcriber"]), (True, 100.0, "peaks"))
        view = s.arrange("skyline")
        self.assertEqual((view["judged_against"], view["truth"], view["kind"]), ("heard", {}, "audio"))
        self.assertIsNone(view["scores"][0]["melody_recall"])
        self.assertEqual(len(s.original_wav()), 44 + 2 * len(samples))
        with self.assertRaises(ValueError):
            s.open_audio(np.zeros(0, dtype=np.float32))

    @needs_numpy
    @unittest.skipIf(np is None, "NumPy is not installed")
    def test_detail_tidying_and_effects_reach_the_page(self):
        from eigenchip.audio import synth
        drone = read(os.path.join(ROOT, "corpus", "deep_drone.mid"))
        session = Session()
        facts = session.open_audio(synth.scene(drone, synth.EFFECT_DEMO, "pad"), title="Scene", transcriber="pads",
                                   tempo=drone.tempo, quality="fast", clean="strict")
        self.assertEqual((facts["info"]["quality"], facts["info"]["clean"]), ("fast", "strict"))
        view = json.loads(to_json(session.arrange("roles", 3)))
        kinds = {e["kind"] for e in view["effects"]}
        self.assertTrue({"riser", "fall", "swell"} <= kinds, kinds)
        self.assertGreaterEqual(view["steps"], max(e["end"] for e in view["effects"]))
        sweeps = [e for e in view["effects"] if e["kind"] == "riser"]
        self.assertLessEqual(view["pitch_range"][0], min(e["low"] for e in sweeps))
        self.assertGreaterEqual(view["pitch_range"][1], max(e["high"] for e in sweeps) - 0.5)
        self.assertIn('"fx"', view["song_json"])
        samples = clio_synth().render_song(session.song)          # the effect tracks are playable
        self.assertGreater(max(abs(x) for x in samples), 0.05)
        quiet = Session()
        quiet.open_audio(synth.scene(drone, synth.EFFECT_DEMO, "pad"), transcriber="pads", tempo=drone.tempo,
                         quality="fast", effects=False)
        self.assertEqual(json.loads(to_json(quiet.arrange("roles", 3)))["effects"], [])

    @unittest.skipIf(np is None, "NumPy is not installed")
    def test_likeness_expression_and_more_voices(self):
        from eigenchip.audio import synth
        score = read(os.path.join(ROOT, "corpus", "dense_chords.mid"))
        session = Session()
        session.open_audio(synth.render(score, "band"), title="Dense", tempo=score.tempo)
        view = json.loads(to_json(session.arrange("roles", 5)))
        self.assertEqual((len(view["voices"]), view["expression"]), (5, "full"))
        self.assertIsNone(session.likeness)                         # nothing to compare until there is a chip sound
        cs = clio_synth()
        session.chip_wav(cs)
        like = json.loads(to_json(session.likeness))
        self.assertGreater(like["harmony"], 0.7)
        self.assertEqual(sorted(like), ["bass", "harmony", "loudness", "movement", "seconds"])
        three = json.loads(to_json(session.arrange("roles", 3, expression="plain")))
        self.assertIsNone(three["needs"])
        session.chip_wav(cs)
        self.assertLess(session.likeness["harmony"], like["harmony"] + 0.05)
        # every note the writer can produce is one the synthesizer understands
        for view_song in (session.song, json.loads(view["song_json"])):
            for tracks in view_song["patterns"].values():
                for name, text in tracks.items():
                    if view_song["instruments"][name].get("wave") == "drums":
                        continue
                    for _start, _steps, notes in cs.parse_track(text)[0]:
                        for note in notes:
                            pitch, target, a, b = cs.split_note(note)
                            self.assertGreater(cs.note_freq(pitch), 0, note)
                            self.assertTrue(target is None or cs.note_freq(target) > 0, note)
                            self.assertTrue(0 <= a <= 1 and 0 <= b <= 1, note)
        midi = Session()
        midi.open_midi(corpus_bytes("waltz"))
        midi.arrange("roles", 3)
        midi.chip_wav(cs)
        self.assertIsNone(midi.likeness)                            # a MIDI file has no sound of its own to compare

    def test_midi_can_be_heard_on_the_test_synth(self):
        s = Session()
        s.open_midi(corpus_bytes("twinkle"))
        self.assertEqual(s.original_wav("sine")[:4], b"RIFF")


class PageTests(unittest.TestCase):
    def test_the_file_list_is_current(self):
        with open(os.path.join(WEB, "manifest.json"), encoding="utf-8") as f:
            listed = json.load(f)
        self.assertEqual(listed, build_manifest.build(), "run: python web/build_manifest.py")
        for path in listed["package"] + list(listed["vendor"].values()):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)
        self.assertIn("eigenchip/app.py", listed["package"])
        self.assertNotIn("eigenchip/cli.py", listed["package"])

    def test_the_page_is_complete(self):
        with open(os.path.join(WEB, "index.html"), encoding="utf-8") as f:
            html = f.read()
        for ref in re.findall(r'(?:src|href)="([^"#:]+)"', html):
            self.assertTrue(os.path.isfile(os.path.join(WEB, ref.split("?")[0])), ref)
        # scripts and styles carry the version, so a browser never pairs an old script with a new page
        self.assertEqual(re.findall(r'app\.(?:js|css)\?v=([0-9.]+)"', html), [__version__, __version__])
        with open(os.path.join(WEB, "app.js"), encoding="utf-8") as f:
            js = f.read()
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        for used in set(re.findall(r'\$\("([^"]+)"\)', js)):
            self.assertIn(used, ids, "app.js uses #%s, which the page does not have" % used)
        self.assertIn('type: "module"', js)                     # current Pyodide refuses classic workers
        with open(os.path.join(WEB, "worker.js"), encoding="utf-8") as f:
            worker = f.read()
        self.assertRegex(worker, r'PYODIDE_VERSION = "\d+\.\d+\.\d+"')
        for command in re.findall(r'ask\("([a-z_]+)"', js):
            if command != "init":
                self.assertIn('name == "%s"' % command, worker)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, ".nojekyll")))    # or Pages hides __init__.py
        with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as f:
            self.assertIn('url=web/', f.read())

    def test_the_vendored_synth_plays_a_song(self):
        synth = clio_synth()
        samples = synth.render_song({"tempo": 120, "steps_per_beat": 4,
                                     "instruments": {"a": {"wave": "square"}},
                                     "patterns": {"p": {"a": "c4 . e4 . g4 . c5 ."}}, "sequence": ["p"]})
        self.assertGreater(len(samples), 10000)
        self.assertGreater(max(abs(x) for x in samples), 0.05)


if __name__ == "__main__":
    unittest.main()
