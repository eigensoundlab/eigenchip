# eigenchip

**Reducing music to a few chip voices.**

A piece of music may have dozens of notes sounding at once. A simple chip synthesizer has
three or four voices, each playing one note at a time. *eigenchip* is a research toolkit
for the step in between: deciding which notes matter, and comparing different ways of
deciding.

Daniel Sandner ([ORCID 0000-0002-1041-814X](https://orcid.org/0000-0002-1041-814X)) ·
[eigensoundlab](https://github.com/eigensoundlab)

**Try it in the browser: <https://eigensoundlab.github.io/eigenchip/>** - nothing to
install, and your files stay on your computer.

Status: early (0.5.0). It reads MIDI files and, by transcribing them, sound files (WAV,
Ogg, MP3, FLAC, M4A...); has three arrangement strategies and four transcription
baselines, finds drums, sorts transcribed notes into lines, and describes risers, falls,
swells and impacts apart from the notes; writes songs for the [CLIo](https://github.com/eryxgames/CLIo) game engine;
and scores every stage on a small corpus. Python 3.8+. The MIDI path has no dependencies;
the audio path needs NumPy, and ffmpeg for anything but WAV.

## Try it

```
python -m eigenchip info    corpus/ode_to_joy.mid
python -m eigenchip compare corpus/crossing.mid --melody 0 --bass 2
python -m eigenchip convert corpus/ode_to_joy.mid -o ode.json --name ode
```

`convert` writes a CLIo song; with `--name` it is wrapped ready to paste into a game's
`music.json`. To hear a result, point `render` at a CLIo checkout, which supplies the
synthesizer:

```
python -m eigenchip render ode.json ode.wav --clio /path/to/CLIo
```

### From a sound file

```
pip install numpy                       # the only extra; ffmpeg must be on the PATH for ogg, mp3, flac...
python -m eigenchip transcribe song.ogg -o song.mid      # what did it hear? open the MIDI and look
python -m eigenchip convert    song.mp3 -o song.json --tempo 96 --meter 3/4
```

Audio is *transcribed* - turned back into notes - before anything else happens, and that
is a guess. Give `--tempo` when you know it: a wrong tempo spoils everything after it, and
the estimate is sometimes twice or half the truth. `--transcriber` picks the method:

| Transcriber | Idea |
| --- | --- |
| `mono` | Follow the single most prominent pitch along a smooth path. For an unaccompanied tune. |
| `peaks` | Find the strongest pitch in each moment, remove its overtones, look again (harmonic summation with cancellation). |
| `nmf` | Explain each moment as a mix of fixed harmonic templates, several tone colours per pitch (non-negative matrix factorisation). The default. |
| `pads` | The same templates read slowly: only what lasts counts, and attacks are not looked for. For drones, pads and slow swells. |

Around the transcriber:

- **Deep tones.** Notes are reported from A0 (27.5 Hz) up. Below about 80 Hz a second,
  much longer analysis window (0.74 s) is used, because neighbouring notes that low
  cannot be told apart in less.
- **Drums.** Kick, snare and hi-hat are looked for by the shape of each attack and put on
  the drum track (`--no-drums` turns this off). A rule of thumb for simple kits, not a
  drum transcriber.
- **Lines.** A transcription is one heap of notes. They are sorted into up to five lines
  by pitch and continuity, so that arrangers have something like channels again
  (`--lines 0` leaves them on one channel).
- **Effects.** Four gestures of film and ambient music are looked for directly and kept
  apart from the notes: a *riser* (a pitch or a hiss sliding up), a *fall* (the same,
  down), a *swell* (a sound that grows and is cut off, like one played backwards) and an
  *impact* (a crack with a long low tail). The CLIo song plays them on tracks of their
  own: a sweep as a staircase of short notes, because the song format has no pitch
  slide; a swell as one note with a slow attack; an impact as a low note that dies away.
  `--no-effects` turns this off.

Two settings trade one thing for another:

| Setting | Choices | What you trade |
| --- | --- | --- |
| `--quality` | `fast`, `standard`, `fine` | Time for detail. On the corpus `fast` takes about half the time and loses two points of F1; `fine` takes about three times as long and gains one. `fine` mostly buys precision. |
| `--clean` | `off`, `light`, `strict` | Stray notes for real ones. `light` removes only what is very likely a mistake: scraps of a held note, a faint copy a semitone beside a note, short faint notes on a drum hit, the staircase a sweep leaves behind. `strict` also removes faint short notes and allows six notes at once: with drums, precision rises from 0.60 to 0.71 and recall falls from 0.85 to 0.74. |

These are plain, readable baselines, not the state of the art. Instruments are not
recognised, the meter is assumed, and the effect detector was fitted to clean synthetic
effects: expect it to miss and to misname things in a real mix.
Read [RESULTS-audio.md](RESULTS-audio.md) before trusting it.

### In the browser

`web/` is a static page that runs this package, unchanged, inside the browser. Open a MIDI
or sound file (or take a corpus piece, as written or played by the test synthesizer), and
it draws the notes it found against the voices the chip plays, lets you switch between
the original and the chip version while it plays, scores every arranger, and offers the
CLIo song, the transcription and the chip sound for download. For sound files you choose
how closely it listens and how hard it tidies the notes; sweeps, swells and impacts are
drawn on the roll as slanted lines, wedges and strokes. Nothing is uploaded: the
analysis is done by Python compiled to WebAssembly ([Pyodide](https://pyodide.org)) on
your own machine. That makes listening slow: transcribing a sound file takes about as
long as the music lasts, where the command line needs a couple of seconds.

To publish it from a fork: repository Settings, Pages, "Deploy from a branch", branch
`main`, folder `/ (root)`. To run it locally:

```
python -m http.server 8000        # in the repository root
# then open http://localhost:8000/web/
```

The page fetches Pyodide and NumPy from the jsDelivr CDN, so it needs a connection the
first time. If you add or remove a module of the package, run `python web/build_manifest.py`.

## How it is put together

```
 reader            quantize           arranger                writer
.mid  ──▶  Score  ────────▶  Grid  ────────────▶  Arrangement  ────▶  CLIo song (JSON)
.wav  ──▶  notes in          notes in             lead, bass, inner
.ogg       beats             steps                or chords, drums
.mp3 ...                       │                       │
                               └──────  metrics  ──────┘
                                  what survived?

 audio reader:  decode ──▶ spectrogram ──▶ transcriber ──▶ notes in seconds
                                └──▶ onset strength ──▶ tempo, first beat ──▶ notes in beats
```

Each stage has one job and a plain data structure on either side (`eigenchip/ir.py`), so
any stage can be replaced without touching the others. The arrangers are the research;
everything else exists to feed them and to judge them.

| Arranger | Idea |
| --- | --- |
| `skyline` | Pitch only: the top line is the lead, the bottom line the bass, then the top of what is left. |
| `roles` | Work out which *channel* carries the melody and which the bass from simple statistics, and take the lead only from the lead channel. |
| `roles-arp` | As `roles`, but everything that is not lead or bass becomes one chord per half bar, played as an arpeggio. |

## What has been found so far

Scores for every arranger on every piece are in **[RESULTS.md](RESULTS.md)**, regenerated
by `python experiments/run.py`. Dated notes are in
[docs/research-log.md](docs/research-log.md). In brief:

- Finding the melody by pitch alone is not safe: `skyline` loses it when anything sits
  above the tune. `roles` used to lose it to a busy broken-chord accompaniment; since it
  learnt that a tune moves by step and a broken chord by leap, it gets both cases right.
  A round, where every part is the tune in turn, still defeats it.
- Turning the accompaniment into arpeggiated chords keeps more of the harmony than a
  third melodic line, at some cost to the accompaniment's rhythm.
- Three-note chords are a hard ceiling for dense harmony.

From audio ([RESULTS-audio.md](RESULTS-audio.md)), on clean synthetic recordings of the
same corpus:

- Template matching (`nmf`) finds about nine notes in ten and invents about one in ten;
  the simpler `peaks` is clearly behind, mostly on chords.
- Compressing the audio to MP3 or Ogg costs almost nothing.
- Drums still cost precision, though less than before: on the two pieces with a drum
  track it falls from 0.70 to 0.58 and from 0.73 to 0.61. The drum hits themselves are
  found with almost no false alarms, but a fifth to a third of them are missed.
- Sub-bass is only readable with the long window: on the drone piece all three notes
  between 29 and 37 Hz are found with it and none invented; without it, four or five
  wrong neighbours appear beside them.
- For sustained sound the slow reading (`pads`) is clearly better than `nmf`, which
  shreds a swelling pad into fragments; on ordinary music it is useless by design.
- Tempo is right on eight pieces of ten, doubled on one, and wrong on the drone piece,
  which has no pulse to find.
- Effects wreck a transcription and can be taken out again. Laid over a piece, eight
  effects cut the precision of the notes roughly in half (0.90 to 0.40 on the drone, 0.59
  to 0.32 on a tune with drums), because a sweep is read as a spray of short notes. Found
  as effects and cleaned away, most of that comes back (0.74 and 0.63). The detector
  finds all eight alone, five to seven of eight over music, and reported nothing in
  eleven minutes of the plain corpus - all of it on synthetic effects.
- Listening more closely helps little: three times the work buys one point of F1.
- Cleaning does not rescue the lines. Light cleaning is safe and helps mostly where there
  are drums; strict cleaning trades recall for precision one for one. Neither changes
  how much of the melody the arranger keeps (0.72, 0.72, 0.70): the mistake that breaks
  lines is a held note cut in two, and in a note list that looks like a repeated note.
- Sorting notes into lines works on clean notes and barely matters on transcribed ones.
  With the channels of the MIDI files thrown away, the lead voice keeps 0.77 of the
  melody; with lines found again, 0.85; with the true channels, 0.88. From audio the
  same step changes almost nothing (0.73 against 0.72): the transcriber's stray notes
  break the lines up.

## What the scores mean, and what they do not

The measures compare notes with notes (`eigenchip/metrics.py`): is the melody in the lead
voice, is the bass in the bass voice, how much pitch content was kept, how much was
invented, does each beat have the same harmony, do notes start where they started.

They do not listen. A high score means the right pitches are present at the right time; it
does not mean the result sounds good. Two limits to keep in mind:

- Scores are taken against the source *after* it has been snapped to the grid, so damage
  done by the grid itself (triplets, swing) is reported separately and not scored.
- The corpus is nine short pieces, mostly written to break things. It shows how methods
  fail; it does not show how they perform on real repertoire.
- The audio scores are taken on the corpus played by eigenchip's own small synthesizer:
  dry, exactly in tune, every note cleanly struck. They are an upper bound. Nothing here
  has been measured on a recording of real instruments yet.

## The corpus

`corpus/build.py` writes every piece from note lists, so the answers (which channel is
the melody, which is the bass) are known exactly and the files can be rebuilt bit for
bit. The tunes are in the public domain or were written for this project. To add a piece,
add a function there and run it; please use only material that is public domain or your
own.

## Adding an arranger

Create `eigenchip/arrangers/yours.py` with `NAME`, `SUMMARY` and
`arrange(grid, voices=3) -> Arrangement`, and list it in `eigenchip/arrangers/__init__.py`.
It then appears in `convert --arranger`, in `compare` and as a new row in the results.
Run `python experiments/run.py` and read the diff of `RESULTS.md`: that diff is the
experiment.

## Directions

- **Finding the melody**: a detector that survives both a pad above the tune and a busy
  accompaniment below it.
- **Harmony**: four-note chord voices; chord windows that follow the harmonic rhythm;
  recognising an arpeggio in the source and storing it as a chord.
- **Structure**: finding repeated passages that are not aligned to four-bar blocks.
- **Timbre**: choosing waveform and envelope from the source instrument.
- **Rhythm**: grids for triplets and swing; a measure taken against the unquantised source.
- **Lines that survive a noisy transcription**: the separator works on clean notes and
  not yet on heard ones. Cleaning the note list did not help; telling a held note from a
  repeated one has to happen earlier, where the sound is still at hand.
- **Effects in real mixes**: the detector knows four clean gestures. Real risers are
  layered, filtered and drowned in reverb; sweeps in the bass are not seen at all; and an
  impact over a rhythm section is hard to tell from a kick and a bass note together.
- **A target that can slide**: CLIo songs have no pitch slide or volume curve, so sweeps
  become staircases. A slide in the song format would let effects be played as they are.
- **Slowly changing timbre**: filter sweeps and evolving pads still have no description.
- **Drums**: missed hits when a hat and a snare coincide; toms and cymbals; removing
  the drums from the sound before the pitched analysis instead of working around them.
- **Harder audio**: recordings of real instruments, reverberation, detuning; a trained
  transcription model as an optional reader, measured on the same table as the baselines.
- **More readers**: tracker modules.
- **Style, not copy**: extract only key, tempo and chords, and have a generative composer
  write new music from them.
- **Listening**: a protocol for judging results by ear, to find out which of the symbolic
  measures agree with listeners.

## Tests

```
python -m unittest discover -s tests
```

The audio tests are skipped without NumPy, and the compressed-format tests without ffmpeg.

Set `CLIO_HOME` to a CLIo checkout to also check that every converted song plays in the
real synthesizer.

## Citing

See [CITATION.cff](CITATION.cff). A DOI will be added when a release is archived.

## Licence

[Apache-2.0](LICENSE). Copyright 2026 Daniel Sandner.
