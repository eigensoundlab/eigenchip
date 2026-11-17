# CLIo's synthesizer

`clio_synth.py` is `engine/audio/synth.py` from [CLIo](https://github.com/eryxgames/CLIo)
2.2.2, unchanged. Since that version instruments have four more settings - `drive`
(overdrive), `detune` (two more oscillators a few cents apart), `filter` (a resonant
low-pass that moves over every note) and `room` (early echoes) - which the genres of
`expand` use for guitars, strings, brass and acid lines, and a song can be rendered track
by track (`render_tracks`), which is how the page switches voices on and off while a
piece plays. An older CLIo plays a song that has those settings with the same notes and
plainer sounds. The web page uses this file to play a song as the game engine would.

Copyright 2024-2026 Daniel Sandner. Licensed under the Apache License, Version 2.0.

To update: copy the file from a newer CLIo tag and change the tag named here and in
`web/index.html`.
