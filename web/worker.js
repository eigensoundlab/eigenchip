// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Daniel Sandner
//
// The engine room: Python (Pyodide) in a worker, running the eigenchip package
// unchanged. The page sends one message per action; nothing leaves the browser.
// This is a module worker (see app.js): current Pyodide refuses classic ones.

const PYODIDE_VERSION = "314.0.7";
const query = new URL(self.location.href).searchParams;
// ?pyodide=/some/path/ serves Pyodide from elsewhere (a local copy, another mirror)
const INDEX = new URL(query.get("pyodide") || `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`, self.location.href).href;
const ROOT = new URL("../", self.location.href).href;      // the repository root, as served

let pyodide = null;
let call = null;
let numpy = false;

const say = (text) => postMessage({ type: "status", text });

const BOOT = `
import json, sys
sys.path.insert(0, "/app")
import eigenchip
from eigenchip.app import Session, to_json
import clio_synth

session = Session()

def _progress(fraction, text):
    js_progress(float(fraction), str(text))

def _bytes(blob):
    return bytes(blob.to_py()) if blob is not None else None

def _call(name, payload, blob):
    a = json.loads(payload)
    if name == "open_midi":
        return to_json(session.open_midi(_bytes(blob), a.get("title", ""), a.get("truth")))
    if name == "open_audio":
        import numpy as np
        samples = np.frombuffer(_bytes(blob), dtype=np.float32)
        return to_json(session.open_audio(samples, a.get("rate", 22050), a.get("title", ""),
                                          progress=_progress, **a.get("options", {})))
    if name == "open_midi_as_audio":
        return to_json(session.open_midi_as_audio(_bytes(blob), a.get("title", ""), a.get("colour", "band"),
                                                  a.get("drums", True), a.get("truth"),
                                                  progress=_progress, **a.get("options", {})))
    if name == "open_tune":
        return to_json(session.open_tune(a.get("text", ""), a.get("tempo", 100), tuple(a.get("meter", [4, 4])),
                                         a.get("title", "A tune")))
    if name == "arrange":
        return to_json(session.arrange(a.get("arranger", "roles-arp"), a.get("voices", 3), a.get("steps_per_beat", 4),
                                       expression=a.get("expression", "full"), style=a.get("style", "plain"),
                                       chords=a.get("chords")))
    if name == "likeness":
        return to_json(session.likeness)
    if name == "chip":
        return session.chip_wav(clio_synth, a.get("mute") or ())
    if name == "original":
        return session.original_wav(a.get("colour", "band"))
    if name == "midi":
        return session.midi_bytes()
    raise ValueError("unknown command " + name)
`;

async function init() {
  say("Fetching Python");
  const { loadPyodide } = await import(INDEX + "pyodide.mjs");      // Pyodide runs in module workers only
  pyodide = await loadPyodide({ indexURL: INDEX });
  say("Loading eigenchip");
  const manifest = await (await fetch(ROOT + "web/manifest.json", { cache: "no-cache" })).json();
  const wanted = manifest.package.map((p) => [p, p]).concat(Object.entries(manifest.vendor).map(([to, from]) => [from, to]));
  const texts = await Promise.all(wanted.map(async ([from]) => {
    const res = await fetch(ROOT + from, { cache: "no-cache" });
    if (!res.ok) throw new Error(`Could not load ${from} (${res.status})`);
    return res.text();
  }));
  wanted.forEach(([, to], i) => {
    const path = "/app/" + to;
    pyodide.FS.mkdirTree(path.slice(0, path.lastIndexOf("/")));
    pyodide.FS.writeFile(path, texts[i]);
  });
  pyodide.globals.set("js_progress", (fraction, text) => postMessage({ type: "progress", fraction, text }));
  pyodide.runPython(BOOT);
  call = pyodide.globals.get("_call");
  const version = pyodide.runPython("eigenchip.__version__");
  say("Loading NumPy");
  try {
    await pyodide.loadPackage("numpy");
    pyodide.runPython("import numpy");
    numpy = true;
  } catch (err) {
    numpy = false;                       // MIDI files still work; sound files and the reference synth do not
  }
  postMessage({ type: "ready", numpy, version, python: pyodide.version });
}

function tidy(err) {
  // the last line of a Python traceback is the part worth reading
  const lines = String((err && err.message) || err).trim().split("\n");
  return lines[lines.length - 1].replace(/^[A-Za-z_.]*(Error|Exception): /, "");
}

self.onmessage = async (event) => {
  const { id, cmd, payload, blob } = event.data;
  try {
    if (cmd === "init") {
      await init();
      postMessage({ id, ok: true });
      return;
    }
    const out = call(cmd, JSON.stringify(payload || {}), blob || null);
    if (typeof out === "string") {
      postMessage({ id, ok: true, json: out });
    } else {
      const bytes = out.toJs();          // Python bytes -> Uint8Array (a copy)
      out.destroy();
      postMessage({ id, ok: true, bytes }, [bytes.buffer]);
    }
  } catch (err) {
    postMessage({ id, ok: false, error: tidy(err) });
  }
};
