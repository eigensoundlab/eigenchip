# CLIo's synthesizer

`clio_synth.py` is `engine/audio/synth.py` from [CLIo](https://github.com/eryxgames/CLIo)
as it will be in CLIo 2.1: tag `v2.0.0` plus the change that adds slides and levels to the
song notation (`c3>c5:16`, `c4@5`, `c4@2>9:16`). Songs written for 2.0 sound exactly as
they did. The web page uses it to play a converted song as the game engine would.

Copyright 2024-2026 Daniel Sandner. Licensed under the Apache License, Version 2.0.

To update: copy the file from a newer CLIo tag and change the tag named here and in
`web/index.html`.
