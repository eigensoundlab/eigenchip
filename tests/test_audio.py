# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Tests for the audio front end. They need NumPy; the format tests also need ffmpeg."""
import io
import math
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import numpy as np
except ImportError:                                             # pragma: no cover
    np = None

from eigenchip import cli, metrics                              # noqa: E402
from eigenchip.arrangers import arrange                         # noqa: E402
from eigenchip.audio import AudioError, analysis, decode, evaluate, synth       # noqa: E402
from eigenchip.ir import Note, Score, quantize                  # noqa: E402
from eigenchip.readers import is_audio, read                    # noqa: E402
from eigenchip.writers import clio                              # noqa: E402

CORPUS = os.path.join(ROOT, "corpus")
FFMPEG = decode.ffmpeg_path()
needs_numpy = unittest.skipIf(np is None, "NumPy is not installed")
needs_ffmpeg = unittest.skipIf(np is None or not FFMPEG, "ffmpeg is not installed")


def piece(name):
    return read(os.path.join(CORPUS, name + ".mid"))


def tmp(name):
    return os.path.join(tempfile.mkdtemp(prefix="eigenchip-test-"), name)


def tune(pitches, beats=1.0, tempo=120.0, channel=0):
    return Score([Note(i * beats, beats, p, 100, channel) for i, p in enumerate(pitches)], tempo)


def raw_wav(path, kind, channels, rate, bits, payload, extensible=False):
    """A WAV file written by hand, so the reader is tested against the format, not against itself."""
    align = channels * bits // 8
    if extensible:
        fmt = struct.pack("<HHIIHHHHIH14s", 0xFFFE, channels, rate, rate * align, align, bits, 22, bits, 0,
                          kind, b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71")
    else:
        fmt = struct.pack("<HHIIHH", kind, channels, rate, rate * align, align, bits)
    body = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"LIST" + struct.pack("<I", 5) + b"abcde" + b"\x00"         # an odd-sized chunk to skip
    body += b"data" + struct.pack("<I", len(payload)) + payload
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)


@needs_numpy
class DecodeTests(unittest.TestCase):
    values = [0.0, 0.5, -0.5, 0.25, -1.0, 0.999]

    def check(self, path, places):
        frames, rate = decode.read_wav(path)
        self.assertEqual((rate, frames.shape), (8000, (3, 2)))
        for got, want in zip(frames.ravel(), self.values):
            self.assertAlmostEqual(float(got), want, places=places)

    def test_wav_encodings(self):
        v = self.values
        path = tmp("a.wav")
        raw_wav(path, 1, 2, 8000, 16, struct.pack("<6h", *[int(round(x * 32767)) for x in v]))
        self.check(path, 3)
        raw_wav(path, 1, 2, 8000, 8, bytes(int(round(x * 127 + 128)) for x in v))
        self.check(path, 1)
        raw_wav(path, 1, 2, 8000, 24, b"".join(struct.pack("<i", int(round(x * 8388607)))[:3] for x in v))
        self.check(path, 5)
        raw_wav(path, 1, 2, 8000, 32, struct.pack("<6i", *[int(round(x * 2147483647)) for x in v]))
        self.check(path, 5)
        raw_wav(path, 3, 2, 8000, 32, struct.pack("<6f", *v))
        self.check(path, 6)
        raw_wav(path, 3, 2, 8000, 64, struct.pack("<6d", *v))
        self.check(path, 6)
        raw_wav(path, 1, 2, 8000, 16, struct.pack("<6h", *[int(round(x * 32767)) for x in v]), extensible=True)
        self.check(path, 3)

    def test_bad_files_are_reported_not_crashed_on(self):
        path = tmp("bad.wav")
        with open(path, "wb") as f:
            f.write(b"this is not a sound file at all")
        with self.assertRaises(AudioError):
            decode.read_wav(path)
        raw_wav(path, 2, 1, 8000, 4, b"\x00" * 64)                # ADPCM: not handled here
        with self.assertRaises(AudioError):
            decode.read_wav(path)
        with self.assertRaises(ValueError):
            read(tmp("song.xyz"))

    def test_without_ffmpeg_the_message_says_what_to_do(self):
        saved = dict(os.environ)
        try:
            os.environ["PATH"] = ""
            os.environ.pop("EIGENCHIP_FFMPEG", None)
            with self.assertRaises(AudioError) as caught:
                decode.load(tmp("song.ogg"))
            self.assertIn("ffmpeg", str(caught.exception))
            self.assertIn("WAV", str(caught.exception))
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_write_read_and_resample(self):
        t = np.arange(44100) / 44100.0
        stereo = np.stack((np.sin(2 * math.pi * 440 * t), np.sin(2 * math.pi * 440 * t)), axis=1) * 0.5
        path = tmp("tone.wav")
        decode.write_wav(path, stereo, 44100)
        samples, rate, info = decode.load(path)
        self.assertEqual((rate, info["channels"], info["source_rate"], info["decoder"]), (22050, 2, 44100, "wav"))
        self.assertAlmostEqual(len(samples) / 22050.0, 1.0, places=3)
        spectrum = np.abs(np.fft.rfft(samples[:16384] * np.hanning(16384)))
        self.assertAlmostEqual(np.argmax(spectrum) * 22050.0 / 16384, 440.0, delta=2.0)
        high = np.sin(2 * math.pi * 9000 * np.arange(44100) / 44100.0)      # above the new Nyquist: must go
        self.assertLess(float(np.abs(decode.resample(high, 44100, 11025)[200:-200]).max()), 0.02)

    @needs_ffmpeg
    def test_compressed_formats_through_ffmpeg(self):
        samples = synth.render(tune([60, 64, 67, 72], tempo=120), "organ")
        folder = os.path.dirname(tmp("x"))
        wav = os.path.join(folder, "a.wav")
        decode.write_wav(wav, samples)
        for ext, flags in ((".flac", ["-c:a", "flac"]), (".ogg", ["-c:a", "libvorbis"]),
                           (".mp3", ["-c:a", "libmp3lame"]), (".m4a", ["-c:a", "aac"])):
            packed = os.path.join(folder, "a" + ext)
            done = subprocess.run([FFMPEG, "-v", "error", "-y", "-i", wav] + flags + [packed],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if done.returncode != 0:
                continue                                        # this ffmpeg was built without that encoder
            back, rate, info = decode.load(packed)
            self.assertEqual((rate, info["decoder"]), (22050, "ffmpeg"))
            self.assertAlmostEqual(len(back) / 22050.0, len(samples) / 22050.0, delta=0.15)
            self.assertTrue(is_audio(packed))
            notes = {n.pitch for n in read(packed).notes}
            self.assertTrue({60, 64, 67, 72} <= notes, "%s: %s" % (ext, sorted(notes)))
        with open(os.path.join(folder, "junk.mp3"), "wb") as f:
            f.write(b"\x00" * 300)
        with self.assertRaises(AudioError):
            decode.load(os.path.join(folder, "junk.mp3"))


@needs_numpy
class AnalysisTests(unittest.TestCase):
    def test_reference_synth_plays_the_right_pitch(self):
        for colour in synth.TIMBRES:
            x = synth.render(tune([69], 2.0), colour)
            spectrum = np.abs(np.fft.rfft(x[2000:2000 + 16384] * np.hanning(16384)))
            self.assertAlmostEqual(np.argmax(spectrum) * 22050.0 / 16384, 440.0, delta=2.0, msg=colour)
        self.assertEqual(synth.truth(tune([60, 62], tempo=60)), [(0.0, 1.0, 60), (1.0, 2.0, 62)])

    def test_tempo_and_first_beat(self):
        for name, octave_ok in (("twinkle", False), ("waltz", False), ("groove", False), ("bach_prelude", True)):
            score = piece(name)
            flux, fps = analysis.onset_strength(synth.render(score, "band"))
            bpm, phase, confidence = analysis.estimate_tempo(flux, fps)
            verdict = evaluate.tempo_verdict(bpm, score.tempo)
            self.assertIn(verdict, ("ok", "double") if octave_ok else ("ok",), "%s: %.1f" % (name, bpm))
            beat = 60.0 / bpm
            if not octave_ok:                               # in even running notes any step could be the beat
                self.assertLess(min(phase % beat, beat - phase % beat), 0.03, name)
            self.assertGreater(confidence, 0.2)
        self.assertEqual(analysis.estimate_tempo(np.zeros(1000), 86.0)[2], 0.0)     # silence: no opinion

    def test_grid_fit_repairs_a_slightly_wrong_tempo(self):
        step = 60.0 / 97.3 / 4
        onsets = [0.21 + step * k for k in range(0, 240, 3)]
        bpm, offset, agreement = analysis.fit_grid(onsets, 96.0, 0.2)
        self.assertAlmostEqual(bpm, 97.3, delta=0.05)
        self.assertAlmostEqual(offset, 0.21, delta=0.01)
        self.assertGreater(agreement, 0.95)
        self.assertEqual(analysis.fit_grid(onsets[:3], 96.0, 0.2)[0], 96.0)         # too little to go on

    def test_scoring(self):
        ref = [(0.0, 0.5, 60), (0.5, 1.0, 64), (1.0, 1.5, 67)]
        same = evaluate.note_scores(ref, ref)
        self.assertEqual((same["precision"], same["recall"], same["f1"], same["frame_f1"]), (1.0, 1.0, 1.0, 1.0))
        late = evaluate.note_scores(ref, [(a + 0.2, b + 0.2, p) for a, b, p in ref])
        self.assertEqual(late["f1"], 0.0)
        octave = evaluate.note_scores(ref, [(a, b, p + 12) for a, b, p in ref])
        self.assertEqual((octave["f1"], octave["f1_class"]), (0.0, 1.0))
        extra = evaluate.note_scores(ref, ref + [(0.0, 0.5, 72), (0.01, 0.5, 60)])
        self.assertAlmostEqual(extra["precision"], 0.6)
        self.assertEqual(extra["recall"], 1.0)
        self.assertEqual(evaluate.note_scores(ref, [])["f1"], 0.0)
        self.assertEqual([evaluate.tempo_verdict(b, 100) for b in (101, 200, 50, 120)], ["ok", "double", "half", "wrong"])


@needs_numpy
class TranscriberTests(unittest.TestCase):
    def scores(self, score, method, colour="band", **kw):
        from eigenchip.audio.transcribe import transcribe
        notes = [n[:3] for n in transcribe(synth.render(score, colour, **kw), method)]
        return evaluate.note_scores(synth.truth(score), notes)

    def test_a_single_line_is_found_by_every_method(self):
        melody = tune([64, 64, 65, 67, 67, 65, 64, 62, 60, 60, 62, 64, 64, 62, 62], 0.5, 104)
        for method in ("mono", "peaks", "nmf"):
            for colour in ("square", "pluck"):
                res = self.scores(melody, method, colour)
                self.assertGreaterEqual(res["f1"], 0.9, "%s on %s: %s" % (method, colour, res))

    def test_repeated_notes_are_told_apart(self):
        res = self.scores(tune([67] * 8, 0.5, 100), "nmf", "organ")
        self.assertEqual((res["notes"], res["recall"]), (8, 1.0))

    def test_chords_need_a_multi_pitch_method(self):
        chords = Score([Note(b * 2, 2, p, 100, 0) for b, chord in enumerate([(48, 64, 67), (53, 65, 69), (55, 62, 71)])
                        for p in chord], 90)
        self.assertGreaterEqual(self.scores(chords, "nmf", "organ")["f1"], 0.9)
        self.assertGreaterEqual(self.scores(chords, "peaks", "organ")["recall"], 0.6)
        self.assertLessEqual(self.scores(chords, "mono", "organ")["recall"], 0.4)       # one line at most

    def test_corpus_pieces(self):
        for name, floor in (("waltz", 0.9), ("triplets", 0.9), ("bach_prelude", 0.9)):
            res = self.scores(piece(name), "nmf", drums=False)
            self.assertGreaterEqual(res["f1"], floor, "%s: %s" % (name, res))

    def test_silence_and_noise_do_not_crash(self):
        from eigenchip.audio.transcribe import TRANSCRIBERS, transcribe
        rng = np.random.RandomState(1)
        for method in TRANSCRIBERS:
            self.assertEqual(transcribe(np.zeros(22050, dtype=np.float32), method), [])
            self.assertIsInstance(transcribe(rng.uniform(-0.3, 0.3, 22050).astype(np.float32), method), list)
        with self.assertRaises(ValueError):
            transcribe(np.zeros(100, dtype=np.float32), "magic")


@needs_numpy
class DrumsDeepTonesAndLinesTests(unittest.TestCase):
    def test_drums_are_found_and_not_imagined(self):
        from eigenchip.audio.transcribe import Spectrum, find_drums
        score = piece("groove")
        beat = 60.0 / score.tempo
        kinds = {36: "k", 38: "s"}
        truth = [(n.start * beat, kinds.get(n.pitch, "h")) for n in score.notes if n.drum]
        spec = Spectrum(synth.render(score, "band"))
        res = evaluate.drum_scores(truth, find_drums(spec))
        self.assertGreaterEqual(res["precision"], 0.9, res)
        self.assertGreaterEqual(res["recall"], 0.6, res)
        self.assertTrue(spec.kicks)
        for name in ("waltz", "crossing"):                      # no drums in these: none should be heard
            self.assertEqual(find_drums(Spectrum(synth.render(piece(name), "band"))), [], name)
        self.assertEqual(evaluate.drum_scores([(1.0, "k")], [(1.02, "k"), (1.0, "s")])["precision"], 0.5)

    def test_sub_bass_needs_the_deep_window(self):
        from eigenchip.audio.transcribe import Spectrum, transcribe
        score = piece("deep_drone")
        samples = synth.render(score, "sine")
        lows = lambda spec: {n[2] for n in transcribe(spec, "pads") if n[2] < 36}      # noqa: E731
        self.assertEqual(lows(Spectrum(samples)), {22, 24, 26})                 # Bb0, C1, D1: 29 to 37 Hz
        self.assertNotEqual(lows(Spectrum(samples, deep=False)), {22, 24, 26})  # the ordinary window cannot tell

    def test_slow_reading_suits_sustained_sound(self):
        from eigenchip.audio.transcribe import Spectrum, transcribe
        score = piece("deep_drone")
        spec = Spectrum(synth.render(score, "pad"))
        score_of = lambda m: evaluate.note_scores(synth.truth(score), [n[:3] for n in transcribe(spec, m)],     # noqa: E731
                                                  tolerance=0.25)["f1"]
        self.assertGreaterEqual(score_of("pads"), 0.8)
        self.assertGreater(score_of("pads"), score_of("nmf") + 0.2)

    def test_lines_are_found_again(self):
        from eigenchip.voices import consistency, flatten, separate
        score = piece("twinkle")
        flat = flatten(score)
        self.assertEqual(flat.channels(), [0])
        apart = separate(flat)
        self.assertEqual(len(apart.notes), len(score.notes))
        self.assertGreaterEqual(len(apart.channels()), 2)
        self.assertTrue(apart.info["lines_guessed"])
        self.assertEqual(consistency(score, apart), 1.0)
        self.assertLess(consistency(score, flat.__class__(
            [Note(n.start, n.dur, n.pitch, n.vel, i % 3) for i, n in enumerate(score.notes)], score.tempo)), 0.6)
        mean = lambda ch: sum(n.pitch for n in apart.notes if n.channel == ch) / float(     # noqa: E731
            sum(1 for n in apart.notes if n.channel == ch))
        self.assertGreater(mean(0), mean(apart.channels()[-1]))                 # numbered from the top down
        groove = separate(flatten(piece("groove")))
        self.assertEqual(sum(1 for n in groove.notes if n.drum), 84)            # drums are left alone
        # with the channels gone, the pad piece loses its tune; with lines found again, most of it is back
        crossing = piece("crossing")
        tune = lambda s: metrics.evaluate(quantize(crossing), arrange(quantize(s), "roles"), None,      # noqa: E731
                                          {"melody": 0})["melody_recall"]
        self.assertEqual(tune(flatten(crossing)), 0.0)
        self.assertGreaterEqual(tune(separate(flatten(crossing))), 0.7)

    def test_the_reader_reports_progress_drums_and_lines(self):
        from eigenchip.readers.audio import score_from_samples
        seen = []
        score = score_from_samples(synth.render(piece("groove"), "band"),
                                   progress=lambda fraction, text: seen.append((fraction, text)))
        self.assertGreater(len(seen), 5)
        self.assertEqual([f for f, _t in seen], sorted(f for f, _t in seen))
        self.assertEqual(seen[-1][0], 1.0)
        self.assertGreater(sum(1 for n in score.notes if n.drum), 40)
        self.assertEqual(score.info["drum_hits"], sum(1 for n in score.notes if n.drum))
        self.assertGreaterEqual(len(score.channels()), 2)
        plain = score_from_samples(synth.render(piece("waltz"), "band"), drums=False, voices=0)
        self.assertEqual((plain.channels(), sum(1 for n in plain.notes if n.drum)), ([0], 0))


@needs_numpy
class QualityCleaningAndEffectsTests(unittest.TestCase):
    def test_quality_is_a_choice_between_time_and_detail(self):
        from eigenchip.audio.transcribe import QUALITY, Spectrum, transcribe
        samples = synth.render(piece("twinkle"), "band", drums=False)
        truth = synth.truth(piece("twinkle"))
        frames = {}
        for quality in QUALITY:
            spec = Spectrum(samples, quality=quality)
            frames[quality] = spec.raw.shape[0]
            res = evaluate.note_scores(truth, [n[:3] for n in transcribe(spec, "nmf")])
            self.assertGreaterEqual(res["f1"], 0.85, quality)
        self.assertLess(frames["fast"], frames["standard"])
        self.assertLess(frames["standard"], frames["fine"])
        with self.assertRaisesRegex(ValueError, "fast, standard, fine"):
            Spectrum(samples, quality="perfect")

    def test_cleaning_rules(self):
        from eigenchip.audio.clean import clean
        notes = [(0.0, 0.5, 60, 0.9), (0.53, 0.6, 60, 0.3),         # a held note and the scrap after it
                 (1.0, 1.5, 64, 0.9), (1.0, 1.4, 65, 0.2),          # a note and its semitone shadow
                 (2.0, 2.5, 67, 0.8), (3.0, 3.05, 72, 0.2),         # a real note; a blip
                 (4.0, 4.08, 50, 0.2)]                              # a faint scrap on a drum hit
        self.assertEqual(clean(notes, "off"), sorted(notes))
        light = clean(notes, "light", hits=[(4.0, "k")])
        self.assertEqual([(n[0], n[2]) for n in light], [(0.0, 60), (1.0, 64), (2.0, 67), (3.0, 72)])
        self.assertAlmostEqual(light[0][1], 0.6)                    # the scrap was joined on, not thrown away
        strict = clean(notes, "strict", hits=[(4.0, "k")])
        self.assertEqual([n[2] for n in strict], [60, 64, 67])
        # what a sweep leaves behind: a staircase along its path, and nothing else is touched
        riser = {"kind": "riser", "start": 10.0, "end": 12.0, "low": 50.0, "high": 74.0, "noise": False}
        stairs = [(10.0 + 0.2 * i, 10.2 + 0.2 * i, 51 + int(2.4 * i), 0.6) for i in range(10)]
        tune_under = [(10.0, 11.0, 40, 0.9), (10.5, 10.8, 90, 0.9)]
        self.assertEqual(clean(stairs + tune_under, "light", effects=[riser]), sorted(tune_under))
        fall = dict(riser, kind="fall")
        left = len(clean(stairs, "light", effects=[fall]))          # a fall crosses that staircase, no more
        self.assertTrue(6 <= left < 10, left)
        with self.assertRaisesRegex(ValueError, "off, light, strict"):
            clean(notes, "spotless")

    def test_effects_are_found_and_not_imagined(self):
        from eigenchip.audio.effects import find_effects
        from eigenchip.audio.transcribe import Spectrum
        demo = synth.EFFECT_DEMO
        found = find_effects(Spectrum(synth.scene(None, demo)))
        res = evaluate.effect_scores(demo, found)
        self.assertEqual((res["found"], res["wrong"]), (8, 0), found)
        hiss = [e for e in found if e["noise"]]
        self.assertEqual(sorted(e["kind"] for e in hiss), ["riser", "swell"])
        first = found[0]
        self.assertEqual(first["kind"], "riser")
        self.assertTrue(2.0 <= first["start"] <= 2.6 and 4.8 <= first["end"] <= 5.2, first)   # its quiet start may be cut
        for when, pitch in ((first["start"], first["low"]), (first["end"], first["high"])):
            self.assertAlmostEqual(pitch, 48 + 36 * (when - 2.0) / 3.0, delta=2.5)          # but it is where it says
        # music is not an effect: scale runs, arpeggios, plucked basses, drums
        for name, colour in (("bach_prelude", "pluck"), ("twinkle", "band"), ("groove", "band"), ("deep_drone", "pad")):
            self.assertEqual(find_effects(Spectrum(synth.render(piece(name), colour))), [], name)
        # over a tune most are still found, and few invented
        over = evaluate.effect_scores(demo, find_effects(Spectrum(synth.scene(piece("groove"), demo, "band"))))
        self.assertGreaterEqual(over["found"], 6)
        self.assertLessEqual(over["wrong"], 2)
        self.assertEqual(evaluate.effect_scores(demo, [])["found"], 0)

    def test_the_reader_keeps_effects_apart_and_the_song_plays_them(self):
        from eigenchip.readers.audio import score_from_samples
        drone = piece("deep_drone")
        samples = synth.scene(drone, synth.EFFECT_DEMO, "pad")
        heard = score_from_samples(samples, transcriber="pads", tempo=drone.tempo, quality="fast")
        info = heard.info
        self.assertEqual((info["quality"], info["clean"]), ("fast", "light"))
        kinds = [e["kind"] for e in info["effects"]]
        self.assertGreaterEqual(len(kinds), 5)
        self.assertIn("riser", kinds)
        beat = 60.0 / heard.tempo
        riser = [e for e in info["effects"] if e["kind"] == "riser"][0]
        self.assertAlmostEqual(riser["end"] * beat + info["offset"], 5.0, delta=0.4)    # stored in beats
        self.assertGreater(info["cleaned_away"], 0)
        untidy = score_from_samples(samples, transcriber="pads", tempo=drone.tempo, clean="off", effects=False)
        self.assertEqual((untidy.info["effects"], untidy.info["cleaned_away"]), ([], 0))
        self.assertGreater(len(untidy.notes), len(heard.notes))
        grid = quantize(heard)
        self.assertEqual(grid.info["effects"], info["effects"])
        song = clio.to_song(arrange(grid, "roles", 3), grid)
        self.assertEqual(clio.validate(song), [])
        self.assertEqual(song["instruments"]["fx"], clio.FX_SLIDING["fx"])
        self.assertIn("2.1", song["needs"])
        fx = " ".join(tracks.get("fx", "") for tracks in song["patterns"].values())
        self.assertRegex(fx, r"[a-g]#?\d>[a-g]#?\d@\d>\d:\d+")         # one note that slides and grows
        plain = clio.to_song(arrange(grid, "roles", 3), grid, expression="plain")
        self.assertEqual(clio.validate(plain), [])
        self.assertEqual(plain["instruments"]["fx"], clio.FX_INSTRUMENTS["fx"])
        self.assertNotIn("needs", plain)                            # the chip as it was: CLIo 2.0 plays it
        for tracks in plain["patterns"].values():
            for text in tracks.values():
                self.assertNotRegex(text, "[@>]")
        bare = clio.to_song(arrange(grid, "roles", 3), grid, effects=False)
        self.assertNotIn("fx", bare["instruments"])
        with self.assertRaisesRegex(ValueError, "full, plain"):
            clio.to_song(arrange(grid, "roles", 3), grid, expression="loud")

    def test_loudness_and_lasting_noise_are_measured(self):
        from eigenchip.readers.audio import score_from_samples
        drone = piece("deep_drone")
        tones = synth.render(drone, "pad")
        calm = score_from_samples(tones, transcriber="pads", tempo=drone.tempo)
        self.assertLess(calm.info["noise_share"], 0.03)
        self.assertNotIn("texture", calm.info)
        self.assertEqual(calm.info["loudness_per_beat"], 4)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in calm.info["loudness"]))
        self.assertLess(score_from_samples(synth.render(piece("groove"), "band")).info["noise_share"], 0.03)   # hats are the kit's
        rng = np.random.RandomState(3)                              # wind over the drone, rising
        wind = rng.uniform(-1, 1, len(tones)).astype(np.float32) * np.linspace(0.04, 0.5, len(tones)).astype(np.float32)
        windy = score_from_samples(tones + wind, transcriber="pads", tempo=drone.tempo)
        self.assertGreater(windy.info["noise_share"], 0.1)
        level = windy.info["texture"]["level"]
        self.assertGreater(sum(level[-40:]), 2 * sum(level[:40]))   # and it is heard to rise
        grid = quantize(windy)
        song = clio.to_song(arrange(grid, "roles", 3), grid)
        self.assertEqual(clio.validate(song), [])
        self.assertEqual(song["instruments"]["bed"]["wave"], "noise")
        bed = [tracks["bed"] for tracks in song["patterns"].values() if "bed" in tracks]
        self.assertTrue(bed and any("@" in text for text in bed))
        self.assertNotIn("bed", clio.to_song(arrange(grid, "roles", 3), grid, effects=False)["instruments"])
        plain = clio.to_song(arrange(grid, "roles", 3), grid, expression="plain")
        self.assertNotRegex(" ".join(t.get("bed", "") for t in plain["patterns"].values()), "[@>]")

    def test_sound_against_sound(self):
        from eigenchip.audio import compare
        own, other = piece("twinkle"), piece("crossing")
        a, b = synth.render(own, "band"), synth.render(other, "band")
        same = compare.compare(a, a)
        self.assertEqual([same[k] for k in compare.KEYS], [1.0, 1.0, 1.0, 1.0])
        again = compare.compare(a, synth.render(own, "square"))     # another tone colour, the same music
        self.assertGreater(again["harmony"], 0.85)
        apart = compare.compare(a, b)
        self.assertLess(apart["harmony"], 0.4)
        self.assertLess(apart["bass"], 0.4)
        late = np.concatenate((np.zeros(22050, dtype=np.float32), a))
        self.assertGreater(compare.compare(late, a, lead=1.0)["harmony"], 0.95)
        self.assertLess(compare.compare(late, a)["harmony"], 0.7)   # a second out of step
        self.assertEqual(compare.compare(a, np.zeros(len(a), dtype=np.float32))["harmony"], 0.0)
        with self.assertRaisesRegex(ValueError, "short"):
            compare.compare(a[:4000], a[:4000])

    def test_effect_tracks(self):
        tracks = clio.effect_tracks([
            {"kind": "riser", "start": 0.0, "end": 2.0, "low": 60.0, "high": 68.0, "noise": False},
            {"kind": "fall", "start": 1.5, "end": 3.0, "low": 60.0, "high": 72.0, "noise": False},   # overlaps: waits
            {"kind": "riser", "start": 4.0, "end": 5.0, "low": 70.0, "high": 90.0, "noise": True},
            {"kind": "swell", "start": 6.0, "end": 8.0, "low": 57.2, "high": 57.2, "noise": False},
            {"kind": "impact", "start": 8.0, "end": 8.25, "low": 33.0, "high": 33.0, "noise": False},
        ], 4)
        self.assertEqual(sorted(tracks), ["air", "boom", "fx", "swell"])
        fx = tracks["fx"]
        self.assertEqual(fx[0][0], 0)
        pitches = [p[0] for s, d, p in fx if s < 8]
        self.assertEqual(pitches, sorted(pitches))                  # the riser climbs
        self.assertEqual((pitches[0], pitches[-1]), (60, 68))
        later = [p[0] for s, d, p in fx if s >= 8]
        self.assertEqual(later, sorted(later, reverse=True))        # then the fall, from where it is by then
        for events in tracks.values():                              # nothing overlaps on a track
            for (s0, d0, _p0), (s1, _d1, _p1) in zip(events, events[1:]):
                self.assertLessEqual(s0 + d0, s1)
        self.assertEqual(tracks["swell"], [(24, 8, [57])])          # one note, not eight
        self.assertEqual(tracks["boom"], [(32, 8, [33])])           # an impact rings for two beats at least
        self.assertEqual(clio.effect_tracks(None, 4), {})


@needs_numpy
class TuneTests(unittest.TestCase):
    """Which notes are the tune, chosen with the whole piece in view (eigenchip/audio/melody.py)."""

    def test_the_line_is_chosen_by_standing_and_by_how_it_moves(self):
        from eigenchip.audio.melody import tune
        # a slow tune in long notes, a busy figure above it: the tune is the one that stands out
        slow = [(0.0, 2.0, 62, 0.9), (2.0, 4.0, 64, 0.9), (4.0, 6.0, 65, 0.9)]
        busy = [(0.25 * i, 0.25 * i + 0.2, 81 + (i % 3) * 4, 0.4) for i in range(24)]
        notes = slow + busy
        self.assertEqual(tune(notes, [1.0] * 3 + [0.25] * 24), [0, 1, 2])
        # of equal standing, the top of a chord leads
        chords = [(t, t + 1.0, p, 0.8) for t in (0.0, 1.0, 2.0) for p in (60, 64, 67 + int(t))]
        self.assertEqual([chords[i][2] for i in tune(chords, [1.0] * 9)], [67, 68, 69])
        # one line plays one note at a time, and does not hop an octave and a half for a short note
        hop = [(0.0, 1.0, 60, 1.0), (1.0, 1.2, 80, 1.0), (1.0, 2.0, 62, 1.0)]
        self.assertEqual(tune(hop, [1.0, 1.0, 1.0]), [0, 2])
        self.assertEqual(tune([(0.0, 1.0, 30, 1.0)], [1.0]), [])            # too low to be a tune

    @needs_numpy
    def test_a_slow_tune_is_followed_under_a_moving_figure(self):
        from eigenchip.readers.audio import score_from_samples
        score = piece("long_tune")
        samples = synth.render(score, "band", drums=False)
        truth = {"melody": 0, "bass": 3}
        found = {}
        for label, options in (("followed", {}), ("lines only", {"tune": False})):
            heard = score_from_samples(samples, tempo=score.tempo, offset=0.0, effects=False, **options)
            found[label] = metrics.evaluate(quantize(score), arrange(quantize(heard), "roles-arp"), None, truth)
            if label == "followed":
                self.assertEqual(heard.info["lead_channel"], 0)
                self.assertEqual(heard.names[0], "tune")
        self.assertGreaterEqual(found["followed"]["melody_recall"], 0.9)
        self.assertLess(found["lines only"]["melody_recall"], 0.5)          # what sorting note by note makes of it
        self.assertGreaterEqual(found["followed"]["bass_recall"], 0.9)

    def test_the_key_and_the_register_are_remembered(self):
        from eigenchip.audio import melody
        c_major = [(i * 0.5, i * 0.5 + 0.5, 60 + p, 0.8) for i, p in enumerate((0, 2, 4, 5, 7, 9, 11, 12, 7, 4, 0))]
        self.assertEqual(melody.key_of(c_major), {0, 2, 4, 5, 7, 9, 11})
        stray = c_major + [(6.0, 6.2, 61, 0.8)]                              # one wrong note does not change the key
        self.assertEqual(melody.key_of(stray), {0, 2, 4, 5, 7, 9, 11})
        every = [(i * 0.5, i * 0.5 + 0.5, 60 + i % 12, 0.8) for i in range(24)]
        self.assertIsNone(melody.key_of(every))                              # all twelve alike: no key to keep to
        # where the tune lies: the middle of its notes around that time, by worth
        line = [(float(i), i + 1.0, 72, 1.0) for i in range(6)] + [(6.0, 7.0, 48, 1.0)]
        lies = melody._register(line, list(range(7)), [1.0] * 7)
        self.assertEqual(lies[6], 72)                                        # the low note is far from the tune
        self.assertEqual(melody._register(line, [], [1.0] * 7), [None] * 7)

    @needs_numpy
    def test_a_held_note_cut_in_pieces_is_put_together_and_a_repeated_one_is_not(self):
        from eigenchip.audio import melody
        from eigenchip.audio.transcribe import Spectrum
        held = Score([Note(0.0, 4.0, 69, 100, 0, 0), Note(4.0, 2.0, 72, 100, 0, 0)], 120)
        again = Score([Note(0.0, 2.0, 69, 100, 0, 0), Note(2.0, 2.0, 69, 100, 0, 0), Note(4.0, 2.0, 72, 100, 0, 0)], 120)
        pieces = [(0.0, 0.95, 69, 0.5), (1.0, 1.9, 69, 0.5), (2.0, 2.9, 72, 0.5)]   # what a wavering note is written as
        for score, count in ((held, 2), (again, 3)):
            spec = Spectrum(synth.render(score, "organ", drums=False))
            self.assertEqual(len(melody.mend(spec, pieces, [0, 1, 2])), count)
        whole = melody.mend(Spectrum(synth.render(held, "organ", drums=False)), pieces, [0, 1, 2])
        self.assertEqual(whole[0][:3], (0.0, 1.9, 69))
        far = [(0.0, 0.95, 69, 0.5), (1.6, 1.9, 69, 0.5)]                           # too far apart to be one note
        self.assertEqual(len(melody.mend(Spectrum(synth.render(held, "organ", drums=False)), far, [0, 1])), 2)

    def test_a_midi_file_says_which_part_is_played_to_be_heard(self):
        for name in ("long_tune", "octaves", "crossing"):
            arr = arrange(quantize(piece(name)), "roles")
            self.assertEqual(arr.notes["lead_channel"], 0, name)

    def test_a_long_note_follows_the_loudness_in_pieces(self):
        flat = [5] * 40
        self.assertEqual(clio._spans(flat, 0, 40), [(0, 40)])
        ramp = [int(round(2 + 6 * i / 39.0)) for i in range(40)]
        self.assertEqual(clio._spans(ramp, 0, 40), [(0, 40)])                # one token can say "from 2 to 8"
        hill = [2] * 20 + [8] * 4 + [3] * 16
        spans = clio._spans(hill, 0, 40)
        self.assertGreater(len(spans), 1)
        self.assertEqual((spans[0][0], spans[-1][1]), (0, 40))
        self.assertTrue(all(b - a >= clio.SHORTEST for a, b in spans))
        self.assertTrue(all(a2 == b1 for (_a, b1), (a2, _b) in zip(spans, spans[1:])))
        self.assertEqual(clio._spans(hill, 0, 12), [(0, 12)])                # too short to cut
        self.assertEqual(clio._spans(hill, 0, 28, shortest=clio.LEAD_SHORTEST), [(0, 28)])     # a tune is left whole
        self.assertEqual(clio._spans({(0, 60): 5}, 0, 40), [(0, 40)])        # levels per note: nothing to follow
        text, _sounded = clio._track([(0, 40, [36])], 0, 48, 16, hill)
        self.assertGreaterEqual(text.count("c2"), 2)                         # struck again where the music swells


def hummed(text, tempo, rate=22050, octave=-12, cents=0.0, vibrato=0.3, scoop=1.5, noise=0.01, drift=0.0, seed=1):
    """A made-up voice humming a tune: partials under a formant, a slide up into every note, a wavering pitch, a
    breath of silence before the next note, never quite on the beat, tuned ``cents`` off and drifting."""
    from eigenchip.readers.tune import read_tune
    rnd = np.random.default_rng(seed)
    score = read_tune(text, tempo)
    beat = 60.0 / tempo
    total = int((score.length * beat + 0.9) * rate)
    out = np.zeros(total)
    for n in score.notes:
        at = int((0.4 + n.start * beat + rnd.normal(0, 0.012)) * rate)
        dur = n.dur * beat * (0.82 if n.dur <= 1 else 0.9)
        t = np.arange(int(dur * rate)) / rate
        pitch = n.pitch + octave + cents / 100.0 + drift * n.start / max(1.0, score.length)
        f = 440.0 * 2 ** ((pitch - scoop * np.exp(-t / 0.035)
                           + vibrato * np.sin(2 * np.pi * 5.5 * t) * np.minimum(1.0, t / 0.25) - 69) / 12.0)
        phase = 2 * np.pi * np.cumsum(f) / rate
        tone = sum((1.0 / h) * (1.0 + 2.0 * np.exp(-((f.mean() * h - 500.0) / 250.0) ** 2)) * np.sin(h * phase)
                   for h in range(1, 14))
        tone = tone * np.minimum(1.0, t / 0.04) * np.minimum(1.0, (dur - t) / 0.06)
        out[at:at + len(tone)] += 0.2 * tone[:total - at]
    out += noise * rnd.normal(size=total)
    return (out / np.abs(out).max() * 0.6).astype(np.float32), rate


@needs_numpy
class HumTests(unittest.TestCase):
    """A tune hummed into a microphone becomes notes for the composer."""

    ODE = "e4 e4 f4 g4 | g4 f4 e4 d4 | c4 c4 d4 e4 | e4:1.5 d4:.5 d4:2"

    def heard(self, text, sung, given, **how):
        from eigenchip.audio import hum
        from eigenchip.readers.tune import read_tune
        samples, rate = hummed(text, sung, **how)
        notes, tempo = hum.notes(samples, rate, given)
        want = [(n.start, n.pitch) for n in read_tune(text).notes]
        return [(s, p) for s, _d, p in notes], want, tempo, notes

    def test_a_low_voice_is_written_down_in_the_tunes_octave(self):
        got, want, tempo, notes = self.heard(self.ODE, 100, 100)                  # hummed an octave below
        self.assertEqual(got, want)
        self.assertEqual(tempo, 100.0)
        self.assertEqual([d for _s, d, _p in notes[:8]], [1.0] * 8)               # a breath is not a rest
        self.assertEqual(notes[12][1:], (1.5, 64))

    def test_the_tempo_is_fitted_near_the_one_set(self):
        for sung in (88, 112):
            got, want, tempo, _notes = self.heard(self.ODE, sung, 100)
            self.assertEqual(got, want, sung)
            self.assertAlmostEqual(tempo, sung, delta=1.0)

    def test_a_voice_out_of_tune_wavering_and_sinking(self):
        from eigenchip.audio import hum
        for how in ({"cents": -30}, {"vibrato": 0.6}, {"drift": -0.5}, {"cents": 40, "drift": -1.0}):
            got, want, _tempo, _notes = self.heard(self.ODE, 100, 100, **how)
            self.assertEqual(got, want, how)
        samples, rate = hummed(self.ODE, 100, cents=-30)
        _times, off = hum.tuning(samples, rate)
        self.assertAlmostEqual(float(off.mean()), -0.3, delta=0.05)               # the voice's own tuning is measured
        bent, clock = hum.in_tune(samples, rate)
        self.assertLess(len(bent), len(samples))                                  # played a little faster: higher
        self.assertAlmostEqual(clock(len(bent) / float(rate)), len(samples) / float(rate), delta=0.01)

    def test_quick_notes_rests_and_a_whistle(self):
        quick = "g4:.5 a4:.5 b4 d5:.5 b4:.5 a4 | g4:2 e4 d4 | g4:.5 a4:.5 b4 d5:.5 b4:.5 a4 | g4:3 .:1"
        for how in ({}, {"octave": 12, "vibrato": 0.1, "scoop": 0.5}):
            got, want, _tempo, _notes = self.heard(quick, 104, 100, **how)
            self.assertEqual(got, want, how)
        _got, _want, _tempo, notes = self.heard("c4 c4 g4 g4 | a4 a4 g4 . | f4 f4 e4 e4 | d4 d4 c4:2", 100, 100)
        self.assertEqual(notes[6][:2], (6.0, 1.0))                                # a real rest stays a rest
        self.assertEqual(notes[7][0], 8.0)

    def test_a_coarser_grid_forgives_more(self):
        from eigenchip.audio import hum
        samples, rate = hummed("g4:.5 a4:.5 b4 d5:.5 b4:.5 a4 | g4:2 e4 d4", 104, noise=0.05, scoop=2.5)
        fine, _tempo = hum.notes(samples, rate, 100)
        eighths, _tempo = hum.notes(samples, rate, 100, None, 0.5)
        quarters, _tempo = hum.notes(samples, rate, 100, None, 1.0)
        self.assertEqual([p for _s, _d, p in fine], [67, 69, 71, 74, 71, 69, 67, 64, 62])
        self.assertEqual([(s, p) for s, _d, p in eighths], [(s, p) for s, _d, p in fine])   # eighths hold this tune
        self.assertTrue(all(s % 0.5 == 0 and d % 0.5 == 0 for s, d, _p in eighths))
        self.assertTrue(all(s % 1 == 0 and d % 1 == 0 for s, d, _p in quarters))
        self.assertLess(len(quarters), len(fine))                                 # quarters cannot write the quick notes
        with self.assertRaisesRegex(ValueError, "sixteenths"):
            hum.notes(samples, rate, 100, None, 0.33)

    def test_nothing_hummed_and_the_session(self):
        from eigenchip.app import Session
        from eigenchip.audio import hum
        with self.assertRaisesRegex(ValueError, "No tune was heard"):
            hum.notes(np.zeros(22050, dtype=np.float32), 22050, 100)
        samples, rate = hummed("c4 c4 g4 g4 | a4 a4 g4:2 | f4 f4 e4 e4 | d4 d4 c4:2", 96)
        session = Session()
        facts = session.open_hum(samples, rate, tempo=100)
        self.assertEqual((facts["hummed"], facts["tempo"]), (14, 96.0))
        self.assertEqual(facts["written"][:3], [[0.0, 1.0, 60], [1.0, 1.0, 60], [2.0, 1.0, 67]])
        view = session.arrange("expand", 4, style="calm")
        self.assertEqual((view["key"], view["tune_text"][:26]), ("C major", "c4 c4 g4 g4 | a4 a4 g4:2 |"))
        with self.assertRaisesRegex(ValueError, "Nothing was recorded"):
            session.open_hum(np.zeros(0, dtype=np.float32), rate)


class ReaderTests(unittest.TestCase):
    def wav(self, name, **kw):
        score = piece(name)
        path = tmp(name + ".wav")
        decode.write_wav(path, synth.render(score, "band", drums=False, **kw))
        return score, path

    def test_audio_becomes_the_same_grid_as_the_midi_file(self):
        score, path = self.wav("waltz")
        heard = read(path, meter=(3, 4))
        self.assertEqual(heard.info["source"], "audio")
        self.assertFalse(heard.info["tempo_given"])
        self.assertAlmostEqual(heard.tempo, score.tempo, delta=0.5)
        want = {(n.start, n.pitch) for n in quantize(score).pitched}
        got = {(n.start, n.pitch) for n in quantize(heard).pitched}
        self.assertGreaterEqual(len(want & got) / float(len(want)), 0.95)
        self.assertLessEqual(len(got - want), 3)
        song = clio.to_song(arrange(quantize(heard), "roles-arp"), quantize(heard))
        self.assertEqual(clio.validate(song), [])

    def test_a_given_tempo_is_used_as_it_is(self):
        score, path = self.wav("bach_prelude")
        guessed = read(path)
        self.assertEqual(evaluate.tempo_verdict(guessed.tempo, score.tempo), "double")  # the known weakness
        told = read(path, tempo=72)
        self.assertEqual((told.tempo, told.info["tempo_given"]), (72.0, True))
        grid, heard = quantize(score), quantize(told)
        res = metrics.evaluate(grid, arrange(heard, "skyline"))
        self.assertGreaterEqual(res["pitch_recall"], 0.9)
        self.assertGreaterEqual(res["onset_f1"], 0.9)

    def test_command_line(self):
        _score, path = self.wav("triplets")
        mid, song = tmp("out.mid"), tmp("out.json")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(["transcribe", path, "-o", mid, "--transcriber", "peaks"]), 0)
            self.assertEqual(cli.main(["convert", path, "-o", song, "--tempo", "100", "--quality", "fast",
                                       "--clean", "strict", "--no-effects"]), 0)
            self.assertEqual(cli.main(["info", path]), 0)
            self.assertEqual(cli.main(["transcribe", os.path.join(CORPUS, "waltz.mid")]), 1)
        self.assertIn("transcribed with 'peaks'", err.getvalue())
        self.assertIn("tempo 100.0 bpm (given)", err.getvalue())
        self.assertIn("already notes", err.getvalue())
        self.assertGreater(len(read(mid).notes), 40)
        with open(song, encoding="utf-8") as f:
            self.assertIn('"patterns"', f.read())


class WithoutNumpyTests(unittest.TestCase):
    def test_midi_never_needs_numpy(self):
        code = ("import sys; sys.modules['numpy'] = None; sys.path.insert(0, %r)\n"
                "from eigenchip import cli\n"
                "from eigenchip.readers import read\n"
                "assert len(read(%r).notes) > 10\n"
                "try:\n    read('song.wav')\nexcept ValueError as e:\n    assert 'NumPy' in str(e), e\n"
                "else:\n    raise SystemExit('no error')\n" % (ROOT, os.path.join(CORPUS, "waltz.mid")))
        done = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
