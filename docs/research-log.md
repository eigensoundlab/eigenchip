# Research log

Dated notes on what was tried and what it showed. Newest first. Keep entries short; the
numbers live in `RESULTS.md` and in the history of that file.

## 2026-11-13 - deep tones, drums, lines, and a melody rule

**Set-up.** The linear spectrogram was replaced by one spaced in pitch (three bins per
semitone, A0 to 5.5 kHz), with a second, 0.74 s window blended in below 55-80 Hz. A slow
reading of the same activations (`pads`), a rule-of-thumb drum detector, and a greedy
line separator were added. A tenth piece, *Deep drone*, tests sustained sound and
sub-bass. Numbers in `RESULTS-audio.md` and `RESULTS.md`.

**What the tables show.**

- *Low notes need time.* At 30-40 Hz a semitone is about 2 Hz wide; a 186 ms window
  cannot separate that, whatever is done afterwards. With the long window the three
  sub-bass notes of the drone piece are found and nothing is invented; without it four or
  five wrong neighbours appear. The long window is kept below 80 Hz only: when it also
  covered the bass register, fast bass lines smeared into their neighbours.
- *Pooling into pitch bins changes what a template must look like.* Low partials are
  wide in this picture and high ones narrow. Templates have to follow that (bumps as wide
  as a spectral peak really is there), but sums of evidence must not: a wide bump gathers
  more, and `peaks` and `mono` drifted an octave down until every bump was given the same
  area. Getting this wrong cost more accuracy than anything else in this round.
- *A phantom bass has no fundamental.* With the range extended downwards, chords were
  increasingly "explained" by one very low note whose overtones are the chord. Scaling
  each activation by the energy at its own fundamental removes most of these.
- *`pads` is a different reading, not a better one.* On the swelling pad it scores 0.90
  where `nmf` scores 0.24, because `nmf` cuts a slow attack into pieces; on every ordinary
  piece it scores near zero, because it ignores anything shorter than 0.4 s.
- *Drums are easy to find and hard to remove.* Flat, quickly fading bursts are drums with
  almost no false alarms on three tone colours, but 18-33% of hits are missed (a hi-hat
  under a snare, for one, is reported as the snare alone). A plucked attack is itself
  a short burst of noise; only a strict flatness threshold keeps plucked notes from
  being heard as snares. Knowing where the kicks are lets the note cutter demand longer
  low notes there, which recovers part of the precision drums cost (0.45 to 0.58 on the
  worst piece).
- *The melody problem of the first entry is solved for clean notes.* A tune moves mostly
  by step, a broken chord only by leap. With that, and with activity weighted up so that
  a pad's top note is not mistaken for a tune, `roles` passes both `crossing` and
  `twinkle`. The round still fails, as it should: it has no single melody.
- *Lines: yes on notes, not yet on sound.* With true channels the lead keeps 0.88 of the
  melody, with none 0.77, with lines found again 0.85. From audio, finding lines changes
  0.73 to 0.72. The separator is fed fragments and ghosts, and a greedy rule cannot
  recover from them. This was expected to be the big win of the round and is not.
- *The new analysis is about two points less accurate on the old pieces* (`nmf`, `band`)
  and several times cheaper. That trade was taken for the browser.

**What the tables cannot show.**

- Soundscapes. *Deep drone* is a soundscape only in the sense of being slow and low. It
  has no pitch glides, no noise sweeps, no evolving timbre - the things that made the
  owner's first real test piece hard. Nothing here follows a riser.
- Real drums. The detector was fitted to three synthetic sounds.
- Whether the lines are musically right; only whether successive notes stay together.

**Next.**

1. Clean the transcription before separating lines (merge fragments, drop ghosts), then
   measure lines from audio again.
2. A description for what is not notes: pitch contours for glides, a noise level over
   time. This needs a target that can play it; CLIo songs cannot slide.
3. Real audio with known notes (BabySlakh, MusicNet), as planned.
4. Hi-hat under snare; remove drums from the sound instead of working around them.

## 2026-11-13 - audio: three transcription baselines

**Set-up.** The corpus played by a small additive synthesizer in four tone colours
(`sine`, `square`, `pluck`, and `band`, where each channel gets its own), transcribed by
`mono`, `peaks` and `nmf`, and compared with the notes that were played (right pitch,
onset within 50 ms). Numbers in `RESULTS-audio.md`.

**What the table shows.**

- *Fixed templates go a long way on clean audio.* `nmf` is ahead in every tone colour.
  `peaks` loses mainly on the pieces with thick chords; a likely cause, not yet checked,
  is that cancelling one note's overtones removes parts of the other notes with it.
- *Pure sines are the hardest colour for summing methods, not the easiest.* With no
  overtones, nothing separates a tone from the octave below it except the missing
  fundamental. Weighting each candidate by the energy at its own fundamental helped
  `mono` and `peaks` a great deal; sines remain their worst colour.
- *Which pitch and when are two different measurements.* A 186 ms window resolves low
  notes but smears time; onsets are taken from a 46 ms analysis instead. Repeated notes
  are invisible in the long window: they are found as a notch in the pitch's own level
  at an onset. This only works because the test notes are let go before the next begins
  (90% of their length). Perfect legato repeats would be merged.
- *Drums are the largest single problem.* On the piece hit hardest, the invented notes
  are of two kinds: short low notes where the kick is (a kick *is* a short low tone), and
  faint notes scattered through the rest. Median-filter separation is applied before
  transcription and removes neither.
- *Lossy compression is harmless* at the bit rates tried, down to 32 kbit/s MP3.
- *Tempo doubling* on the Prelude: even sixteenths have no accent to say where the beat
  is. The fit of tempo to transcribed onsets fixes small errors, not this one.
- *The chain loses the roles, not the notes.* `nmf` transcriptions contain nearly all of
  the melody, yet the arrangers put only about two thirds of it in the lead voice: with
  everything on one channel, `roles` has nothing to choose between and falls back on
  pitch height. `mono`, which hears only the most prominent line, keeps more melody than
  either multi-pitch method - and no bass at all.

**What the table cannot show.**

- Anything about recordings. The synthesizer is dry, in tune and exactly on time; real
  instruments have vibrato, reverberation, soft attacks and overtones that drift. These
  scores are a ceiling.
- Durations beyond the frame measure; note-offs are not scored separately.
- Whether a mistake matters musically: a wrong octave in the bass and a wrong note in the
  tune count the same.

**Next.**

1. Voice separation on the piano roll, so that arrangers get lines instead of one heap.
   This is now the weakest link of the audio chain.
2. Drums: detect and remove kicks before pitch analysis; transcribe kick, snare and hat
   into the drum track instead of ignoring them.
3. A harder test bed: detuned, reverberant, layered renderings, then recordings with
   aligned MIDI.
4. A trained transcription model as an optional reader, on the same table.

## 2026-11-13 - baseline: three arrangers, nine pieces

**Set-up.** `skyline`, `roles`, `roles-arp` at three voices on a sixteenth-note grid,
scored against the quantised source.

**What the table shows.**

- *Neither lead detector is safe.* `skyline` loses the melody completely when a pad sits
  above it (`crossing`). `roles` gets that right but loses the melody completely on
  `twinkle`, where it mistakes the Alberti bass for the tune: a broken chord is
  monophonic, busy and always moving, which is exactly what the heuristic rewards.
- *Arpeggiated chords keep the most.* `roles-arp` retains at least as much of the
  original pitch content as a third melodic line on every piece, and clearly more
  wherever the harmony is thicker than three voices. The cost is in rhythm (the
  accompaniment's own rhythm is replaced by the arpeggio) and in precision (a chord held
  for half a bar sounds notes longer than the source did); both are most visible on
  `waltz` and `frere_jacques`.
- *Three notes per chord is a ceiling.* On `dense_chords` even `roles-arp` keeps under
  two thirds of the pitch content.
- *A round has no single melody.* On `frere_jacques` every method fails the melody
  measure; the measure itself is questionable there.

**What the table cannot show.**

- Damage done by the grid. Scores compare against the *quantised* source, so `triplets`
  scores perfectly although its rhythm has been bent. The quantisation error is reported
  beside each piece but is not part of any score.
- Whether any of it sounds good. Nothing here has been judged by ear.

**Next.**

1. A lead detector that passes both `crossing` and `twinkle` (penalise cyclic,
   low-entropy figures; reward stepwise motion and phrase structure).
2. A measure that compares against the unquantised source.
3. Chord voices of four notes, and chord windows that follow the harmonic rhythm
   instead of a fixed half bar.
