/** Listening on this PC instead of the browser's speech service.
 *
 * Nyx's own app window (WebView2) has no speech service, and the one in Chrome and Edge needs the internet, so
 * in the app window voice heard nothing (Fixer Upper S33, "it doesn't listen"). The microphone itself works in
 * every window, so here the page only records: the level meter (`micVad`) says when a sentence starts and when
 * the pause after it is long enough, and that one sentence goes to `/api/voice/transcribe` as a small WAV.
 * The PC turns it into words (Whisper when installed, Windows dictation otherwise) and the words go on to the
 * chat exactly as the browser recognizer's would.
 *
 * The recording uses the meter's echo-cancelled stream, so Nyx's own voice is mostly gone from it already.
 */

import { authHeaders } from "../api";
import { onVad, vadState, vadStream } from "./micVad";

/** Speech kept from just before the meter said "speaking", so the first syllable is not cut off. */
const PRE_ROLL_MS = 350;
/** Shorter than this is a cough or a click, not a sentence. */
const MIN_SPEECH_MS = 300;
/** One sentence is cut here even if the owner has not paused, so the PC never gets a minute of audio. */
const MAX_SENTENCE_MS = 25_000;
const TARGET_RATE = 16_000;

export type EarCallbacks = {
  /** The words of one sentence (may be empty when nothing was understood). */
  heard: (text: string, info: { engine: string; ms: number }) => void;
  /** Something is being transcribed right now. */
  busy?: (on: boolean) => void;
  /** A reason for the owner, when the PC can't listen. */
  failed?: (message: string) => void;
};

type Ear = {
  context: AudioContext;
  node: ScriptProcessorNode;
  source: MediaStreamAudioSourceNode;
  offVad: () => void;
  timer: number;
};

let ear: Ear | null = null;

/** Mono float samples at `rate` → 16 kHz 16-bit mono WAV. */
export function encodeWav(samples: Float32Array, rate: number): ArrayBuffer {
  const ratio = rate / TARGET_RATE;
  const length = Math.max(0, Math.floor(samples.length / ratio));
  const out = new ArrayBuffer(44 + length * 2);
  const view = new DataView(out);
  const text = (at: number, s: string) => { for (let i = 0; i < s.length; i += 1) view.setUint8(at + i, s.charCodeAt(i)); };
  text(0, "RIFF"); view.setUint32(4, 36 + length * 2, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, TARGET_RATE, true); view.setUint32(28, TARGET_RATE * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, length * 2, true);
  for (let i = 0; i < length; i += 1) {
    // Average the source samples that fall into this output sample: a cheap low-pass, enough for speech.
    const from = Math.floor(i * ratio), to = Math.max(from + 1, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = from; j < to && j < samples.length; j += 1) sum += samples[j];
    const value = Math.max(-1, Math.min(1, sum / (to - from)));
    view.setInt16(44 + i * 2, value < 0 ? value * 0x8000 : value * 0x7fff, true);
  }
  return out;
}

function join(chunks: Float32Array[]): Float32Array {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Float32Array(total);
  let at = 0;
  for (const chunk of chunks) { out.set(chunk, at); at += chunk.length; }
  return out;
}

/** What can listen on this PC ("" when nothing can). */
export async function localEarEngine(): Promise<string> {
  try {
    const response = await fetch("/api/voice/ears", { headers: authHeaders() });
    if (!response.ok) return "";
    return String((await response.json())?.best ?? "");
  } catch {
    return "";
  }
}

async function transcribe(wav: ArrayBuffer): Promise<{ text: string; engine: string; ms: number }> {
  const response = await fetch("/api/voice/transcribe", {
    method: "POST", body: wav, headers: { ...authHeaders(), "Content-Type": "audio/wav" },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(String(body?.detail ?? `Listening on this PC failed (${response.status}).`));
  return { text: String(body.text ?? ""), engine: String(body.engine ?? ""), ms: Number(body.ms ?? 0) };
}

/** Start recording sentences from the meter's microphone. `pauseMs` says how long a pause ends a sentence.
 * `longestMs` skips sentences with more speech than that: the wake phrase only needs short ones, and a TV or a
 * conversation in the room then costs the PC nothing. */
export function startLocalEar(callbacks: EarCallbacks, pauseMs: () => number, longestMs = 0): boolean {
  if (ear) return true;
  const stream = vadStream();
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!stream || !Ctor) return false;
  const context = new Ctor();
  const source = context.createMediaStreamSource(stream);
  // ScriptProcessor is old but needs no separate worklet file and works in WebView2, Edge and Chrome alike.
  const node = context.createScriptProcessor(4096, 1, 1);
  const rate = context.sampleRate;
  const preRoll: Float32Array[] = [];
  let sentence: Float32Array[] = [];
  let recording = false;
  let startedAt = 0;
  let spokeFor = 0;
  let speechSince = 0;

  node.onaudioprocess = (event) => {
    const chunk = new Float32Array(event.inputBuffer.getChannelData(0));
    if (recording) { sentence.push(chunk); return; }
    preRoll.push(chunk);
    let kept = preRoll.reduce((n, c) => n + c.length, 0);
    while (preRoll.length > 1 && kept - preRoll[0].length >= (PRE_ROLL_MS / 1000) * rate) kept -= preRoll.shift()!.length;
  };
  source.connect(node);
  node.connect(context.destination);                     // a ScriptProcessor only runs while connected; it outputs silence

  const finish = () => {
    const audio = join(sentence);
    sentence = [];
    recording = false;
    if (spokeFor < MIN_SPEECH_MS || (longestMs && spokeFor > longestMs)) return;
    callbacks.busy?.(true);
    void transcribe(encodeWav(audio, rate))
      .then((heard) => callbacks.heard(heard.text.trim(), { engine: heard.engine, ms: heard.ms }))
      .catch((error: Error) => callbacks.failed?.(error.message))
      .finally(() => callbacks.busy?.(false));
  };

  const offVad = onVad((vad) => {
    const now = Date.now();
    if (vad.speaking) {
      speechSince = now;
      if (!recording) {
        recording = true;
        startedAt = now;
        spokeFor = 0;
        sentence = preRoll.splice(0, preRoll.length);
      }
    } else if (recording && speechSince) {
      spokeFor += now - speechSince;
      speechSince = 0;
    }
  });
  const timer = window.setInterval(() => {
    if (!recording) return;
    const vad = vadState();
    const tooLong = Date.now() - startedAt >= MAX_SENTENCE_MS;
    if (tooLong && speechSince) { spokeFor += Date.now() - speechSince; speechSince = Date.now(); }
    if (tooLong || (!vad.speaking && vad.silenceMs >= pauseMs())) finish();
  }, 90);

  ear = { context, node, source, offVad, timer };
  return true;
}

export function stopLocalEar(): void {
  if (!ear) return;
  window.clearInterval(ear.timer);
  ear.offVad();
  ear.node.onaudioprocess = null;
  try { ear.source.disconnect(); ear.node.disconnect(); } catch { /* already gone */ }
  void ear.context.close().catch(() => undefined);
  ear = null;
}

export function localEarRunning(): boolean {
  return ear !== null;
}
