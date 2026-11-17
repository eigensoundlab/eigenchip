# Changelog

## 0.16.0 - 2026-11-17

A voice is switched on or off at once.

- **No more waiting for a voice.** Switching a voice on or off, or soloing it, used to
  make the whole chip version anew in Python and then swap the sound - a second or more
  on a long piece, during which the old sound played on: bars of delay. Now every voice
  of the song is rendered once as its own sound (`Session.chip_stems`, on the
  synthesizer's `render_tracks`), all are started together, and each sits behind its own
  volume: a switch is heard within a few hundredths of a second, while the piece plays.
- The sound that is taken away (*Chip sound (.wav)*) is mixed in the page from the voices
  that are on.
- The page's synthesizer is CLIo 2.2.2's; the texts name that version for the newer
  instrument settings.

## 0.15.0 - 2026-11-17

The rest of the orchestra, a short tune made long, the plain chip, and a tempo that is heard.

- **A hummed tune at its own tempo.** [Playhead](https://github.com/eigensoundlab/playhead)'s
  analysis (one file of it, `web/vendor/playhead`, fetched when you first hum) hears the
  tempo of what was hummed, so none has to be set before. It is on unless switched off;
  where it is not sure of a pulse, the tempo set is taken as before.
- **More of the orchestra**, four genres: **epic orchestral** (a trumpet over strings and
  horns, low strings driving, kettledrums, a snare), **pastoral** (a flute over a harp,
  plucked basses, strings behind, a clarinet below the tune), **chamber** (plucked strings
  off the beat, a clarinet, a bell on top) and **cathedral** (a choir, an organ, a bell
  that tolls). Kettledrums are notes now, on the root of the chord - also in *dark
  orchestral*. The genres are listed by family: band, orchestra, electronic, space.
- **Five more sounds for the tune**: clarinet, oboe, horn, trumpet, bells.
- **A short tune made long by arrangement.** In the form, a part in brackets - `(A)` - is
  played without the tune, `A-` quietly (no bass, no drums), `A+` a tone higher. *Make it
  longer* writes such a form by itself: the first part without its tune to begin, the
  form, a quiet part, the first part again and once more a tone higher, a closing bar -
  `A A B A` becomes `(A) A A B A B- A A+` (`eigenchip/arrangers/plan.py`).
- **On the plain chip.** A tick plays any genre on the plain chip instruments - the same
  notes, no overdrive, detune, filter or room - so that the song sounds the same on every
  CLIo.
- A song says it needs CLIo 2.1 only when it really has slides or levels.

In a browser with a made-up microphone, a tune hummed at 138 with 90 set came out right
with Playhead's tempo and as nonsense at 76 without. None of the new sounds has been
listened to by anyone; the voice was synthetic.

## 0.14.0 - 2026-11-17

An orchestra, a studio, five more genres - and the tune's sound, quantising, dark mode.

- **Five more genres**: **dark orchestral** (a section of strings held wide, low strings
  driving in eighths, a horn for the tune, great drums in a hall), **acid techno** (a kick
  on every beat, hats between, stabs off the beat and a bass line in sixteenths through a
  resonant filter that closes on every note), **rock ballad** (a clean guitar picking the
  chords, a long bass, a lead that sings), **metal march** (chords on the beat, a marching
  snare, two guitars in thirds) and **neon noir** (slow synthesizer brass in seventh
  chords, a deep bass, a great deal of room).
- They rest on **three new instrument settings** of CLIo's synthesizer (2.3; the page plays
  them already): `detune` - a section instead of one player; `filter` - a resonant
  low-pass that moves over every note; `room` - early echoes around a track. An older
  CLIo plays such a song with the same notes and plainer sounds.
- **The soundscape's air is wind now**: the same noise far brighter at its source and far
  darker after the filter, and half as loud - as loud as the ambient's, which stays.
- **Another sound for the tune** (*Tune played*: soft, flute, strings), for any arranger,
  when the square lead is too sharp.
- **A song without its tune.** What is switched off on the page is left out of the song
  that is taken away (`Session.song_json(mute)`), as it already was of the sound: a
  backing for something else to play over.
- **Quantising.** Hummed and played notes go on sixteenths, eighths or quarter notes, as
  chosen; *Tidy the notes* puts a tune that is on the roll already on that note value.
- **Record in time.** One bar is counted in, a click goes on, and every key - the
  computer's or a MIDI keyboard's - is written where and as long as it was played.
- **Dark mode**, by the system's setting or the switch at the top; the screen with the
  roll is the same in both.
- Drum patterns can be laid over each other; pads can carry the seventh of the key.

Measured with [Playhead](https://github.com/eigensoundlab/playhead) as a judge that is
not eigenchip (`docs/research-log.md`): its harshness of timbre agrees with the ear - the
square lead 0.12, soft 0.03, flute 0.02 - and its loudness explains the rough air (6 dB
above the ambient's); it hears the set tempo exactly in 8 of 12 arranged pieces; and
started from the tempo it hears, a hum at any tempo from 60 to 150 is written down right
where eigenchip alone needs the tempo set within a fifth. None of the new sounds has been
listened to by anyone.

## 0.13.0 - 2026-11-17

Genres: rock, metal, doom, industrial, ambient, soundscape - and modes.

- **Genres** for the written parts (`expand.GENRES`), a third group beside the ways of
  moving and the moods. A genre says what the chord voice *is*, gives every voice its own
  sound, and brings a tempo:
  - **rock** - power chords in eighths, a backbeat, a lead with some bite;
  - **metal** - a galloping riff under hard overdrive, the bass with the guitar, two
    kicks to the beat;
  - **doom** - slow and very heavy: low chords left to ring;
  - **industrial** - clipped chords in sixteenths on a thin pulse wave, an overdriven
    kit, a hiss of steam at the end of every second bar;
  - **ambient** - soft chords held and spread wide with a slow attack and a long tail, a
    bass that stays as long as the chord, air (a bed of noise that swells and fades), no
    drums;
  - **soundscape** - a drone on the key note under everything, more air, the tune far
    away in echo.
- **Power chords and riffs.** In the four guitar genres the chord voice plays root, fifth
  and octave - no third - low down, struck in the rhythm of a riff (`x` strikes, `-`
  lets it ring, `.` is silent), through **overdrive**.
- **Overdrive** is new in CLIo's synthesizer (`"drive"` on an instrument; it will be in
  CLIo 2.3 - the page plays it already). A song with it plays on an older CLIo with the
  same notes, clean; the song and the page say so.
- **Modes.** Beside the key note there is now a choice of major, minor, dorian,
  phrygian, lydian, mixolydian and locrian. A mode is never found by itself - a tune in C
  major that leans on its e would be taken for E phrygian - but asked for, the chords
  are the same seven with another one for home and the mode's own chord preferred (F
  under E phrygian). `expand.parse_key("E phrygian")`.
- An arrangement can carry tracks that are not notes (`Arrangement.tracks`: air, steam)
  and a kit of its own; `writers.clio.to_song` writes them.

None of the genres has been listened to by anyone yet: the volumes are set by measuring
(the tune a little louder than the guitar, nothing clips), the sounds by reasoning.

## 0.12.0 - 2026-11-17

Form, harmony that moves, moods, and a tune hummed in.

- **Form.** A double bar line `||` in the tune's text begins a new part - A, then B, C… -
  and on the roll a double click on a bar number does the same. The *Form* field says in
  which order the parts are played (`A A B A`); a part not named is left out. The tune is
  kept as it was written: while it is edited, the roll shows it once, with its parts
  marked and what the chip plays folded back onto it.
- **An ending.** *End with a closing bar* writes one more bar on the tonic and the song is
  played once (`"loop": false`) instead of going round.
- **Smarter harmony** in `expand`:
  - **minor keys** - the relative minor is taken when the music rests there, and its
    major dominant (E in A minor) when the raised seventh is heard;
  - **cadences** - a phrase likes to end on the dominant or the tonic, the piece on the
    tonic with the dominant before it; phrases are the parts of the tune, else four bars;
  - harmony **moves** at bar lines and follows the usual successions, so a tune no
    longer sits on one chord for bars; the note that begins a half bar says most about
    its chord, a short note between the beats least, and the dominant may carry its
    seventh (an f under G is not a wrong note);
  - a tune that leaves out a step of its scale fits two keys: the choice is now made by
    how listeners weigh the steps of a key (Krumhansl and Kessler's profiles), where the
    music ends, and against a key whose own triad is never heard;
  - the **key can be chosen** when the one found is not the one meant.
- **A walking bass** (style *walk*): a step on every beat, up through the chord and by a
  step of the scale into each new one.
- **Moods**: calm, mystery, dark, tense, battle, heroic, shop, space, victory, defeat -
  the names, tempi, drum patterns and lead sounds of CLIo's own composer, so a mood means
  the same in both. Choosing one for a tune of your own also sets its tempo.
- **Hum it.** *Hum it instead* records the microphone and writes down what was hummed,
  sung or whistled (`eigenchip/audio/hum.py`): the voice's own tuning is measured and
  allowed for (also when it sinks as the tune goes on), slides into notes and blips are
  taken out, the tempo is fitted near the one set, a breath is not written as a rest,
  and a low voice is moved up into the tune's octave. The notes land on the roll, to be
  mended there.
- `readers.tune.parts_of`, `play_form`; `expand.key_of`, `parse_key`, `MOODS`, `way`;
  `Session.open_hum`, `Session.arrange(form=, ending=, key=)`.

On the corpus, a tune alone and expanded is now closer to the piece it was taken from in
harmony (0.72 to 0.74) and its bass hits the true bass more often (0.50 to 0.56); a whole
piece through `expand` is unchanged (0.85). The measure hardly moves with the settings:
whether the richer harmony *sounds* better is for the ear. The hum reader has only been
tried on a synthetic voice, not on a real one.

## 0.11.0 - 2026-11-16

The tune on the piano roll.

- **Edit the tune on the roll.** A switch above the roll turns the lead into notes you can
  change there: a click adds a note of the chosen length, dragging moves it in time and
  pitch, its right end lengthens it, a double click removes it. Every change is drawn at
  once and, when the hand has rested, the other voices are written to it again.
- **Play it in.** With the roll in focus the computer's keys A to K play C to C (W E T Y U
  the black keys, Z and X the octave) and write each note at the marker, which moves on;
  `.` is a rest, Backspace takes the last note back, the arrows move the marker and
  transpose the chosen note. A **MIDI keyboard** does the same where the browser gives a
  page one (Chrome, Edge, Firefox on request; not Safari).
- **From a conversion to a tune.** Switched on over a converted piece, its lead becomes
  the tune: what the transcriber got wrong can be put right by hand, and the parts
  written to the corrected melody.
- Roll and text stay in step: what is drawn is written out in the text box
  (`readers.tune.write_tune`), and a tune typed there appears on the roll.
- `readers.tune.read_notes`, `Session.open_tune(notes=...)`.

Notes are entered step by step, not in time to a click: there is no recording against a
metronome yet. One note length at a time is also the grid the pointer snaps to.

## 0.10.0 - 2026-11-14

The base of a composer's tool: a tune of your own, and the voices written to it.

- **Write a tune.** On the page, *Write a tune* takes a melody as text - `e4 e4 f4 g4 |
  g4:2 e4:2`, a note a beat long unless a length in beats follows a colon, a dot for a
  rest, `-` to hold - with a tempo and a meter (`eigenchip/readers/tune.py`). It is kept
  as the lead and arranged with `expand`.
- **Styles** for the written parts: *plain* (held bass, rolling chords), *ballad*,
  *march* (bass on every beat, root and fifth; snare on two and four), *drive* (bass in
  eighths, busy hats) and *waltz*. A style is a bass movement, a pace for the chord
  voice and a bar of drums.
- **Chords you can change.** The chords the arranger chose are shown bar by bar
  (`C | C | F | C G`); edit the line and it plays yours - triads, sevenths (`G7`, `Dm7`,
  `Fmaj7`), diminished; `-` leaves a bar to the arranger.
- **Voices on and off.** Under the roll every voice of the chip version has a tick and a
  *solo*; the sound is made again without the others and goes on from where it was.
  The downloaded sound is what you hear.

`expand` picks few chords when a tune fits one chord tolerably (four bars of *Ode to Joy*
come out as C, C, C, C G): the line is there to be changed. The score table judges a
written tune against itself, so for `expand` its "true" and "harmony" only say how much
is new.

## 0.9.0 - 2026-11-14

An arranger that goes the other way: from fewer voices to more.

- **`expand`.** The other arrangers reduce: every note they play was in the source. This
  one keeps one line, the tune, and writes a bass, a chord voice and an inner line anew
  from the harmony. The key is the major scale holding most of the sound; each half bar
  gets one of its seven triads, by the best path through them (the notes sounding there
  speak for a chord that holds them and against one that does not; changing chord costs a
  little). It serves two cases:
  - *a tune and nothing else* - a sketch, a melody in the head: it is harmonised;
  - *a dense recording* - what was heard of the inner parts is the least reliable thing
    in the chain and, played back, the most disturbing. Here it is only evidence for the
    chords, and what is played is the tune and clean parts written from them.
- On the page: *expand* among the arrangers, and a row in the score table.

Measured against the corpus pieces themselves (harmony per beat): a tune alone agrees
0.69 with its piece, the tune expanded 0.72 - a harmonisation is one of many, not the
composer's; a whole piece put through `expand` keeps 0.85 of its harmony, against 0.97
for `roles-arp`, which plays the notes themselves. Seven triads and one key per piece are
its whole vocabulary: no sevenths, no modulation, no minor dominant.

## 0.8.0 - 2026-11-14

A steadier tune, and a noise bed that does not click.

- **The tune, tidied.** By the author's ear the 0.7.0 lead was close but janky. Three
  things are known only once a first line exists, so the search now runs again with them:
  the **key** of the piece (a note outside it counts half - more often a mistake of the
  ear than a chromatic step; a piece in no key is left alone), **where the tune lies** (a
  note more than a fifth from the middle of the tune's notes of the last and next eight
  seconds counts less, the further the less: it is another part filling a rest), and
  that a **blip** shorter than a tenth of a second is not a note of the tune.
- **Held notes put together.** A long note in a recording wavers and is written as
  several, which plays back as a stutter. Neighbours of one pitch less than 0.3 s apart
  are joined unless the pitch was heard to be struck again (the note cutter's own test).
- **The lead is left whole.** Long notes of the lead are no longer struck again to follow
  the loudness, unless they last two bars or more; other voices in pieces of half a bar.
- **A smoother noise bed.** The lasting noise of a recording is evened out over about two
  beats before it is written, so it no longer flickers on and off; its notes last up to
  two bars while level and colour glide evenly; and the bed instrument comes in over 0.6 s,
  leaves over 0.8 s and is low-passed.

On the author's recordings (five voices; harmony / bass / loudness / movement): the
orchestral piece 0.73 / 0.77 / 0.88 / 0.41 (0.7.0: 0.75 / 0.77 / 0.89 / 0.42), its lead 52
notes with 3 far leaps where 0.7.0 had 75 with ten; the ambient piece 0.63 / 0.64 / 0.79 /
0.40 (0.7.0: 0.64 / 0.67 / 0.79 / 0.31). Over the corpus the melody kept is unchanged
(0.81).

## 0.7.0 - 2026-11-14

The tune, followed with the whole piece in view.

- **Following the tune.** The audio reader no longer leaves the melody to the sorting of
  notes into lines, which decides one note at a time and has no memory. It chooses, over
  the whole piece, the one line through the transcribed notes that carries the most
  prominent sound for the least leaping (`eigenchip/audio/melody.py`): a note counts by
  its length and by its standing among the notes sounding with it; the top of a chord,
  and a move by step, count a little more; leaps cost, far leaps cost much more. The tune
  becomes line 0 and the arrangers take it as the lead. `tune=False` (reader) gives the
  old behaviour. From audio, the lead voice now keeps 0.81 of the melody over the corpus
  where it kept 0.58.
- **A MIDI file's melody part is also chosen by loudness.** `roles` now counts how loud
  a part is played against the others; the melody is found in every piece of the corpus
  that has one (1.00, from 0.70 with the two new pieces).
- **Long notes follow the loudness.** A held note could say one thing about its level -
  "from this to that". Where the loudness of the source leaves that straight line, the
  note is now struck again and each piece follows the curve. Pedal notes no longer stay
  flat under a swell.
- **Two new corpus pieces** for the texture of slow orchestral writing: *Long tune* (the
  melody in long notes in the middle, a figure moving above it) and *Octaves* (the melody
  doubled an octave above; the strict melody score counts the lower octave only). All
  results are regenerated; averages are not comparable with 0.6.0.
- `RESULTS-audio.md` shows the whole chain three ways: no lines, lines found, tune
  followed.

On the author's two recordings, sound against sound, five voices: the orchestral piece
0.76 / 0.81 / 0.89 / 0.44 before (harmony, bass, loudness, movement) and 0.75 / 0.77 /
0.89 / 0.42 now, with a lead that leaps half as often and keeps to two and a half octaves
instead of five; the ambient piece 0.63 / 0.66 / 0.78 / 0.30 and 0.64 / 0.67 / 0.79 / 0.31.
The numbers do not say whether the lead is the melody a listener hears; that is for ears.

## 0.6.0 - 2026-11-14

The first release shaped by real recordings: dynamics, more voices, a noise track, slides.

- **Sound against sound.** `eigenchip.audio.compare` compares a chip version with its
  original as sound - harmony, bass, loudness, movement - so a conversion of a recording
  can be judged without knowing its notes. The workbench shows it for every sound file;
  `python experiments/listen.py your.wav` prints it for several settings.
- **Expression.** `--expression full | plain` (and a choice on the page). `full`, the
  default, writes a level on every note from the loudness of the source, lets sweeps
  slide and swells swell. That uses the slide and level notation of CLIo 2.1, and the
  song says so in `"needs"`. `plain` is the chip as it was - one level, sweeps as
  staircases - and plays on CLIo 2.0. A MIDI file's levels come from its velocities,
  each part against its own loudest note; a file with one velocity converts as before.
- **More voices.** `--voices` goes up to 6. Beyond lead and bass, further lines are taken
  from the top of what is left; `roles-arp` gives the chords what remains after them.
- **A noise track.** The audio reader measures how much of the sound is lasting noise
  (wind, rumble, wash) and how bright it is; when that is more than a twelfth of the
  energy the song gets a `bed` track on the noise wave that follows it. Runs of hi-hats
  are left to the drum track.
- **Softer edges for slow music.** With fewer than two attacks a second, the chip
  instruments get a slow attack and a long release.
- The workbench plays songs with CLIo's synthesizer as it will be in 2.1.
- `cut_notes(..., quiet=...)`: an optional threshold that follows the music. Off by
  default; see the research log for why.

Measured on two recordings (an orchestral and an ambient piece), sound against sound:
loudness 0.58 to 0.88 and bass 0.70 to 0.81 on the first with five voices; movement 0.11
to 0.33 on the second. Harmony 0.73 to 0.76 and 0.64 unchanged: the transcriber is the
limit. The effect detector found nothing in either.

## 0.5.0 - 2026-11-14

A choice of how closely to listen, a tidier transcription, and the sounds that are not notes.

- **Quality.** `--quality fast | standard | fine` (and the same choice on the page) sets
  how often the spectrogram looks, how finely it divides the semitone and how long the
  template matching runs. Measured on the corpus: `fast` about half the time for two
  points of F1, `fine` about three times the time for one point.
- **Cleaning.** `eigenchip.audio.clean` tidies a transcription before the beat is found:
  `light` (the default) joins scraps to the note they belong to and removes semitone
  shadows, short faint notes on drum hits, and what a sweep left behind; `strict` also
  removes faint short notes and limits the crowd. `--clean off` gives the old behaviour.
- **Effects.** `eigenchip.audio.effects.find_effects` reports risers, falls, swells and
  impacts with their times, pitch range and whether they are tone or hiss. The audio
  reader keeps them in `score.info["effects"]`, apart from the notes, and removes the
  debris they leave in the transcription.
- **Effects in the song.** The CLIo writer puts them on tracks of their own (`fx`, `air`,
  `swell`, `hiss`, `boom`) using only what CLIo 2.0 songs can do: staircases for sweeps,
  a slow attack for swells, a long decay for impacts. `to_song(..., effects=False)` and
  `--no-effects` leave them out.
- Reference synthesizer: `synth.effect` and `synth.scene` make effects with known
  answers and lay them over a piece; `evaluate.effect_scores` compares.
- Workbench: selects for detail and tidying; effects drawn on the piano roll as slanted
  lines, wedges and strokes, with their own legend entry and tooltips; the summary says
  what was found and how many notes tidying removed.
- Results: new tables for quality, cleaning and effects.

Changed numbers: the audio reader now cleans lightly and looks for effects by default,
so whole-chain figures move by a point at most (`nmf` is unchanged; the melody kept from
`peaks` goes from 0.69 to 0.68). The detector's rules were fitted to the synthetic
effects it is tested on.

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
