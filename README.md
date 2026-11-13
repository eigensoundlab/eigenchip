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

Status: early (0.3.0). It reads MIDI files and, by transcribing them, sound files (WAV,
Ogg, MP3, FLAC, M4A...); has three arrangement strategies and three transcription
baselines; writes songs for the [CLIo](https://github.com/eryxgames/CLIo) game engine;
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

These are plain, readable baselines, not the state of the art. What comes out is one
piano roll: no instruments, no drums, an assumed meter. Read
[RESULTS-audio.md](RESULTS-audio.md) before trusting it.

### In the browser

`web/` is a static page that runs this package, unchanged, inside the browser. Open a MIDI
or sound file (or take a corpus piece, as written or played by the test synthesizer), and
it draws the notes it found against the voices the chip plays, lets you switch between
the original and the chip version while it plays, scores every arranger, and offers the
CLIo song, the transcription and the chip sound for download. Nothing is uploaded: the
analysis is done by Python compiled to WebAssembly ([Pyodide](https://pyodide.org)) on
your own machine, which also makes it several times slower than the command line.

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

- Neither way of finding the melody is safe. `skyline` loses it when anything sits above
  the tune; `roles` loses it to a busy broken-chord accompaniment. No strategy here gets
  both cases right, which makes that the first problem to solve.
- Turning the accompaniment into arpeggiated chords keeps more of the harmony than a
  third melodic line, at some cost to the accompaniment's rhythm.
- Three-note chords are a hard ceiling for dense harmony.

From audio ([RESULTS-audio.md](RESULTS-audio.md)), on clean synthetic recordings of the
same corpus:

- Template matching (`nmf`) finds about nine notes in ten and invents about one in ten;
  the simpler `peaks` is clearly behind, mostly on chords.
- Compressing the audio to MP3 or Ogg costs almost nothing.
- Drums cost a lot: they are heard as notes. On the two pieces with a drum track,
  precision falls from 0.71 to 0.45 and from 0.74 to 0.62.
- Tempo is right on eight pieces of nine, and doubled on the ninth.
- The notes survive better than the roles do. A transcription has no channels, so the
  arrangers can no longer tell the tune from the accompaniment by where it came from:
  the lead voice keeps about two thirds of the melody from audio against three quarters
  from MIDI, although the transcription itself contains nearly all of it.

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
- **Voices from a piano roll**: splitting a transcription into lines (by pitch
  proximity and continuity), so that arrangers have something like channels again.
- **Drums**: separating them before transcription, and transcribing them as drums.
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
