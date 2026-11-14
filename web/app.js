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

const state = {
  engine: null,          // {numpy, version} once Python is up
  source: null,          // {id, name, file?, example?, bytes?, midi}
  opened: null,          // what the engine currently holds (source + listening choices)
  facts: null,
  view: null,
  busy: false,
  chords: null,          // chords the user asked for (text), for the expanding arranger
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
    return ask("open_tune", { text: s.tune.text, tempo: s.tune.tempo, meter: s.tune.meter, title: s.name });
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
      state.facts = await open();
      state.opened = key;
    }
    progress(null);
    status("Arranging…");
    state.view = await ask("arrange", { arranger: $("arranger").value, voices: Number($("voices").value),
      expression: $("expression").value, style: $("style").value || "plain", chords: state.chords });
    show();
    status("Making the chip sound…");
    await sound();
    status(`Done in ${((performance.now() - started) / 1000).toFixed(1)} s. Play it, or choose another arranger in the table.`);
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

function written() {                                       // what only the expanding arranger has: a style, and chords to change
  const v = state.view, on = !!v && v.arranger === "expand";
  $("written").hidden = !on;
  $("chordline").hidden = !on;
  if (!on) return;
  const style = $("style");
  if (!style.options.length) for (const [name] of v.styles) style.append(new Option(name, name));
  style.value = v.style || "plain";
  $("style-about").textContent = (v.styles.find(([name]) => name === style.value) || [])[1] || "";
  $("chords").value = v.chords_text || "";
}

// ---------------------------------------------------------------------- which voices sound
const VOICE_NAMES = { lead: "Lead", bass: "Bass", inner: "Inner", chords: "Chords", kit: "Drums", bed: "Noise", fx: "Sweeps" };
const voiceName = (id) => VOICE_NAMES[id] || id.replace(/^inner(\d)$/, "Inner $1").replace(/^fx(\d)$/, "Sweeps $1");
const muted = () => [...state.mute].filter((id) => state.view && state.view.instruments.includes(id));

function hear() {
  const box = $("hear"), v = state.view;
  box.innerHTML = "";
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
    if (v.needs) parts.push("The song uses levels or slides, which need CLIo 2.1; choose \u201cplainly\u201d for one that CLIo 2.0 plays.");
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
  const lo = v.pitch_range[0] - 2, hi = v.pitch_range[1] + 2;
  const rows = hi - lo + 1;
  const rowH = Math.max(5, Math.min(12, Math.floor(310 / rows)));
  const axisH = 22;
  const hasDrums = v.drums.length > 0 || v.source_drums.length > 0;
  const drumH = hasDrums ? 26 : 0;
  const avail = Math.max(200, $("roll").clientWidth - KEYS_W - 2);
  const px = Math.max(1.5, Math.min(12, Math.max(avail / Math.max(1, v.steps), Math.min(6, 15000 / Math.max(1, v.steps)))));
  const W = Math.ceil(v.steps * px) + 2, H = axisH + rows * rowH + drumH + 4;
  const g = (state.geometry = { lo, hi, rowH, axisH, px, W, H, drumY: axisH + rows * rowH + 6 });
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
  for (let s = 0; s <= v.steps; s += v.steps_per_beat) {
    const bar = s % v.steps_per_bar === 0;
    if (!bar && v.steps_per_beat * px < 7) continue;
    c.fillStyle = bar ? "rgba(201,211,224,0.28)" : "rgba(201,211,224,0.09)";
    c.fillRect(Math.round(s * px), bar ? 4 : axisH, 1, H);
    const n = s / v.steps_per_bar;
    if (bar && n % everyBar === 0 && s < v.steps) { c.fillStyle = css("--screen-dim"); c.fillText(String(n + 1), s * px + 4, 15); }
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
  if (layerOn("source")) for (const [s, d, p] of v.source) note(s, d, p, css("--source"), v.kind === "audio" ? "Heard" : "In the file");
  const colours = { lead: css("--lead"), bass: css("--bass") };
  for (const voice of v.voices) {
    const layer = voice.role === "lead" || voice.role === "bass" ? voice.role : "third";
    if (!layerOn(layer)) continue;
    const label = voice.role === "chords" ? "Chords" : voice.role === "inner" ? "Inner voice" : voice.role[0].toUpperCase() + voice.role.slice(1);
    for (const [s, d, p] of voice.notes) note(s, d, p, colours[voice.role] || css("--third"), label);
  }
  if (v.played && layerOn("played")) for (const [s, d, p] of v.played) note(s, d, p, css("--screen-ink"), "Really played", true);
  if (hasDrums && layerOn("drums")) {
    c.fillStyle = css("--source");
    for (const s of v.source_drums) c.fillRect(s * px, g.drumY, Math.max(1.5, Math.min(3, px - 1)), 7);
    c.fillStyle = css("--screen-ink");
    for (const [s] of v.drums) c.fillRect(s * px, g.drumY + 9, Math.max(1.5, Math.min(3, px - 1)), 7);
  }
  if ((v.effects || []).length && layerOn("effects")) drawEffects(c, v, g, px);
  $("notes").setAttribute("aria-label", `Piano roll of ${v.title}: ${v.source.length} source notes and ${v.voices.length} chip voices.`);
  playhead();
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
  const x = KEYS_W + Math.max(0, Math.min(v.steps, musicTime() / v.step_seconds)) * g.px;
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
$("style").addEventListener("change", () => convert(true));
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
  if (!state.view || !state.geometry) return;
  seek(((e.clientX - $("notes").getBoundingClientRect().left) / state.geometry.px) * state.view.step_seconds);
});
$("roll").addEventListener("keydown", (e) => {
  if (!state.view) return;
  if (e.key === " ") { e.preventDefault(); toggle(); }
  const bar = state.view.steps_per_bar * state.view.step_seconds;
  if (e.key === "ArrowRight") { e.preventDefault(); seek(Math.min(total(), musicTime() + bar)); }
  if (e.key === "ArrowLeft") { e.preventDefault(); seek(Math.max(0, musicTime() - bar)); }
});
$("dl-song").addEventListener("click", () => state.view && save(state.view.song_name + ".json", new Blob([state.view.song_json], { type: "application/json" })));
$("dl-wav").addEventListener("click", () => state.chipBytes && save(state.view.song_name + "-chip.wav", new Blob([state.chipBytes], { type: "audio/wav" })));
$("dl-midi").addEventListener("click", async () => {
  if (!state.view || state.busy) return;
  try { save(state.view.song_name + ".mid", new Blob([await ask("midi", {})], { type: "audio/midi" })); } catch (err) { status(err.message, true); }
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
