// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Daniel Sandner
//
// The workbench: choose a source, convert it, look at the notes, hear both versions.
// All analysis happens in worker.js (Python); this file is the hands and the eyes.
"use strict";

const $ = (id) => document.getElementById(id);
const RATE = 22050;
const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const BLACK = [false, true, false, true, false, false, true, false, true, false, true, false];
const KEYS_W = 38;
// the version in this script's address keeps a browser from mixing an old script with a new page
const RELEASE = ((document.currentScript && document.currentScript.src.split("v=")[1]) || "").split("&")[0];
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const edit = { on: false, notes: [], sections: [], length: 4, cursor: 0, sel: -1, drag: null, timer: 0, octave: 4, midi: null, audio: null };
const hum = { rec: null, chunks: [], stream: null, timer: 0 };
const rec = { on: false, t0: 0, beat: 0.5, from: 0, held: new Map(), notes: [], ticker: 0, next: 0, perBar: 4 };   // playing in time
const state = {
  engine: null,          // {numpy, version} once Python is up
  source: null,          // {id, name, file?, example?, bytes?, midi}
  opened: null,          // what the engine currently holds (source + listening choices)
  facts: null,
  view: null,
  busy: false,
  chords: null,          // chords the user asked for (text), for the expanding arranger
  form: null,            // the order of the parts of a tune ("A A B A"), when the user gave one
  key: "",               // the key the user chose ("Am"), empty for the one that is found
  after: null,           // what to say when the next conversion is done, instead of how long it took
  mute: new Set(),       // instruments of the chip version that are switched off
  hits: [],              // rectangles of drawn notes, for the tooltip
  geometry: null,
  urls: { original: null, chip: null },
  chipBytes: null,
  originalIsRecording: false,
};
const players = { original: new Audio(), chip: new Audio() };

// ---------------------------------------------------------------------- engine
let worker = null;
const waiting = new Map();
let sequence = 0;
function startEngine() {
  worker = new Worker("worker.js" + (location.search ? location.search + "&" : "?") + "v=" + RELEASE, { type: "module" });
  worker.onmessage = (event) => {
    const m = event.data;
    if (m.type === "status") return status(m.text + "…");
    if (m.type === "progress") { progress(m.fraction); return status(m.text + "…"); }
    if (m.type === "ready") { state.engine = m; return; }
    const w = waiting.get(m.id);
    if (!w) return;
    waiting.delete(m.id);
    if (m.ok) w.resolve(m.json !== undefined ? JSON.parse(m.json) : m.bytes !== undefined ? m.bytes : true);
    else w.reject(new Error(m.error));
  };
  worker.onerror = (event) => status("The engine could not start: " + (event.message || "the worker failed to load") + ".", true);
  return ask("init", {});
}

// Python cannot be interrupted from outside, so stopping means ending the worker and starting a fresh one.
async function stopEngine() {
  if (!state.busy) return;
  state.stopped = true;
  worker.terminate();
  for (const w of waiting.values()) w.reject(new Error("Stopped."));
  waiting.clear();
  state.engine = null;
  state.opened = null;
  $("stop").hidden = true;
  progress(null);
  status("Stopped. Getting the engine ready again…");
  try {
    await startEngine();
    status("Stopped. Ready again.");
  } catch (err) {
    status("The engine could not restart: " + err.message, true);
  }
  progress(undefined);
  sourceChanged();
}

// fraction 0..1 fills the bar; null shows it busy without a figure; undefined hides it
function progress(fraction) {
  const bar = $("bar");
  bar.hidden = fraction === undefined;
  if (fraction === null || fraction === undefined) bar.removeAttribute("value");
  else bar.value = Math.max(0, Math.min(1, fraction));
}

function ask(cmd, payload, blob) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    waiting.set(id, { resolve, reject });
    worker.postMessage({ id, cmd, payload, blob });
  });
}

function status(text, bad) {
  const el = $("status");
  el.textContent = text;
  el.classList.toggle("bad", !!bad);
}

// ---------------------------------------------------------------------- sources
function isMidiName(name) { return /\.(mid|midi|smf)$/i.test(name); }

function chooseFile(file) {
  if (!file) return;
  state.source = { id: "file:" + file.name + ":" + file.size + ":" + file.lastModified, name: file.name, file, midi: isMidiName(file.name) };
  const size = file.size > 1048576 ? (file.size / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(file.size / 1024)) + " kB";
  $("chosen").innerHTML = "";
  const strong = document.createElement("strong");
  strong.textContent = file.name;
  $("chosen").append(strong, `, ${size}. It stays on your computer.`);
  $("example").value = "";
  sourceChanged();
}

function chooseExample() {
  const entry = state.examples.find((e) => e.file === $("example").value);
  if (!entry) return;
  state.source = { id: "example:" + entry.file, name: entry.title, example: entry, midi: true };
  $("chosen").textContent = entry.source + " " + entry.stresses;
  sourceChanged();
}

function asAudio() {
  const s = state.source;
  return !!s && (!s.midi || (!!s.example && $("example-as").value !== "midi"));
}

function sourceChanged() {
  const s = state.source;
  $("example-as").disabled = !(s && s.example);
  $("listening").hidden = !asAudio();
  $("reading").hidden = asAudio();
  $("limit").disabled = !(s && s.file && !s.midi);
  $("go").disabled = !state.engine || !s || state.busy;
}

async function sourceBytes() {
  const s = state.source;
  if (s.bytes) return s.bytes;
  if (s.file) s.bytes = await s.file.arrayBuffer();
  else {
    const res = await fetch("../corpus/" + s.example.file, { cache: "no-cache" });
    if (!res.ok) throw new Error("Could not load the example (" + res.status + ").");
    s.bytes = await res.arrayBuffer();
  }
  return s.bytes;
}

async function decode(buffer, limitSeconds) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  let decoded;
  try {
    decoded = await ctx.decodeAudioData(buffer.slice(0));
  } catch (err) {
    throw new Error("This browser cannot decode that file. WAV, MP3 and Ogg work almost everywhere.");
  } finally {
    ctx.close();
  }
  const seconds = limitSeconds > 0 ? Math.min(decoded.duration, limitSeconds) : decoded.duration;
  const offline = new OfflineAudioContext(1, Math.max(1, Math.ceil(seconds * RATE)), RATE);   // mono, resampled
  const node = offline.createBufferSource();
  node.buffer = decoded;
  node.connect(offline.destination);
  node.start(0);
  const out = await offline.startRendering();
  return { samples: out.getChannelData(0), seconds, whole: decoded.duration };
}

// ---------------------------------------------------------------------- converting
function listening() {
  const tempo = parseFloat($("tempo").value.replace(",", "."));
  const [num, den] = $("meter").value.split("/").map(Number);
  return { transcriber: $("transcriber").value, tempo: tempo > 20 && tempo < 400 ? tempo : null, meter: [num, den],
    quality: $("quality").value, clean: $("clean").value };
}

async function open() {
  const s = state.source;
  if (s.tune) {
    status("Reading the tune…");
    return ask("open_tune", { text: s.tune.text || "", notes: s.tune.notes || null, sections: s.tune.sections || null,
      tempo: s.tune.tempo, meter: s.tune.meter, title: s.name });
  }
  const title = s.name.replace(/\.[^.]+$/, "");
  const truth = s.example ? s.example.truth : null;
  const bytes = await sourceBytes();
  if (!asAudio()) {
    status("Reading the notes…");
    return ask("open_midi", { title, truth }, new Uint8Array(bytes));
  }
  if (!state.engine.numpy) throw new Error("Sound needs NumPy, which did not load here. MIDI files still work.");
  const options = listening();
  if (s.example) {
    status("Playing it on the test synthesizer and listening…");
    return ask("open_midi_as_audio", { title, truth, colour: $("example-as").value, drums: true, options }, new Uint8Array(bytes));
  }
  status("Decoding the sound…");
  const got = await decode(bytes, Number($("limit").value));
  s.analysed = got.seconds;
  s.whole = got.whole;
  status(`Listening to ${Math.round(got.seconds)} seconds…`);
  return ask("open_audio", { title, rate: RATE, options }, got.samples);
}

async function convert(arrangeOnly) {
  if (state.busy || !state.source || !state.engine) return;
  state.busy = true;
  state.stopped = false;
  $("go").disabled = true;
  $("stop").hidden = false;
  progress(null);
  stop();
  const started = performance.now();
  try {
    const key = JSON.stringify([state.source.id, asAudio(), $("example-as").value, $("limit").value, listening()]);
    if (!arrangeOnly || key !== state.opened) {
      state.opened = null;
      state.chords = null;                                  // another piece: its chords are chosen afresh
      if (!state.source.tune) { state.form = null; state.key = ""; }      // a tune being worked on keeps its form and key
      state.facts = await open();
      state.opened = key;
    }
    progress(null);
    status("Arranging…");
    state.view = await ask("arrange", { arranger: $("arranger").value, voices: Number($("voices").value),
      expression: $("expression").value, style: $("style").value || "plain", chords: state.chords,
      form: state.source.tune ? state.form : null, ending: $("ending").checked, key: state.key || null,
      lead: $("lead-sound").value || null, chip: $("chip").checked });
    show();
    status("Making the chip sound…");
    await sound();
    status(state.after || `Done in ${((performance.now() - started) / 1000).toFixed(1)} s. Play it, or choose another arranger in the table.`);
    state.after = null;
  } catch (err) {
    if (!state.stopped) status(err.message, true);
  } finally {
    state.busy = false;
    $("stop").hidden = true;
    if (!state.stopped) progress(undefined);
    sourceChanged();
  }
}

function setUrl(which, blobOrNull) {
  if (state.urls[which]) URL.revokeObjectURL(state.urls[which]);
  state.urls[which] = blobOrNull ? URL.createObjectURL(blobOrNull) : null;
  players[which].src = state.urls[which] || "";
  if (!state.urls[which]) players[which].removeAttribute("src");
}

// Sound against sound: the only comparison that does not rest on what the transcriber heard.
function likeness(l) {
  const p = $("likeness");
  p.hidden = !l || l.error !== undefined;
  if (p.hidden) return;
  p.innerHTML = "";
  const lead = document.createElement("b");
  lead.textContent = "Sound against sound: ";
  p.append(lead, `harmony ${pct(l.harmony)}, bass ${pct(l.bass)}, loudness ${pct(l.loudness)}, movement ${pct(l.movement)}. ` +
    "How alike the chip version and the original are in these respects, whatever the transcriber made of the notes; " +
    "0% is two unrelated sounds.");
}

// ---------------------------------------------------------------------- the composer's side: a tune, a style, chords
function useTune() {
  if (state.busy) return status("Still working on the last piece. Try again in a moment.");
  if (!state.engine) return status("The engine is still starting. Try again in a moment.");
  const text = $("tune").value.trim();
  const tempo = Number($("tune-tempo").value.replace(",", "."));
  if (!text) return status("Write a few notes first, for example: e4 e4 f4 g4", true);
  if (!(tempo >= 30 && tempo <= 300)) return status("The tempo is a number of beats a minute, between 30 and 300.", true);
  const meter = $("tune-meter").value.split("/").map(Number);
  state.source = { id: "tune:" + JSON.stringify([text, tempo, meter]), name: "A tune", tune: { text, tempo, meter }, midi: true };
  $("example").value = "";
  $("arranger").value = "expand";
  if (Number($("voices").value) < 4) $("voices").value = "4";
  $("chosen").textContent = "A tune of your own. The arranger writes the other parts; change the style and the chords below.";
  sourceChanged();
  convert(false);
}

const MODES = ["major", "minor", "dorian", "phrygian", "lydian", "mixolydian", "locrian"];
function written() {                                       // what only the expanding arranger has: a style or a mood, a form,
  const v = state.view, on = !!v && v.arranger === "expand";       // a key, an ending, and chords to change
  $("written").hidden = !on;
  $("shape").hidden = !on;
  $("chordline").hidden = !on;
  if (!on) return;
  const style = $("style");
  if (!style.options.length) {
    const families = [...new Set(v.genres.map((g) => g[3]))].map((family) => [family, v.genres.filter((g) => g[3] === family)]);
    for (const [label, list] of [["Ways of moving", v.styles], ...families, ["Moods", v.moods]]) {
      const group = document.createElement("optgroup");
      group.label = label;
      for (const [name] of list) group.append(new Option(name, name));
      style.append(group);
    }
    $("key").append(new Option("as found", ""));
    for (const name of NAMES) $("key").append(new Option(name, name));
    for (const name of MODES) $("mode").append(new Option(name, name));
  }
  style.value = v.style || "plain";
  const mood = v.moods.find(([name]) => name === style.value), genre = v.genres.find(([name]) => name === style.value);
  $("style-about").textContent = mood ? `${mood[1]} A mood: it has its own drums and sound for the tune, and a tempo of ${mood[2]}.`
    : genre ? `${genre[1]} A genre: every voice has its own sound, and it has a tempo of ${genre[2]}.`
      : (v.styles.find(([name]) => name === style.value) || [])[1] || "";
  $("chords").value = v.chords_text || "";
  $("key").options[0].text = "as found" + (state.key ? "" : ": " + (v.key || "…"));
  const chosen = (state.key || v.key || "C major").split(" ");       // "E phrygian"
  $("key").value = state.key ? chosen[0] : "";
  $("mode").value = chosen[1] || "major";
  $("mode").hidden = !state.key;                            // the mode is chosen with the key note
  const own = !!v.parts;
  $("chip").checked = !!v.chip;
  $("form-box").hidden = !own;
  $("longer").hidden = !own || !v.longer || v.longer === v.form;
  if (own && document.activeElement !== $("form")) $("form").value = v.form || "";
  const names = own ? [...new Set(v.sections.map((_, i) => String.fromCharCode(65 + i)))] : [];
  $("shape-hint").textContent = (own ? (names.length > 1
    ? `The tune has the parts ${names.join(", ")}. The form is the order they are played in; a part not named is left out. `
    : "The tune is one part, A. Begin another with || in the text, or with a double click on a bar number while editing the roll; " +
      "then write here the order they are played in, for example A A B A. ") +
    "A part in brackets, (A), is played without the tune; A- quietly, without bass and drums; A+ a tone higher. " : "") +
    (v.ending ? "With its closing bar the song is played once." : "Without a closing bar the song goes round and round.");
}

function styleChanged() {                                   // a mood or a genre brings its tempo; a tune of one's own takes it
  const v = state.view, mood = v && [...v.genres, ...v.moods].find(([name]) => name === $("style").value);
  if (mood && state.source && state.source.tune) {
    $("tune-tempo").value = String(mood[2]);
    return edit.on ? commit(true) : useTune();
  }
  convert(true);
}

// ---------------------------------------------------------------------- which voices sound
const VOICE_NAMES = { lead: "Lead", bass: "Bass", inner: "Inner", chords: "Chords", kit: "Drums", bed: "Noise", fx: "Sweeps", air: "Air", steam: "Steam",
  timpani: "Kettledrums", strings: "Strings", bells: "Bells", toll: "Bell" };
const voiceName = (id) => VOICE_NAMES[id] || id.replace(/^inner(\d)$/, "Inner $1").replace(/^fx(\d)$/, "Sweeps $1");
const muted = () => [...state.mute].filter((id) => state.view && state.view.instruments.includes(id));

function hear() {
  const box = $("hear"), v = state.view;
  box.innerHTML = "";
  const sounds = $("lead-sound");
  $("lead-box").hidden = !v || !v.leads;
  if (v && v.leads && !sounds.options.length) {
    sounds.append(new Option("as the style has it", ""));
    for (const [name, about] of v.leads) { const o = new Option(name, name); o.title = about; sounds.append(o); }
  }
  if (!v || v.instruments.length < 2) return;
  for (const id of v.instruments) {
    const tick = document.createElement("input");
    tick.type = "checkbox";
    tick.checked = !state.mute.has(id);
    tick.addEventListener("change", () => { if (tick.checked) state.mute.delete(id); else state.mute.add(id); remix(); });
    const label = document.createElement("label");
    label.append(tick, " " + voiceName(id));
    const solo = document.createElement("button");
    solo.type = "button";
    solo.className = "solo";
    solo.textContent = "solo";
    solo.title = `Only ${voiceName(id).toLowerCase()}; press again for all voices`;
    const alone = v.instruments.every((other) => (other === id) !== state.mute.has(other));
    solo.setAttribute("aria-pressed", String(alone));
    solo.addEventListener("click", () => {
      state.mute = new Set(alone ? [] : v.instruments.filter((other) => other !== id));
      remix();
    });
    const item = document.createElement("span");
    item.className = "voice";
    item.append(label, solo);
    box.append(item);
  }
}

async function remix() {                                    // the chip version again, without the muted voices
  hear();
  if (state.busy || !state.view) return;
  const p = players.chip, at = p.currentTime, playing = !p.paused && active() === "chip";
  state.busy = true;
  try {
    state.chipBytes = await ask("chip", { mute: muted() });
    setUrl("chip", new Blob([state.chipBytes], { type: "audio/wav" }));
    p.currentTime = at;
    if (playing) await p.play();
  } catch (err) {
    status(err.message, true);
  } finally {
    state.busy = false;
    sourceChanged();
  }
}

async function sound() {
  state.chipBytes = await ask("chip", { mute: muted() });
  setUrl("chip", new Blob([state.chipBytes], { type: "audio/wav" }));
  likeness(await ask("likeness", {}));
  const s = state.source;
  let note = "";
  state.originalIsRecording = false;
  if (s.file && !s.midi) {
    setUrl("original", s.file);
    state.originalIsRecording = true;
    if (s.whole > s.analysed + 1) note = `Only the first ${Math.round(s.analysed)} seconds were converted.`;
  } else if (state.engine.numpy) {
    const wav = await ask("original", { colour: "band" });
    setUrl("original", new Blob([wav], { type: "audio/wav" }));
    if (!asAudio()) note = "The original is the MIDI file played by a plain test synthesizer.";
  } else {
    setUrl("original", null);
    note = "No original to play: the test synthesizer needs NumPy, which did not load.";
  }
  const radio = document.querySelector('input[name="ab"][value="original"]');
  radio.disabled = !state.urls.original;
  if (radio.disabled) document.querySelector('input[name="ab"][value="chip"]').checked = true;
  $("sound-note").textContent = note;
  $("transport").hidden = false;
  clock();
}

// ---------------------------------------------------------------------- showing
const pitchName = (p) => NAMES[((p % 12) + 12) % 12] + (Math.floor(p / 12) - 1);
const pct = (x) => Math.round(x * 100) + "%";

function show() {
  const v = state.view, f = state.facts;
  $("empty").hidden = true;
  $("legend").hidden = false;
  $("findings").hidden = false;
  $("source-name").textContent = v.kind === "audio" ? "Heard" : "In the file";
  $("played-toggle").hidden = !v.played;
  $("effects-toggle").hidden = !(v.effects || []).length;
  const inner = v.voices.filter((x) => x.role === "inner").length;
  $("third-name").textContent = [inner > 1 ? "Inner voices" : inner ? "Inner voice" : "", v.voices.some((x) => x.role === "chords") ? "chords" : ""]
    .filter(Boolean).join(" and ").replace(/^c/, "C") || "Chords";
  written();
  hear();
  if (v.tune_text != null && document.activeElement !== $("tune")) $("tune").value = v.tune_text;
  if (edit.on && state.source && state.source.tune && state.source.tune.text) {     // written as text meanwhile: the roll follows
    edit.notes = fromView();
    edit.sections = (v.sections || []).filter((bar) => bar > 0);
    edit.sel = -1;
    edit.cursor = Math.max(0, ...edit.notes.map((n) => n[0] + n[1]));
    $("roll").scrollLeft = 0;
  }
  draw();
  table();

  const parts = [];
  const b = (x) => `<b>${x}</b>`;
  if (!f.notes) {
    parts.push("No notes were found. If this is a sound file, it may be too quiet, too dense or not pitched.");
  } else if (v.kind === "audio") {
    const info = f.info || {};
    parts.push(`Heard ${b(f.notes)} notes between ${f.lowest.toUpperCase()} and ${f.highest.toUpperCase()}, at ${b(v.tempo)} bpm ` +
      `(${info.tempo_given ? "as given" : "estimated"}), with the first beat at ${Number(info.offset || 0).toFixed(2)} s.`);
    if (f.drum_hits) parts.push(`It also heard ${b(f.drum_hits)} drum hits.`);
    const fx = v.effects || [];
    if (fx.length) {
      const names = { riser: "riser", fall: "fall", swell: "swell", impact: "impact" };
      const count = Object.keys(names).map((k) => [fx.filter((e) => e.kind === k).length, names[k]]).filter(([n]) => n)
        .map(([n, name]) => `${n} ${name}${n === 1 ? "" : "s"}`);
      parts.push(`Besides notes it found ${b(count.join(", "))}; the chip version plays them on tracks of their own, ` +
        `${v.expression === "plain" ? "sweeps as staircases" : "as notes that slide and swell"}.`);
    }
    if (v.bed) parts.push(`About ${b(pct(info.noise_share || 0))} of the sound is lasting noise - wind, rumble, wash - which a noise track follows.`);
    if (info.cleaned_away) parts.push(`Tidying took out ${b(info.cleaned_away)} notes that looked like mistakes.`);
    if (f.transcription) {
      const t = f.transcription;
      parts.push(`Of the ${b(t.true_notes)} notes really played it found ${b(pct(t.recall))}, and ${b(pct(t.precision))} of what it wrote down is right.`);
      if (f.drums) parts.push(`Of ${f.drums.true_hits} drum hits it found ${b(pct(f.drums.recall))}; ${b(pct(f.drums.precision))} of the hits it reported are real.`);
      if (f.tempo_verdict !== "ok") parts.push(`The true tempo is ${f.tempo_true} bpm: the estimate is ${b(f.tempo_verdict)}. Give the tempo to put it right.`);
    }
    if (!info.tempo_given && info.grid_agreement !== undefined && info.grid_agreement < 0.6) {
      parts.push("The notes do not sit well on a grid at this tempo. If it sounds wrong, give the tempo yourself.");
    }
  } else {
    parts.push(`${b(f.notes)} notes on ${f.channels} channel${f.channels === 1 ? "" : "s"} between ${f.lowest.toUpperCase()} and ${f.highest.toUpperCase()}` +
      `${f.drum_hits ? `, and ${f.drum_hits} drum hits` : ""}. Tempo ${b(v.tempo)} bpm in ${v.meter[0]}/${v.meter[1]}.`);
  }
  if (f.notes) {
    parts.push(`Up to ${b(v.polyphony[1])} notes sounded at once; the chip version has ${b(v.voices.length)} voice${v.voices.length === 1 ? "" : "s"}` +
      `${v.drums.length ? " and drums" : ""}, in ${v.patterns[0]} patterns of which ${v.patterns[1]} differ.`);
    if (v.needs && v.needs.includes("2.1")) parts.push("The song uses levels or slides, which need CLIo 2.1; choose \u201cplainly\u201d for one that CLIo 2.0 plays.");
    if (v.driven) parts.push("Its sounds use overdrive, detune, a moving filter or a room, which need CLIo 2.3; an older CLIo plays the same notes with plainer sounds.");
  }
  $("facts").innerHTML = parts.join(" ");
  $("against").textContent = {
    file: "Judged against the notes in the file.",
    played: "Judged against the notes that were really played, so mistakes of the ear count too.",
    heard: "Judged against the notes that were heard: the real ones are not known, so mistakes of the ear do not show here.",
  }[v.judged_against] + (state.source && state.source.tune
    ? " The file is the tune you wrote: for an arranger that writes new parts, \u201ctrue\u201d and \u201charmony\u201d only say how much is new."
    : "");
}

function table() {
  const body = $("scores").tBodies[0];
  body.textContent = "";
  for (const row of state.view.scores) {
    const tr = document.createElement("tr");
    const chosen = row.arranger === state.view.arranger;
    tr.setAttribute("aria-selected", chosen ? "true" : "false");
    tr.title = row.summary;
    const first = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = row.arranger;
    button.setAttribute("aria-pressed", chosen ? "true" : "false");
    first.append(button);
    tr.append(first);
    for (const key of ["melody_recall", "bass_recall", "pitch_recall", "pitch_precision", "chroma", "onset_f1"]) {
      const td = document.createElement("td");
      const value = row[key];
      if (value === null || value === undefined) {
        td.textContent = "–";
        td.className = "none";
        td.title = "Not known for this source";
      } else {
        const bar = document.createElement("span");
        bar.className = "bar";
        const fill = document.createElement("i");
        fill.style.width = Math.round(value * 100) + "%";
        bar.append(fill);
        td.append(bar, value.toFixed(2));
      }
      tr.append(td);
    }
    tr.addEventListener("click", () => {
      if (row.arranger === state.view.arranger || state.busy) return;
      $("arranger").value = row.arranger;
      convert(true);
    });
    body.append(tr);
  }
}

// ---------------------------------------------------------------------- piano roll
const layerOn = (name) => {
  const box = document.querySelector(`#legend input[data-layer="${name}"]`);
  return !box || box.checked;
};

function sized(canvas, w, h) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

function draw() {
  const v = state.view;
  if (!v) return;
  let lo = v.pitch_range[0] - 2, hi = v.pitch_range[1] + 2;
  const folded = folding();                                 // editing a tune with a form: the roll shows it as written
  const steps = folded ? Math.max(editSteps(), ...folded.map(([, , ws, len]) => ws + len)) : edit.on ? Math.max(v.steps, editSteps()) : v.steps;
  if (edit.on) {                                            // room to write: three octaves at least, and what is there
    lo = Math.min(lo, 48, ...edit.notes.map((n) => n[2] - 2));
    hi = Math.max(hi, 84, ...edit.notes.map((n) => n[2] + 2));
  }
  const rows = hi - lo + 1;
  const rowH = Math.max(5, Math.min(12, Math.floor(310 / rows)));
  const axisH = 22;
  const hasDrums = v.drums.length > 0 || v.source_drums.length > 0;
  const drumH = hasDrums ? 26 : 0;
  const avail = Math.max(200, $("roll").clientWidth - KEYS_W - 2);
  const px = Math.max(1.5, Math.min(12, Math.max(avail / Math.max(1, steps), Math.min(6, 15000 / Math.max(1, steps)))));
  const W = Math.ceil(steps * px) + 2, H = axisH + rows * rowH + drumH + 4;
  const g = (state.geometry = { lo, hi, rowH, axisH, px, W, H, steps, drumY: axisH + rows * rowH + 6 });
  const y = (pitch) => axisH + (hi - pitch) * rowH;

  // the keys down the left edge
  $("keys").hidden = $("notes").hidden = false;
  const k = sized($("keys"), KEYS_W, H);
  k.fillStyle = css("--screen");
  k.fillRect(0, 0, KEYS_W, H);
  k.font = `600 ${Math.min(11, rowH + 3)}px Archivo, sans-serif`;
  k.textBaseline = "middle";
  for (let p = lo; p <= hi; p++) {
    if (BLACK[((p % 12) + 12) % 12]) { k.fillStyle = css("--screen-2"); k.fillRect(0, y(p), KEYS_W, rowH); }
    if (((p % 12) + 12) % 12 === 0) { k.fillStyle = css("--screen-ink"); k.fillText(pitchName(p), 6, y(p) + rowH / 2 + 0.5); }
  }
  if (hasDrums) { k.fillStyle = css("--screen-dim"); k.fillText("dr", 6, g.drumY + 8); }

  const c = sized($("notes"), W, H);
  c.fillStyle = css("--screen");
  c.fillRect(0, 0, W, H);
  c.fillStyle = css("--screen-2");
  for (let p = lo; p <= hi; p++) if (BLACK[((p % 12) + 12) % 12]) c.fillRect(0, y(p), W, rowH);
  // bar and beat lines, bar numbers
  c.font = "600 11px Archivo, sans-serif";
  c.textBaseline = "alphabetic";
  const everyBar = Math.max(1, Math.ceil(34 / (v.steps_per_bar * px)));
  for (let s = 0; s <= steps; s += v.steps_per_beat) {
    const bar = s % v.steps_per_bar === 0;
    if (!bar && v.steps_per_beat * px < 7) continue;
    c.fillStyle = bar ? "rgba(201,211,224,0.28)" : "rgba(201,211,224,0.09)";
    c.fillRect(Math.round(s * px), bar ? 4 : axisH, 1, H);
    const n = s / v.steps_per_bar;
    if (bar && n % everyBar === 0 && s < steps) { c.fillStyle = css("--screen-dim"); c.fillText(String(n + 1), s * px + 4, 15); }
  }
  // the parts of a tune: as written while it is edited, as played otherwise
  const marks = edit.on ? (edit.sections.length ? [0, ...edit.sections].map((bar, i) => [String.fromCharCode(65 + i), bar * v.steps_per_bar]) : [])
    : (v.parts && v.parts.length > 1 ? v.parts.map(([name, at], i) => {
      const how = (v.plan || [])[i] || "";                // as the form writes it: (A), A-, A+
      return [(how.includes("t") ? `(${name})` : name) + (how.includes("q") ? "-" : "") + (how.includes("l") ? "+" : ""), at];
    }) : []);
  for (const [name, at] of marks) {
    c.fillStyle = css("--lead");
    c.fillRect(Math.round(at * px), 0, 2, H);
    c.fillText(name, at * px + 6 + c.measureText(String(at / v.steps_per_bar + 1)).width + 4, 15);
  }

  state.hits = [];
  const note = (start, dur, pitch, colour, label, outline) => {
    const x = start * px + 0.5, w = Math.max(1.5, dur * px - 1.5), top = y(pitch) + 0.5, h = rowH - 1;
    if (outline) {
      c.strokeStyle = colour;
      c.lineWidth = 1;
      c.strokeRect(x + 0.5, top + 0.5, Math.max(1, w - 1), Math.max(1, h - 1));
    } else {
      c.fillStyle = colour;
      if (c.roundRect && h >= 5 && w >= 4) { c.beginPath(); c.roundRect(x, top, w, h, 1.5); c.fill(); } else c.fillRect(x, top, w, h);
    }
    state.hits.push({ x, y: top, w, h, start, dur, pitch, label });
  };
  if (layerOn("source") && !edit.on) for (const [s, d, p] of v.source) note(s, d, p, css("--source"), v.kind === "audio" ? "Heard" : "In the file");
  const colours = { lead: css("--lead"), bass: css("--bass") };
  for (const voice of v.voices) {
    const layer = voice.role === "lead" || voice.role === "bass" ? voice.role : "third";
    if (!layerOn(layer) || (edit.on && voice.role === "lead")) continue;     // the tune is drawn from the editor, below
    const label = voice.role === "chords" ? "Chords" : voice.role === "inner" ? "Inner voice" : voice.role[0].toUpperCase() + voice.role.slice(1);
    for (const [s, d, p] of voice.notes) {
      const at = folded ? unfold(s, true) : s;
      if (at !== null) note(at, d, p, colours[voice.role] || css("--third"), label);
    }
  }
  if (v.played && layerOn("played")) for (const [s, d, p] of v.played) note(s, d, p, css("--screen-ink"), "Really played", true);
  if (hasDrums && layerOn("drums")) {
    c.fillStyle = css("--source");
    for (const s of v.source_drums) c.fillRect(s * px, g.drumY, Math.max(1.5, Math.min(3, px - 1)), 7);
    c.fillStyle = css("--screen-ink");
    for (const [s] of v.drums) {
      const at = folded ? unfold(s, true) : s;
      if (at !== null) c.fillRect(at * px, g.drumY + 9, Math.max(1.5, Math.min(3, px - 1)), 7);
    }
  }
  if ((v.effects || []).length && layerOn("effects")) drawEffects(c, v, g, px);
  if (edit.on) {
    edit.notes.forEach(([s, d, p], i) => {
      note(s, d, p, css("--lead"), "Tune");
      if (i === edit.sel) { c.strokeStyle = "#fff"; c.lineWidth = 1.5; c.strokeRect(s * px + 1, y(p) + 1, Math.max(2, d * px - 2.5), rowH - 2); }
    });
    c.fillStyle = css("--go");                              // where the next played note goes
    c.fillRect(edit.cursor * px, axisH, 2, rows * rowH);
    c.fillRect(edit.cursor * px - 3, axisH - 5, 8, 5);
  }
  $("notes").setAttribute("aria-label", `Piano roll of ${v.title}: ${v.source.length} source notes and ${v.voices.length} chip voices.`);
  playhead();
}

// A tune with a form is longer played than written.  While it is edited the roll shows it as written, and what
// the chip plays is folded back onto that: each part once, where it was written, and the closing bar after the end.
function folding() {
  const v = state.view;
  return edit.on && v && v.parts && v.parts.length ? v.parts : null;
}

function unfold(step, once) {                               // a step of the song -> where it is on the written roll
  const parts = folding();
  if (!parts) return step;
  const seen = new Set();
  for (const [name, at, ws, len] of parts) {
    if (step >= at && step < at + len) return once && seen.has(name) ? null : ws + step - at;
    seen.add(name);
  }
  const last = parts[parts.length - 1];
  return Math.max(...parts.map(([, , ws, len]) => ws + len)) + step - (last[1] + last[3]);
}

function where(start, dur) {
  const v = state.view;
  const bar = Math.floor(start / v.steps_per_bar) + 1;
  const beat = Math.floor((start % v.steps_per_bar) / v.steps_per_beat) + 1;
  const beats = dur / v.steps_per_beat;
  const len = Number.isInteger(beats) ? beats : beats.toFixed(2).replace(/0+$/, "");
  return `bar ${bar}, beat ${beat}, ${len} beat${beats === 1 ? "" : "s"} long`;
}

// Sounds that are not notes are drawn as shapes, so that they are never mistaken for bars:
// a sweep is a slanted line, a swell a growing wedge, an impact a stroke with a fading tail.
function drawEffects(c, v, g, px) {
  const colour = css("--effect");
  const yMid = (pitch) => g.axisH + (g.hi - pitch) * g.rowH + g.rowH / 2;
  const floor = g.axisH + (g.hi - g.lo + 1) * g.rowH;
  const names = { riser: "Riser", fall: "Fall", swell: "Swell", impact: "Impact" };
  c.save();
  c.strokeStyle = c.fillStyle = colour;
  c.lineCap = "round";
  for (const e of v.effects) {
    const x0 = e.start * px, x1 = Math.max(x0 + 3, e.end * px);
    let box;
    c.setLineDash(e.noise ? [5, 4] : []);
    if (e.kind === "riser" || e.kind === "fall") {
      const [from, to] = e.kind === "riser" ? [e.low, e.high] : [e.high, e.low];
      c.lineWidth = 2.5;
      c.beginPath(); c.moveTo(x0, yMid(from)); c.lineTo(x1, yMid(to)); c.stroke();
      c.setLineDash([]);
      c.beginPath(); c.arc(x1, yMid(to), 3.5, 0, 2 * Math.PI); c.fill();
      box = { x: x0, y: Math.min(yMid(from), yMid(to)) - 4, w: x1 - x0, h: Math.abs(yMid(from) - yMid(to)) + 8, pitch: Math.round(to) };
    } else if (e.kind === "swell") {
      const ym = yMid(e.low), half = Math.max(5, g.rowH * 1.4);
      c.beginPath(); c.moveTo(x0, ym); c.lineTo(x1, ym - half); c.lineTo(x1, ym + half); c.closePath();
      c.lineWidth = 1.5;
      if (e.noise) c.stroke(); else { c.globalAlpha = 0.7; c.fill(); c.globalAlpha = 1; }
      box = { x: x0, y: ym - half, w: x1 - x0, h: 2 * half, pitch: Math.round(e.low) };
    } else {
      const tall = Math.min(floor - g.axisH, Math.max(18, g.rowH * 5));
      c.setLineDash([]);
      c.globalAlpha = 0.7;
      c.beginPath(); c.moveTo(x0, floor - tall); c.lineTo(x1, floor); c.lineTo(x0, floor); c.closePath(); c.fill();
      c.globalAlpha = 1;
      c.lineWidth = 2;
      c.beginPath(); c.moveTo(x0, g.axisH + 2); c.lineTo(x0, floor); c.stroke();
      box = { x: x0, y: floor - tall, w: x1 - x0, h: tall, pitch: null };
    }
    state.hits.push({ ...box, start: e.start, dur: e.end - e.start, label: names[e.kind] + (e.noise ? " (hiss)" : "") });
  }
  c.restore();
}

function hover(event) {
  const tip = $("tip");
  if (!state.view) return;
  const box = $("notes").getBoundingClientRect();
  const x = event.clientX - box.left, y = event.clientY - box.top;
  let found = null;
  for (let i = state.hits.length - 1; i >= 0; i--) {
    const h = state.hits[i];
    if (x >= h.x - 1 && x <= h.x + h.w + 1 && y >= h.y - 1 && y <= h.y + h.h + 1) { found = h; break; }
  }
  if (!found) { tip.hidden = true; return; }
  tip.innerHTML = "";
  const strong = document.createElement("b");
  strong.textContent = found.label;
  tip.append(strong, ` ${found.pitch === null ? "" : pitchName(found.pitch) + ", "}${where(found.start, found.dur)}`);
  tip.hidden = false;
  const host = tip.parentElement.getBoundingClientRect();
  const left = Math.min(event.clientX - host.left + 14, host.width - tip.offsetWidth - 8);
  tip.style.left = Math.max(4, left) + "px";
  tip.style.top = event.clientY - host.top - 34 + "px";
}

// ---------------------------------------------------------------------- playing
const active = () => document.querySelector('input[name="ab"]:checked').value;
const lead = (which) => (which === "original" && state.originalIsRecording && state.view ? state.view.offset : 0);   // first beat in a recording
const musicTime = () => players[active()].currentTime - lead(active());
const total = () => (state.view ? state.view.steps * state.view.step_seconds : 0);
const mmss = (t) => `${Math.floor(Math.max(0, t) / 60)}:${String(Math.floor(Math.max(0, t) % 60)).padStart(2, "0")}`;

function clock() { $("clock").textContent = `${mmss(musicTime())} / ${mmss(total())}`; }

function playhead() {
  const g = state.geometry, v = state.view, el = $("playhead");
  if (!g || !v) return;
  const x = KEYS_W + (unfold(Math.max(0, Math.min(v.steps, musicTime() / v.step_seconds)), false) || 0) * g.px;
  el.hidden = false;
  el.style.left = x + "px";
  el.style.height = g.H + "px";
  return x;
}

let raf = 0;
function tick() {
  const x = playhead();
  clock();
  const roll = $("roll");
  if (x !== undefined && (x > roll.scrollLeft + roll.clientWidth - 60 || x < roll.scrollLeft + KEYS_W)) roll.scrollLeft = Math.max(0, x - KEYS_W - 40);
  if (!players[active()].paused) raf = requestAnimationFrame(tick);
}

function stop() {
  players.original.pause();
  players.chip.pause();
  cancelAnimationFrame(raf);
  $("play").textContent = "Play";
}

async function toggle() {
  const p = players[active()];
  if (!p.src) return;
  if (!p.paused) { stop(); return; }
  if (musicTime() >= total() - 0.05) p.currentTime = Math.max(0, lead(active()));
  try {
    await p.play();
    $("play").textContent = "Pause";
    raf = requestAnimationFrame(tick);
  } catch (err) {
    status("The browser would not play the sound: " + err.message, true);
  }
}

function seek(seconds) {
  const which = active();
  players[which].currentTime = Math.max(0, seconds + lead(which));
  playhead();
  clock();
}

function swap(event) {
  const now = event.target.value, before = now === "original" ? "chip" : "original";
  const t = players[before].currentTime - lead(before);
  const playing = !players[before].paused;
  players[before].pause();
  if (!players[now].src) return;
  players[now].currentTime = Math.max(0, t + lead(now));
  if (playing) players[now].play().then(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(tick); }).catch(() => stop());
}

function save(name, blob) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

// ---------------------------------------------------------------------- wiring
$("pick").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", (e) => chooseFile(e.target.files[0]));
$("example").addEventListener("change", chooseExample);
$("example-as").addEventListener("change", sourceChanged);
$("write").addEventListener("click", () => {
  const panel = $("sketch");
  panel.hidden = !panel.hidden;
  $("write").setAttribute("aria-expanded", String(!panel.hidden));
  if (!panel.hidden) $("tune").focus();
});
$("tune-use").addEventListener("click", useTune);
$("style").addEventListener("change", styleChanged);
$("form").addEventListener("change", () => { state.form = $("form").value.trim() || null; convert(true); });
$("form").addEventListener("keydown", (e) => { if (e.key === "Enter") $("form").blur(); });
const keyChanged = () => { state.key = $("key").value ? `${$("key").value} ${$("mode").value}` : ""; state.chords = null; convert(true); };
$("key").addEventListener("change", keyChanged);
$("mode").addEventListener("change", keyChanged);
$("ending").addEventListener("change", () => convert(true));
$("hum").addEventListener("click", toggleHum);
$("chords-use").addEventListener("click", () => { state.chords = $("chords").value.trim() || null; convert(true); });
$("chords-auto").addEventListener("click", () => { state.chords = null; convert(true); });
$("chords").addEventListener("keydown", (e) => { if (e.key === "Enter") $("chords-use").click(); });
$("go").addEventListener("click", () => convert(false));
$("stop").addEventListener("click", stopEngine);
$("tempo").addEventListener("keydown", (e) => { if (e.key === "Enter") convert(false); });
$("play").addEventListener("click", toggle);
document.querySelectorAll('input[name="ab"]').forEach((r) => r.addEventListener("change", swap));
document.querySelectorAll("#legend input").forEach((box) => box.addEventListener("change", draw));
for (const p of Object.values(players)) p.addEventListener("ended", () => { stop(); clock(); });
$("notes").addEventListener("mousemove", hover);
$("notes").addEventListener("mouseleave", () => { $("tip").hidden = true; });
$("notes").addEventListener("click", (e) => {
  if (!state.view || !state.geometry || edit.on) return;    // while editing, the pointer writes notes (below)
  seek(((e.clientX - $("notes").getBoundingClientRect().left) / state.geometry.px) * state.view.step_seconds);
});
$("roll").addEventListener("keydown", (e) => {
  if (!state.view) return;
  if (e.key === " ") { e.preventDefault(); toggle(); }
  if (edit.on) return editKey(e);
  const bar = state.view.steps_per_bar * state.view.step_seconds;
  if (e.key === "ArrowRight") { e.preventDefault(); seek(Math.min(total(), musicTime() + bar)); }
  if (e.key === "ArrowLeft") { e.preventDefault(); seek(Math.max(0, musicTime() - bar)); }
});
$("dl-song").addEventListener("click", async () => {       // what is switched off is left out of the song
  if (!state.view) return;
  let text = state.view.song_json;
  try {
    if (muted().length) text = JSON.stringify(await ask("song", { mute: muted() }), null, 2) + "\n";
  } catch (err) {
    return status(err.message, true);
  }
  save(state.view.song_name + (muted().length ? "-part" : "") + ".json", new Blob([text], { type: "application/json" }));
});
$("lead-sound").addEventListener("change", () => convert(true));
$("chip").addEventListener("change", () => convert(true));
$("longer").addEventListener("click", () => {             // the form made long by arrangement: an introduction, a quiet part, a lift
  if (!state.view || !state.view.longer) return;
  state.form = state.view.longer;
  $("ending").checked = true;
  convert(true);
});
$("theme").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true));
$("dl-wav").addEventListener("click", () => state.chipBytes && save(state.view.song_name + "-chip.wav", new Blob([state.chipBytes], { type: "audio/wav" })));
$("dl-midi").addEventListener("click", async () => {
  if (!state.view || state.busy) return;
  try { save(state.view.song_name + ".mid", new Blob([await ask("midi", {})], { type: "audio/midi" })); } catch (err) { status(err.message, true); }
});

// ---------------------------------------------------------------------- the tune on the roll
// With "Edit the tune on the roll" the lead is a list of notes that the pointer, the computer's keys and a MIDI
// keyboard change. Every change is drawn at once and, a moment later, handed to the engine, which writes the
// other voices to it again. Notes are [start, length, pitch] in steps of a quarter beat.
const KEY_PITCH = { a: 0, w: 1, s: 2, e: 3, d: 4, f: 5, t: 6, g: 7, y: 8, h: 9, u: 10, j: 11, k: 12 };

function tuneMeta() {
  const tempo = Number($("tune-tempo").value.replace(",", "."));
  return { tempo: tempo >= 30 && tempo <= 300 ? tempo : 120, meter: $("tune-meter").value.split("/").map(Number) };
}

function editSteps() {                                      // what is written, and two empty bars to write on
  const { meter } = tuneMeta();
  const bar = (meter[0] * 16) / meter[1];
  const end = Math.max(edit.cursor, ...edit.notes.map((n) => n[0] + n[1]), 0);
  return Math.max(8 * bar, (Math.ceil(end / bar) + 2) * bar);
}

function blankView() {                                      // a roll with nothing on it yet
  const { tempo, meter } = tuneMeta();
  return { kind: "midi", title: "A tune", tempo, meter, steps: 0, steps_per_beat: 4, steps_per_bar: (meter[0] * 16) / meter[1],
    step_seconds: 15 / tempo, pitch_range: [60, 72], source: [], voices: [], drums: [], source_drums: [], effects: [], played: null,
    instruments: [], offset: 0 };
}

function beep(pitch) {                                      // the note under the finger, at once
  try {
    edit.audio = edit.audio || new (window.AudioContext || window.webkitAudioContext)();
    const ctx = edit.audio, osc = ctx.createOscillator(), gain = ctx.createGain();
    osc.type = "square";
    osc.frequency.value = 440 * Math.pow(2, (pitch - 69) / 12);
    gain.gain.setValueAtTime(0.07, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.22);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.24);
  } catch (err) { /* no sound here: the note is still written */ }
}

function commit(soon) {                                     // draw now; tell the engine when the hand has rested
  clearTimeout(edit.timer);
  edit.timer = setTimeout(applyTune, soon ? 0 : 700);
  draw();
}

async function applyTune() {
  if (!edit.on) return;
  if (state.busy) return commit();
  if (!edit.notes.length) return status("The roll is empty. Click on it to add a note, or play one.");
  const { tempo, meter } = tuneMeta();
  const notes = edit.notes.map(([s, d, p]) => [s / 4, d / 4, p]);
  const sections = [...edit.sections];
  state.source = { id: "tune:" + JSON.stringify([notes, sections, tempo, meter]), name: "A tune", tune: { notes, sections, tempo, meter }, midi: true };
  $("example").value = "";
  $("arranger").value = "expand";
  if (Number($("voices").value) < 4) $("voices").value = "4";
  $("chosen").textContent = "A tune of your own. The arranger writes the other parts; change the style and the chords below.";
  sourceChanged();
  await convert(false);
}

function fromView() {                                       // the tune as the engine has it, in quarter beats
  const v = state.view;
  if (!v) return [];
  const own = state.source && state.source.tune && v.written;          // as it was written, not as its form plays it
  const k = own ? 4 : 4 / v.steps_per_beat;
  const lead = own ? v.written : ((v.voices.find((x) => x.role === "lead") || v.voices[0] || {}).notes || []);
  return lead.map(([s, d, p]) => [Math.round(s * k), Math.max(1, Math.round(d * k)), p]).sort((a, b) => a[0] - b[0] || a[2] - b[2]);
}

function setEditing(on, heard) {                            // ``heard``: notes to begin with, from a hummed tune
  if (on && state.busy) return status("Still working on the last piece. Try again in a moment.");
  edit.on = on;
  $("edit").setAttribute("aria-pressed", String(on));
  $("edit").textContent = on ? "Done editing" : "Edit the tune on the roll";
  $("edit-tools").hidden = !on;
  $("roll").classList.toggle("editing", on);
  if (!on) { clearTimeout(edit.timer); return draw(); }
  const own = !!(state.source && state.source.tune);
  if (state.view && !own && !heard) {                       // a converted piece: its lead becomes a tune to work on
    $("tune-tempo").value = String(Math.round(state.view.tempo));
    const meter = state.view.meter.join("/");
    if ([...$("tune-meter").options].some((o) => o.value === meter)) $("tune-meter").value = meter;
  }
  edit.notes = heard || fromView();
  edit.sections = heard || !own || !state.view ? [] : (state.view.sections || []).filter((bar) => bar > 0);
  edit.sel = -1;
  edit.cursor = Math.max(0, ...edit.notes.map((n) => n[0] + n[1]));
  $("sketch").hidden = false;
  $("write").setAttribute("aria-expanded", "true");
  if (!state.view) { state.view = blankView(); $("empty").hidden = true; }
  listenToMidi();
  if ((heard || !own) && edit.notes.length) commit(true); else draw();
  $("roll").focus();
}

// ---------------------------------------------------------------------- humming a tune in
async function toggleHum() {
  if (hum.rec) return hum.rec.stop();
  if (state.busy) return status("Still working on the last piece. Try again in a moment.");
  if (!state.engine) return status("The engine is still starting. Try again in a moment.");
  if (!state.engine.numpy) return status("Listening to a voice needs NumPy, which did not load here.", true);
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
    return status("This browser gives a page no microphone. Write the tune as text, or on the roll.", true);
  }
  try {                                                     // the voice as it is: nothing taken out, nothing levelled
    hum.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
  } catch (err) {
    return status("The microphone was not allowed, or there is none. Write the tune as text, or on the roll.", true);
  }
  stop();
  hum.chunks = [];
  hum.rec = new MediaRecorder(hum.stream);
  hum.rec.ondataavailable = (e) => { if (e.data.size) hum.chunks.push(e.data); };
  hum.rec.onstop = heardHum;
  hum.rec.start();
  hum.timer = setTimeout(() => hum.rec && hum.rec.stop(), 60000);
  $("hum").textContent = "Stop and write it down";
  $("hum").setAttribute("aria-pressed", "true");
  status(`Listening. Hum, sing or whistle the tune, one note after another, at about ${tuneMeta().tempo} beats a minute. Then stop.`);
}

// Playhead's analysis (web/vendor/playhead), fetched the first time it is wanted: it hears the tempo of what was
// hummed, so that none has to be set first.  Nothing leaves the page.
let playheadLoad = null;
function loadPlayhead() {
  if (window.WL) return Promise.resolve(window.WL);
  playheadLoad = playheadLoad || new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "vendor/playhead/analysis.js?v=0.4.0";
    script.onload = () => (window.WL ? resolve(window.WL) : reject(new Error("Playhead did not start.")));
    script.onerror = () => { playheadLoad = null; reject(new Error("Playhead did not load.")); };
    document.head.append(script);
  });
  return playheadLoad;
}

async function heardTempo(samples) {                        // beats a minute, or null where Playhead is not sure of a pulse
  const WL = await loadPlayhead();
  const sound = { sampleRate: RATE, numberOfChannels: 1, length: samples.length, duration: samples.length / RATE, getChannelData: () => samples };
  const rhythm = WL.rhythmOf(await WL.analyse(sound, () => {}));
  return rhythm && rhythm.tempo >= 40 && rhythm.tempo <= 220 && rhythm.medClar >= 0.4 ? rhythm.tempo : null;
}

async function heardHum() {
  clearTimeout(hum.timer);
  const blob = new Blob(hum.chunks, { type: hum.rec.mimeType });
  hum.stream.getTracks().forEach((track) => track.stop());
  hum.rec = hum.stream = null;
  $("hum").textContent = "Hum it instead";
  $("hum").setAttribute("aria-pressed", "false");
  if (state.busy) return status("Still working on the last piece. Hum it again in a moment.");
  state.busy = true;
  progress(null);
  let facts = null, found = null;
  try {
    status("Writing down what was hummed…");
    const got = await decode(await blob.arrayBuffer(), 60);
    const { tempo, meter } = tuneMeta();
    if ($("hum-tempo").checked) {
      try { found = await heardTempo(got.samples); } catch (err) { found = null; }     // without it: the tempo that is set
    }
    facts = await ask("open_hum", { rate: RATE, tempo: found || tempo, meter, grid: Number($("snap").value) / 4 }, got.samples);
  } catch (err) {
    status(err.message, true);
  } finally {
    state.busy = false;
    progress(undefined);
  }
  if (!facts) return;
  state.opened = null;
  state.form = null;
  $("tune-tempo").value = String(Math.round(facts.tempo));
  state.after = `Heard ${facts.hummed} notes at about ${Math.round(facts.tempo)} beats a minute` +
    ($("hum-tempo").checked ? (found ? ", the tempo Playhead heard" : "; Playhead was not sure of the tempo, so the one set was taken") : "") +
    ". They are on the roll: mend what was misheard, then play it.";
  setEditing(true, facts.written.map(([s, d, p]) => [Math.round(s * 4), Math.max(1, Math.round(d * 4)), p]));
}

function cell(event) {
  const g = state.geometry, box = $("notes").getBoundingClientRect();
  const x = event.clientX - box.left, y = event.clientY - box.top;
  return { x, step: Math.max(0, Math.floor(x / g.px)), pitch: g.hi - Math.floor((y - g.axisH) / g.rowH), ruler: y < g.axisH };
}

function noteAt(step, pitch) {
  for (let i = edit.notes.length - 1; i >= 0; i--) {
    const [s, d, p] = edit.notes[i];
    if (p === pitch && step >= s && step < s + d) return i;
  }
  return -1;
}

const snapped = (step) => Math.floor(step / edit.length) * edit.length;

function playNote(pitch) {                                  // a key was pressed, here or on a MIDI keyboard: write it down
  if (!edit.on || pitch < 12 || pitch > 119) return;
  if (rec.on) return keyDown(pitch);
  beep(pitch);
  edit.notes.push([edit.cursor, edit.length, pitch]);
  edit.sel = edit.notes.length - 1;
  edit.cursor += edit.length;
  commit();
  const roll = $("roll"), x = KEYS_W + edit.cursor * state.geometry.px;
  if (x > roll.scrollLeft + roll.clientWidth - 40) roll.scrollLeft = x - roll.clientWidth / 2;
}

// ---------------------------------------------------------------------- playing a tune in, in time
// One bar is counted in, the click goes on, and every key - the computer's or a MIDI keyboard's - is written where
// and as long as it was played, on the note value chosen for hummed and played notes.
function click(at, first) {
  const ctx = edit.audio, osc = ctx.createOscillator(), gain = ctx.createGain();
  osc.type = "square";
  osc.frequency.value = first ? 1760 : 1175;
  gain.gain.setValueAtTime(first ? 0.09 : 0.05, at);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.04);
  osc.connect(gain).connect(ctx.destination);
  osc.start(at);
  osc.stop(at + 0.05);
}

function record(on) {
  if (on === rec.on) return;
  if (!on) {
    clearInterval(rec.ticker);
    for (const pitch of [...rec.held.keys()]) keyUp(pitch);
    rec.on = false;
    const grid = Number($("snap").value), late = (edit.audio.outputLatency || 0) + (edit.audio.baseLatency || 0);
    let count = 0;
    for (const [down, up, pitch] of rec.notes) {
      const at = ((down - late - rec.t0) / rec.beat) * 4;                 // in sixteenths from the first beat
      if (at < -grid / 2) continue;                                       // played while it was being counted in
      const start = Math.max(0, Math.round(at / grid) * grid);
      edit.notes.push([rec.from + start, Math.max(grid, Math.round((((up - down) / rec.beat) * 4) / grid) * grid), pitch]);
      edit.cursor = Math.max(edit.cursor, rec.from + start + grid);
      count++;
    }
    edit.sel = -1;
    $("rec").setAttribute("aria-pressed", "false");
    $("rec").textContent = "Record in time";
    if (!count) { status("Nothing was played."); return draw(); }
    state.after = `${count} note${count === 1 ? "" : "s"} written down as played, on ${$("snap").selectedOptions[0].text}. Mend them on the roll.`;
    return commit(true);
  }
  if (state.busy) return status("Still working on the last piece. Try again in a moment.");
  stop();
  const { tempo, meter } = tuneMeta();
  edit.audio = edit.audio || new (window.AudioContext || window.webkitAudioContext)();
  if (edit.audio.state === "suspended") edit.audio.resume();
  const bar = (meter[0] * 16) / meter[1];
  rec.beat = 60 / tempo;
  rec.perBar = Math.max(1, Math.round((meter[0] * 4) / meter[1]));
  rec.from = Math.ceil(edit.cursor / bar) * bar;                          // from the next bar line on
  rec.t0 = edit.audio.currentTime + 0.15 + rec.perBar * rec.beat;        // after one bar of clicks
  rec.next = -rec.perBar;
  rec.notes = [];
  rec.held.clear();
  rec.on = true;
  const ahead = () => {                                                   // keep the next clicks ordered a little ahead
    while (rec.t0 + rec.next * rec.beat < edit.audio.currentTime + 0.4) {
      click(rec.t0 + rec.next * rec.beat, ((rec.next % rec.perBar) + rec.perBar) % rec.perBar === 0);
      rec.next++;
    }
    if (rec.next > 64 * rec.perBar) record(false);                        // sixty-four bars are enough for one go
  };
  ahead();
  rec.ticker = setInterval(ahead, 100);
  edit.cursor = rec.from;
  $("rec").setAttribute("aria-pressed", "true");
  $("rec").textContent = "Stop recording";
  status(`Recording at ${tempo} beats a minute: one bar is counted in, then play. The notes go on ${$("snap").selectedOptions[0].text}.`);
  draw();
  $("roll").focus();
}

function keyDown(pitch) {
  if (rec.held.has(pitch)) return;
  rec.held.set(pitch, edit.audio.currentTime);
  beep(pitch);
}

function keyUp(pitch) {
  const down = rec.held.get(pitch);
  if (!rec.on || down === undefined) return;
  rec.held.delete(pitch);
  rec.notes.push([down, edit.audio.currentTime, pitch]);
}

function tidy() {                                           // every note on the chosen note value
  const grid = Number($("snap").value), seen = new Set();
  edit.notes = edit.notes
    .map(([s, d, p]) => [Math.round(s / grid) * grid, Math.max(grid, Math.round(d / grid) * grid), p])
    .filter(([s, , p]) => !seen.has(s + ":" + p) && seen.add(s + ":" + p))
    .sort((a, b) => a[0] - b[0] || a[2] - b[2]);
  edit.sel = -1;
  edit.cursor = Math.max(0, ...edit.notes.map((n) => n[0] + n[1]));
  if (!edit.notes.length) return draw();
  state.after = `Every note is on ${$("snap").selectedOptions[0].text} now.`;
  return commit(true);
}

function setTheme(theme, keep) {
  document.documentElement.dataset.theme = theme;
  $("theme").textContent = theme === "dark" ? "Light" : "Dark";
  $("theme").setAttribute("aria-pressed", String(theme === "dark"));
  if (keep) try { localStorage.setItem("eigenchip-theme", theme); } catch (err) { /* not kept: it lasts for this visit */ }
}

function editKey(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (key in KEY_PITCH) { e.preventDefault(); if (!e.repeat) playNote(12 * (edit.octave + 1) + KEY_PITCH[key]); return; }
  if (key === "z" || key === "x") { edit.octave = Math.max(1, Math.min(7, edit.octave + (key === "x" ? 1 : -1))); midiNote(); return; }
  if (key === "." || key === "0") { e.preventDefault(); edit.cursor += edit.length; edit.sel = -1; return draw(); }
  if (key === "ArrowRight" || key === "ArrowLeft") {
    e.preventDefault();
    edit.cursor = Math.max(0, edit.cursor + (key === "ArrowRight" ? edit.length : -edit.length));
    return draw();
  }
  if ((key === "ArrowUp" || key === "ArrowDown") && edit.sel >= 0) {
    e.preventDefault();
    const n = edit.notes[edit.sel];
    n[2] = Math.max(12, Math.min(119, n[2] + (key === "ArrowUp" ? 1 : -1) * (e.shiftKey ? 12 : 1)));
    beep(n[2]);
    return commit();
  }
  if (key === "Delete" && edit.sel >= 0) { e.preventDefault(); edit.notes.splice(edit.sel, 1); edit.sel = -1; return commit(); }
  if (key === "Backspace") {                                // take back what was played last: the note that ends at the cursor
    e.preventDefault();
    let last = -1;
    edit.notes.forEach((n, i) => { if (n[0] + n[1] === edit.cursor && (last < 0 || n[0] >= edit.notes[last][0])) last = i; });
    if (last >= 0) { edit.cursor = edit.notes[last][0]; edit.notes.splice(last, 1); edit.sel = -1; return commit(); }
    edit.cursor = Math.max(0, edit.cursor - edit.length);
    return draw();
  }
}

function midiNote() {
  const names = edit.midi ? [...edit.midi.inputs.values()].map((i) => i.name).filter(Boolean) : [];
  $("edit-midi").textContent = (!navigator.requestMIDIAccess ? "This browser gives a page no MIDI keyboard; the computer's keys work."
    : edit.midi === false ? "The MIDI keyboard was not allowed; the computer's keys work."
      : names.length ? "MIDI keyboard: " + names.join(", ") + "."
        : "No MIDI keyboard found; plug one in, or use the computer's keys.") + ` Keys play octave ${edit.octave}.`;
}

async function listenToMidi() {
  midiNote();
  if (!navigator.requestMIDIAccess || edit.midi) return;
  try {
    edit.midi = await navigator.requestMIDIAccess();
  } catch (err) {
    edit.midi = false;
    return midiNote();
  }
  const hook = () => {
    for (const input of edit.midi.inputs.values()) {
      input.onmidimessage = (m) => {
        const kind = m.data[0] & 0xf0;
        if (kind === 0x90 && m.data[2] > 0) playNote(m.data[1]);
        else if (kind === 0x80 || kind === 0x90) keyUp(m.data[1]);       // a key let go: only a recording cares
      };
    }
    midiNote();
  };
  edit.midi.onstatechange = hook;
  hook();
}

$("edit").addEventListener("click", () => { record(false); setEditing(!edit.on); });
$("rec").addEventListener("click", () => record(!rec.on));
$("edit-tidy").addEventListener("click", tidy);
$("roll").addEventListener("keyup", (e) => {
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (rec.on && key in KEY_PITCH) keyUp(12 * (edit.octave + 1) + KEY_PITCH[key]);
});
setTheme(document.documentElement.dataset.theme || "light", false);
$("edit-length").addEventListener("change", (e) => { edit.length = Number(e.target.value); $("roll").focus(); });
$("edit-clear").addEventListener("click", () => { edit.notes = []; edit.sections = []; edit.sel = -1; edit.cursor = 0; draw(); status("The roll is empty. Click on it to add a note, or play one."); });
$("tune-tempo").addEventListener("change", () => { if (edit.on) commit(true); });
$("tune-meter").addEventListener("change", () => { if (edit.on) commit(true); });
$("notes").addEventListener("pointerdown", (e) => {
  if (!edit.on || !state.geometry || e.button !== 0) return;
  const at = cell(e);
  $("roll").focus();
  if (at.ruler) { edit.cursor = snapped(at.step); edit.sel = -1; return draw(); }
  if (at.pitch < 12 || at.pitch > 119) return;
  let i = noteAt(at.step, at.pitch);
  const added = i < 0;
  if (added) {
    edit.notes.push([snapped(at.step), edit.length, at.pitch]);
    i = edit.notes.length - 1;
  }
  const n = edit.notes[i];
  const end = (n[0] + n[1]) * state.geometry.px;
  edit.sel = i;
  edit.drag = { i, grow: n[1] * state.geometry.px > 10 && at.x > end - 5, by: at.step - n[0], moved: added };
  edit.cursor = n[0] + n[1];
  beep(n[2]);
  $("notes").setPointerCapture(e.pointerId);
  draw();
});
$("notes").addEventListener("pointermove", (e) => {
  const d = edit.drag;
  if (!edit.on || !d) return;
  const at = cell(e), n = edit.notes[d.i];
  const before = n.join();
  if (d.grow) n[1] = Math.max(1, snapped(at.step) + edit.length - n[0]);
  else {
    n[0] = Math.max(0, snapped(at.step - d.by + edit.length / 2));
    if (at.pitch >= 12 && at.pitch <= 119 && at.pitch !== n[2]) { n[2] = at.pitch; beep(n[2]); }
  }
  if (n.join() !== before) { d.moved = true; edit.cursor = n[0] + n[1]; draw(); }
});
const dropNote = () => {
  const d = edit.drag;
  edit.drag = null;
  if (d && d.moved) commit(); else if (d) draw();
};
$("notes").addEventListener("pointerup", dropNote);
$("notes").addEventListener("pointercancel", dropNote);
$("notes").addEventListener("dblclick", (e) => {
  if (!edit.on) return;
  const at = cell(e), i = noteAt(at.step, at.pitch);
  if (at.ruler) {                                           // on a bar number: a new part of the tune begins here, or no longer does
    const bar = Math.floor(at.step / state.view.steps_per_bar);
    if (bar < 1) return status("The first part, A, begins with the tune. Double-click a later bar to begin part B there.");
    edit.sections = edit.sections.includes(bar) ? edit.sections.filter((b) => b !== bar) : [...edit.sections, bar].sort((a, b) => a - b);
    if (edit.sections.length > 25) edit.sections.length = 25;
    return edit.notes.length ? commit(true) : draw();
  }
  if (i < 0) return;
  edit.notes.splice(i, 1);
  const same = noteAt(at.step, at.pitch);                   // the first click of the two may have added one on top
  if (same >= 0) edit.notes.splice(same, 1);
  edit.sel = -1;
  commit();
});

let dragDepth = 0;
window.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; document.body.classList.add("dragging"); });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("dragging");
  if (e.dataTransfer.files.length) chooseFile(e.dataTransfer.files[0]);
});
let resizing = 0;
window.addEventListener("resize", () => { clearTimeout(resizing); resizing = setTimeout(draw, 150); });

(async function start() {
  try {
    const res = await fetch("../corpus/manifest.json", { cache: "no-cache" });
    state.examples = res.ok ? await res.json() : [];
  } catch (err) {
    state.examples = [];
  }
  const select = $("example");
  select.append(new Option("an example…", ""));
  for (const entry of state.examples) select.append(new Option(entry.title, entry.file));
  progress(null);
  try {
    await startEngine();
  } catch (err) {
    progress(undefined);
    status("The engine could not start: " + err.message + " Check the connection and reload.", true);
    return;
  }
  progress(undefined);
  $("version").textContent = state.engine.version;
  if (!state.engine.numpy) {
    for (const option of $("example-as").options) option.disabled = option.value !== "midi";
    status("Ready for MIDI files. Sound files are unavailable: NumPy did not load.", true);
  } else {
    status("Ready.");
  }
  if (state.examples.length) {
    select.value = state.examples[0].file;
    chooseExample();
    convert(false);                                        // show something straight away: the first example, as written
  } else {
    sourceChanged();
  }
})();
