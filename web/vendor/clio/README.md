# CLIo's synthesizer

`clio_synth.py` is `engine/audio/synth.py` from [CLIo](https://github.com/eryxgames/CLIo)
as it will be in CLIo 2.3: tag `v2.2.1` plus two changes that give instruments four more
settings - `drive` (overdrive), `detune` (two more oscillators a few cents apart),
`filter` (a resonant low-pass that moves over every note) and `room` (early echoes) -
which the genres of `expand` use for guitars, strings, brass and acid lines. Songs without
them sound exactly as they do in 2.2; a CLIo without them plays a song that has them with
the same notes and plainer sounds. The web page uses this file to play a song as the game
engine would.

Copyright 2024-2026 Daniel Sandner. Licensed under the Apache License, Version 2.0.

To update: copy the file from a newer CLIo tag and change the tag named here and in
`web/index.html`.
