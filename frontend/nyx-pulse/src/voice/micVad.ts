/** Hears *that* someone is speaking, without caring what they say.
 *
 * The microphone stream is opened with echo cancellation on, so the browser has
 * already subtracted the audio it is playing — Nyx's own voice is mostly gone
 * from this signal. That gives two things the recognizer cannot:
 *
 *   • the exact moment the owner stops talking, which is what makes the answer
 *     come straight after the pause instead of a second later;
 *   • an honest "someone is talking over Nyx" signal for barge-in.
 *
 * The level is measured against a noise floor that follows the room, so a noisy
 * fan or a quiet microphone both settle by themselves.
 */

const FRAME_MS = 25;
/** Speech has to stay up this long before it counts, so a door slam is not a word. */
const ATTACK_MS = 60;
/** …and stay down this long before the pause counts. */
const RELEASE_MS = 140;

export type VadState = {
  /** Someone is speaking into the microphone right now. */
  speaking: boolean;
  /** Milliseconds since speech last stopped (0 while speaking). */
  silenceMs: number;
  /** 0–1, for a level meter. */
  level: number;
};

type Listener = (state: VadState) => void;

let context: AudioContext | null = null;
let stream: MediaStream | null = null;
let analyser: AnalyserNode | null = null;
let timer = 0;
let buffer: Float32Array | null = null;

let floor = 0.004;
let speaking = false;
let aboveSince = 0;
let belowSince = 0;
let lastStop = 0;
let level = 0;

const listeners = new Set<Listener>();

function emit(): void {
  const state: VadState = { speaking, silenceMs: speaking ? 0 : Date.now() - lastStop, level };
  listeners.forEach((listener) => {
    try { listener(state); } catch { /* ignore */ }
  });
}

function tick(): void {
  if (!analyser || !buffer) return;
  analyser.getFloatTimeDomainData(buffer as Float32Array<ArrayBuffer>);
  let sum = 0;
  for (let i = 0; i < buffer.length; i += 1) sum += buffer[i] * buffer[i];
  const rms = Math.sqrt(sum / buffer.length);
  level = Math.min(1, rms * 12);

  // The floor falls fast towards quiet and creeps up slowly, so it tracks the
  // room rather than the voice sitting on top of it.
  floor = rms < floor ? floor * 0.85 + rms * 0.15 : floor * 0.995 + rms * 0.005;
  const threshold = Math.max(floor * 3.2, 0.006);
  const now = Date.now();

  if (rms > threshold) {
    belowSince = 0;
    if (!aboveSince) aboveSince = now;
    if (!speaking && now - aboveSince >= ATTACK_MS) { speaking = true; emit(); }
  } else {
    aboveSince = 0;
    if (!belowSince) belowSince = now;
    if (speaking && now - belowSince >= RELEASE_MS) {
      speaking = false;
      lastStop = now - RELEASE_MS;                       // the pause began when it went quiet
      emit();
    }
  }
}

/** Open the microphone for level detection. Safe to call again; it reuses the stream. */
export async function startVad(): Promise<boolean> {
  if (context) return true;
  const media = navigator.mediaDevices;
  if (!media?.getUserMedia) return false;
  try {
    stream = await media.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch {
    return false;                                        // blocked or no microphone: the word guard still works
  }
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) { stream.getTracks().forEach((t) => t.stop()); stream = null; return false; }
  context = new Ctor();
  analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  analyser.smoothingTimeConstant = 0;
  buffer = new Float32Array(analyser.fftSize);
  context.createMediaStreamSource(stream).connect(analyser);
  lastStop = Date.now();
  timer = window.setInterval(tick, FRAME_MS);
  return true;
}

export function stopVad(): void {
  window.clearInterval(timer);
  timer = 0;
  stream?.getTracks().forEach((track) => track.stop());
  void context?.close().catch(() => undefined);
  context = null;
  stream = null;
  analyser = null;
  buffer = null;
  speaking = false;
  level = 0;
}

export function vadRunning(): boolean {
  return context !== null;
}

/** The open microphone, so other listeners (the clap detector) can share it. */
export function vadStream(): MediaStream | null {
  return stream;
}

/** Current state without waiting for the next change. */
export function vadState(): VadState {
  return { speaking, silenceMs: speaking ? 0 : Date.now() - lastStop, level };
}

export function onVad(listener: Listener): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
