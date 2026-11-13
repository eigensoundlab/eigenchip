# Changelog

## 0.4.0 - 2026-11-13

Deeper, with drums and lines - and a page that says what it is doing.

- **A new picture of the sound.** The spectrogram is now spaced evenly in pitch, three
  bins to the semitone from A0 up, with a second 0.74 s window for everything below
  about 80 Hz. Notes down to 27.5 Hz can be reported, and sub-bass notes a semitone apart
  can be told apart. The analysis is also several times smaller, so everything after it
  is faster: the audio experiment runs in 70 s instead of 107, with one more piece.
- **`pads`**, a fourth transcriber for sustained sound: the template activations read
  slowly, without looking for attacks.
- **Drums.** `find_drums` reports kick, snare and hi-hat from the shape of each attack;
  the audio reader puts them on the drum track. Low notes that begin on a kick must last
  longer to count.
- **Lines.** `eigenchip.voices.separate` sorts a heap of notes into up to five lines by
  pitch and continuity; the audio reader applies it. Arrangers take the tune from guessed
  lines but still take the bass from the bottom.
- **`roles` finds the tune over a broken-chord accompaniment**: stepwise motion and
  activity now count. Melody kept by `roles` and `roles-arp` over the corpus rises from
  0.75 to 0.88.
- A tenth corpus piece, *Deep drone*: slow pads over a sub-bass down to 29 Hz.
- Workbench: a progress bar with the current step, a **Stop** button (it ends the engine
  and starts a fresh one), the `pads` choice, and drum hits in the summary.
- Results: new tables for lines, drums, and sustained sound and deep tones.

Changed numbers: `nmf` on the `band` colour is at F1 0.88 where 0.3.0 reported 0.92. The
corpus has a piece more and the analysis is different, so the two are not the same
measurement; on the nine old pieces the new analysis is about two points lower.

## 0.3.0 - 2026-11-13

A workbench in the browser.

- `web/`: a static page that runs the package unchanged in the browser (Python through
  Pyodide, in a worker). Open a MIDI or sound file, or take a corpus piece as written or
  played by the test synthesizer; see the notes that were found against the voices the
  chip plays; switch between the original and the chip version while it plays; compare
  the arrangers in a table and switch by choosing a row; download the CLIo song, the
  transcription as MIDI and the chip sound. Files are not uploaded anywhere.
- The chip sound comes from CLIo's own synthesizer, vendored at tag `v2.0.0`.
- `eigenchip.app.Session`: the same steps as a small Python API returning plain data.
- Serving: GitHub Pages from the repository root (`index.html` forwards to `web/`).

## 0.2.0 - 2026-11-13

Audio in: sound files can be read, by transcribing them.

- Decoding: WAV (8/16/24/32-bit PCM, 32/64-bit float, extensible) with the standard
  library and NumPy; Ogg, Opus, MP3, FLAC, M4A/AAC, AIFF and others through ffmpeg.
- Analysis: spectrogram, harmonic-percussive separation, onset strength, tempo by
  autocorrelation, and a fit of tempo and first beat to the transcribed onsets.
- Three transcription baselines behind one interface: `mono` (predominant pitch on a
  smoothed path), `peaks` (harmonic summation with cancellation), `nmf` (fixed harmonic
  templates). One shared routine cuts activations into notes and detects repeated notes.
- A reference synthesizer that plays the corpus in several tone colours, so that the
  audio has known answers; note-level and frame-level transcription scores.
- `experiments/audio.py` writes `RESULTS-audio.md`: transcribers by tone colour, the
  effect of drums and of lossy compression, tempo, and the whole chain from audio to
  arrangement against the same arrangement from MIDI.
- Command line: `transcribe` (sound file to MIDI); `convert`, `compare` and `info` accept
  sound files, with `--transcriber`, `--tempo`, `--offset` and `--meter`.
- NumPy is needed for audio only (`pip install eigenchip[audio]`); the MIDI path still
  has no dependencies.

## 0.1.0 - 2026-11-13

First version: the frame that later experiments hang on.

- A common note model: `Score` (as read), `Grid` (snapped to steps), `Arrangement` (a few
  monophonic voices, a chord voice and drums).
- A Standard MIDI File reader and writer using only the standard library.
- Three arrangers: `skyline` (pitch only), `roles` (guess the melody and bass channels),
  `roles-arp` (roles, with everything else as arpeggiated chords).
- A writer for CLIo songs, with pattern detection.
- Symbolic measures of what survived: melody, bass, pitch content, harmony, rhythm.
- A nine-piece corpus with known answers, built from source.
- `experiments/run.py`, which scores every arranger on every piece into `RESULTS.md`.
- Command line: `info`, `convert`, `compare`, `render`.
