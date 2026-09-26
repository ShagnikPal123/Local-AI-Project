/** Clap: hearing a sound that is not speech, with no internet (Project Null N86).
 *
 * Speech recognition needs a connection and only returns words. The owner asked
 * for a clap, a whistle, "a phrase, or something more" — while away, offline, or
 * with the background voice running. So this listens to the shape of the sound
 * instead of its meaning:
 *
 *  - **a clap** is a transient: near-silence, then a broadband bang that decays
 *    inside about a tenth of a second. Two of them inside 700 ms is a double clap.
 *  - **a whistle** is the opposite: one narrow band of energy, held.
 *  - **anything else** is taught by example. Three goes are averaged into a
 *    short list of band energies, and live audio is compared with it by dynamic
 *    time warping, so the same sound made faster or slower still matches.
 *
 * Nothing is recorded or uploaded: a frame becomes twelve numbers and is thrown
 * away. The microphone is opened with echo cancellation, so Nyx's own voice is
 * mostly subtracted — and the detector stays deaf while Nyx is speaking anyway.
 */

import { vadStream } from "./micVad";

const FRAME_MS = 24;
const BANDS = 12;
/** Frames kept for matching a taught sound: about 1.4 s. */
const WINDOW = 60;
/** A clap's energy has to be this many times the running floor. */
const CLAP_RATIO = 7;
/** …and must fall back below this many times the floor within CLAP_DECAY_MS. */
const CLAP_RESET = 2.5;
const CLAP_DECAY_MS = 180;
const DOUBLE_GAP = [110, 750];
const WHISTLE_MS = 260;
/** Nothing fires twice inside this window — one clap is one clap. */
const COOLDOWN_MS = 1500;

export type Heard =
  | { kind: "clap" | "double_clap" | "whistle"; at: number }
  | { kind: "taught"; id: string; at: number; distance: number };

export interface TaughtSound {
  id: string;
  template: number[][];
}

type Listener = (heard: Heard) => void;

let context: AudioContext | null = null;
let stream: MediaStream | null = null;
/** True when `stream` is the voice engine's microphone, not one this module opened. */
let borrowed = false;
let analyser: AnalyserNode | null = null;
let timeBuffer: Float32Array | null = null;
let freqBuffer: Float32Array | null = null;
let timer = 0;

const listeners = new Set<Listener>();
let taught: TaughtSound[] = [];
let sensitivity = 0.6;
let muted = false;

let floor = 0.004;
let lastFire = 0;
let clapAt = 0;
let clapArmed = false;
let whistleSince = 0;
const recent: number[][] = [];

/** Capture, for teaching: frames collected while `recording` is true. */
let recording: number[][] | null = null;

function emit(heard: Heard): void {
  lastFire = heard.at;
  listeners.forEach((listener) => {
    try { listener(heard); } catch { /* one bad listener must not deafen the rest */ }
  });
}

/** Twelve log-spaced band energies: enough to tell sounds apart, too little to reconstruct one. */
function bands(spectrum: Float32Array): number[] {
  const out: number[] = [];
  const size = spectrum.length;
  let start = 1;
  for (let b = 0; b < BANDS; b++) {
    const end = Math.max(start + 1, Math.round(size * Math.pow((b + 1) / BANDS, 2)));
    let sum = 0;
    for (let i = start; i < end && i < size; i++) sum += Math.pow(10, spectrum[i] / 20);
    out.push(sum / Math.max(1, end - start));
    start = end;
  }
  const total = out.reduce((a, b) => a + b, 0) || 1;
  return out.map((v) => v / total);   // shape, not loudness: the same clap near or far matches
}

function peakness(spectrum: Float32Array): { ratio: number; bin: number } {
  let peak = -Infinity, bin = 0, sum = 0;
  for (let i = 2; i < spectrum.length; i++) {
    const value = Math.pow(10, spectrum[i] / 20);
    sum += value;
    if (value > peak) { peak = value; bin = i; }
  }
  return { ratio: sum > 0 ? peak / sum : 0, bin };
}

/** Dynamic time warping distance between two sequences of band vectors (0 = identical). */
export function dtw(a: number[][], b: number[][]): number {
  if (!a.length || !b.length) return Infinity;
  const rows = a.length, cols = b.length;
  let previous = new Float64Array(cols + 1).fill(Infinity);
  let current = new Float64Array(cols + 1).fill(Infinity);
  previous[0] = 0;
  for (let i = 1; i <= rows; i++) {
    current[0] = Infinity;
    for (let j = 1; j <= cols; j++) {
      let cost = 0;
      for (let k = 0; k < BANDS; k++) {
        const diff = (a[i - 1][k] ?? 0) - (b[j - 1][k] ?? 0);
        cost += diff * diff;
      }
      current[j] = Math.sqrt(cost) + Math.min(previous[j], current[j - 1], previous[j - 1]);
    }
    [previous, current] = [current, previous];
  }
  return previous[cols] / (rows + cols);
}

/** Average three attempts into one template, by stretching each onto the first one's length. */
export function averageTemplates(takes: number[][][]): number[][] {
  const usable = takes.filter((take) => take.length > 2);
  if (usable.length === 0) return [];
  const length = Math.min(WINDOW, Math.round(usable.reduce((sum, take) => sum + take.length, 0) / usable.length));
  const out: number[][] = [];
  for (let i = 0; i < length; i++) {
    const frame = new Array(BANDS).fill(0);
    for (const take of usable) {
      const source = take[Math.min(take.length - 1, Math.round((i / (length - 1 || 1)) * (take.length - 1)))];
      for (let k = 0; k < BANDS; k++) frame[k] += (source[k] ?? 0) / usable.length;
    }
    out.push(frame.map((v) => Math.round(v * 10000) / 10000));
  }
  return out;
}

function tick(): void {
  if (!analyser || !timeBuffer || !freqBuffer) return;
  analyser.getFloatTimeDomainData(timeBuffer as Float32Array<ArrayBuffer>);
  analyser.getFloatFrequencyData(freqBuffer as Float32Array<ArrayBuffer>);

  let sum = 0;
  for (let i = 0; i < timeBuffer.length; i++) sum += timeBuffer[i] * timeBuffer[i];
  const rms = Math.sqrt(sum / timeBuffer.length);
  floor = rms < floor ? floor * 0.8 + rms * 0.2 : floor * 0.995 + rms * 0.005;
  const now = Date.now();

  const shape = bands(freqBuffer);
  recent.push(shape);
  if (recent.length > WINDOW) recent.shift();
  if (recording) {
    recording.push(shape);
    if (recording.length > WINDOW) recording.shift();
  }
  if (muted || now - lastFire < COOLDOWN_MS) return;

  const loud = rms > Math.max(floor * CLAP_RATIO, 0.02);
  const quiet = rms < Math.max(floor * CLAP_RESET, 0.01);
  const { ratio, bin } = peakness(freqBuffer);
  const hz = analyser.context.sampleRate / 2 * (bin / freqBuffer.length);

  // Whistle: one narrow band, held, and not very loud.
  if (ratio > 0.55 - (sensitivity - 0.6) * 0.3 && hz > 700 && hz < 4200 && rms > floor * 2.5) {
    if (!whistleSince) whistleSince = now;
    else if (now - whistleSince > WHISTLE_MS) {
      whistleSince = 0;
      emit({ kind: "whistle", at: now });
      return;
    }
  } else {
    whistleSince = 0;
  }

  // Clap: a bang that is over almost at once.
  if (loud && !clapArmed) {
    clapArmed = true;
    const previous = clapAt;
    clapAt = now;
    if (previous && now - previous > DOUBLE_GAP[0] && now - previous < DOUBLE_GAP[1]) {
      clapAt = 0;
      emit({ kind: "double_clap", at: now });
      return;
    }
  } else if (clapArmed && quiet) {
    clapArmed = false;
    if (clapAt && now - clapAt < CLAP_DECAY_MS) emit({ kind: "clap", at: now });
  } else if (clapArmed && now - clapAt > CLAP_DECAY_MS * 2) {
    clapArmed = false;   // a long loud noise is not a clap
    clapAt = 0;
  }

  // Taught sounds: compare the tail of what was heard with each template.
  if (taught.length && recent.length >= 8 && rms > floor * 2) {
    const threshold = 0.055 * (1.4 - sensitivity);
    for (const sound of taught) {
      const window = recent.slice(-Math.min(recent.length, Math.max(8, sound.template.length)));
      const distance = dtw(window, sound.template);
      if (distance < threshold) {
        emit({ kind: "taught", id: sound.id, at: now, distance });
        recent.length = 0;
        return;
      }
    }
  }
}

/** Start listening for sounds. Returns false when there is no microphone to open.
 *
 * When the voice is already listening, its microphone is borrowed rather than a
 * second one opened: the same echo-cancelled signal means Nyx's own speaker is
 * already subtracted before a clap is looked for.
 */
export async function startClapListening(): Promise<boolean> {
  if (context) return true;
  const shared = vadStream();
  if (shared) {
    borrowed = true;
    stream = shared;
  } else {
    const media = navigator.mediaDevices;
    if (!media?.getUserMedia) return false;
    try {
      borrowed = false;
      stream = await media.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: false } });
    } catch {
      return false;
    }
  }
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) { if (!borrowed) stream.getTracks().forEach((track) => track.stop()); stream = null; return false; }
  context = new Ctor();
  analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  analyser.smoothingTimeConstant = 0;
  timeBuffer = new Float32Array(analyser.fftSize);
  freqBuffer = new Float32Array(analyser.frequencyBinCount);
  context.createMediaStreamSource(stream).connect(analyser);
  timer = window.setInterval(tick, FRAME_MS);
  return true;
}

export function stopClapListening(): void {
  window.clearInterval(timer);
  timer = 0;
  // A borrowed microphone belongs to the voice engine; stopping its tracks would
  // deafen the thing that lent it.
  if (!borrowed) stream?.getTracks().forEach((track) => track.stop());
  borrowed = false;
  void context?.close().catch(() => undefined);
  context = null;
  stream = null;
  analyser = null;
  timeBuffer = null;
  freqBuffer = null;
  recent.length = 0;
  clapArmed = false;
  clapAt = 0;
}

export function clapListening(): boolean {
  return context !== null;
}

/** Deaf while Nyx is speaking, so it never answers itself. */
export function muteClap(on: boolean): void {
  muted = on;
  if (on) recent.length = 0;
}

export function setTaughtSounds(sounds: TaughtSound[]): void {
  taught = sounds.filter((sound) => sound.template?.length > 2);
}

export function setClapSensitivity(value: number): void {
  sensitivity = Math.min(0.95, Math.max(0.2, value));
}

export function onClap(listener: Listener): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** Record one take of a sound to teach. Resolves with its frames when `stopTeaching` is called. */
export function startTeaching(): void {
  recording = [];
}

export function stopTeaching(): number[][] {
  const take = recording ?? [];
  recording = null;
  // Trim the quiet lead-in and tail so the template is the sound itself.
  const energy = take.map((frame) => frame.reduce((a, b) => a + b, 0));
  const peak = Math.max(...energy, 0.0001);
  const first = energy.findIndex((value) => value > peak * 0.25);
  const last = energy.length - 1 - [...energy].reverse().findIndex((value) => value > peak * 0.25);
  return first >= 0 && last > first ? take.slice(first, last + 1) : take;
}
