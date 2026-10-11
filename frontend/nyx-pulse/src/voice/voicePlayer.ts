/** Plays Nyx's voice in the browser.
 *
 * The engine synthesizes speech (neural voices via edge-tts, Windows voices
 * offline) and announces it with a `voice.say` workspace event. Every open
 * window receives that event, so exactly one plays it: a Web Lock per clip, taken
 * first by a visible window (hidden ones wait a moment). Clips queue in order.
 *
 * `speakText` is the direct path for a "Listen" button: it asks for audio in a
 * role's voice without broadcasting to other windows.
 */

import { authHeaders } from "../api";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { registerSpoken, clearSpoken } from "./echoGuard";
import { emitVoice } from "./voiceBus";

/** One line to say. `ready` settles once its audio is fetched, so clips play in the order they were asked for even
 * when a later, shorter sentence comes back from the engine first. */
type Clip = { url: string | null; ready: Promise<void>; label: string; spoken?: string; dead?: boolean };

const queue: Clip[] = [];
let current: HTMLAudioElement | null = null;
let currentUrl = "";
let started = false;
let advancing = false;
/** Bumped by `stopSpeaking`: audio still being fetched for an older generation is thrown away, never played after a
 * barge-in. */
let generation = 0;
const stateListeners = new Set<(speaking: string | null) => void>();

function notify(label: string | null): void {
  stateListeners.forEach((listener) => listener(label));
  // Everything that listens (the voice engine, the hands-off bar) hears about
  // Nyx's own voice from one place, whoever asked for the clip.
  emitVoice({ type: "speaking", text: label });
}

export function onSpeakingChange(listener: (speaking: string | null) => void): () => void {
  stateListeners.add(listener);
  return () => stateListeners.delete(listener);
}

async function fetchAudio(path: string, init?: RequestInit): Promise<string> {
  const response = await fetch(path, { ...init, headers: { ...authHeaders(), ...(init?.headers ?? {}) } });
  if (!response.ok) {
    let detail = `${response.status}`;
    try { detail = (await response.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return URL.createObjectURL(await response.blob());
}

// --- how loud Ichos is right now, for the speaking face ------------------------------------------------------------
// `captureStream` copies the element's sound without rerouting it, so playback never depends on this AudioContext
// (a suspended context would otherwise mute the voice). Where it is missing, the face gets a speech-like envelope.

let outContext: AudioContext | null = null;
let outAnalyser: AnalyserNode | null = null;
let outSource: MediaStreamAudioSourceNode | null = null;
let outBins: Uint8Array | null = null;

function tap(audio: HTMLAudioElement): void {
  try {
    const capture = (audio as HTMLAudioElement & { captureStream?: () => MediaStream }).captureStream?.();
    if (!capture || !capture.getAudioTracks().length) return;
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    if (!outContext) {
      outContext = new Ctor();
      outAnalyser = outContext.createAnalyser();
      outAnalyser.fftSize = 256;
      outAnalyser.smoothingTimeConstant = 0.6;
      outBins = new Uint8Array(outAnalyser.frequencyBinCount);
    }
    void outContext.resume().catch(() => undefined);
    outSource?.disconnect();
    outSource = outContext.createMediaStreamSource(capture);
    outSource.connect(outAnalyser!);
  } catch {
    outSource = null;                                    // the envelope below stands in
  }
}

/** Fill `bands` (0–1 each, low to high) with what Ichos is saying right now; returns the overall level. */
export function outputLevels(bands: Float32Array): number {
  if (!current || current.paused) { bands.fill(0); return 0; }
  if (outSource && outAnalyser && outBins && outContext?.state === "running") {
    outAnalyser.getByteFrequencyData(outBins as Uint8Array<ArrayBuffer>);
    const usable = Math.floor(outBins.length * 0.7);     // the top of the spectrum is empty for speech
    let total = 0;
    for (let b = 0; b < bands.length; b += 1) {
      const from = Math.floor((b / bands.length) ** 1.6 * usable);
      const to = Math.max(from + 1, Math.floor(((b + 1) / bands.length) ** 1.6 * usable));
      let sum = 0;
      for (let i = from; i < to; i += 1) sum += outBins[i];
      bands[b] = Math.min(1, sum / (to - from) / 200);
      total += bands[b];
    }
    return Math.min(1, (total / bands.length) * 1.6);
  }
  const t = current.currentTime;
  const syllable = Math.max(0, Math.sin(t * 11.3)) * (0.55 + 0.45 * Math.sin(t * 2.7));
  for (let b = 0; b < bands.length; b += 1) bands[b] = syllable * (0.9 - (b / bands.length) * 0.6) * (0.75 + 0.25 * Math.sin(t * 17 + b));
  return syllable * 0.8;
}

// --- the queue ------------------------------------------------------------------------------------------------------

function enqueue(load: string | Promise<string>, label: string, spoken?: string): void {
  const born = generation;
  const clip: Clip = { url: null, label, spoken, ready: Promise.resolve() };
  if (typeof load === "string") clip.url = load;
  else {
    clip.ready = load.then(
      (url) => { if (born !== generation) { URL.revokeObjectURL(url); clip.dead = true; } else clip.url = url; },
      () => { clip.dead = true; },
    );
  }
  queue.push(clip);
  void playNext();
}

async function playNext(): Promise<void> {
  if (current || advancing) return;
  advancing = true;
  try {
    while (queue.length && !current) {
      const clip = queue[0];
      await clip.ready;
      if (queue[0] !== clip) continue;                   // stopped while it loaded
      queue.shift();
      if (clip.dead || !clip.url) continue;
      play(clip);
    }
  } finally {
    advancing = false;
  }
}

function play(clip: Clip): void {
  const url = clip.url!;
  const audio = new Audio(url);
  current = audio;
  currentUrl = url;
  notify(clip.label);
  // While this plays, these words are Nyx's own: the microphone will hear them
  // and the echo guard has to know not to treat them as something the owner said.
  let endWindow = registerSpoken(clip.spoken ?? clip.label);
  audio.onloadedmetadata = () => {
    if (Number.isFinite(audio.duration) && audio.duration > 0) {
      endWindow = registerSpoken(clip.spoken ?? clip.label, audio.duration * 1000);
    }
  };
  let finished = false;
  const done = () => {
    if (finished) return;
    finished = true;
    endWindow();
    URL.revokeObjectURL(url);
    if (current === audio) { current = null; currentUrl = ""; }
    // No "quiet" flicker between sentences: the next clip says "speaking" again straight away.
    if (!queue.length) notify(null);
    void playNext();
  };
  audio.onended = done;
  audio.onerror = done;
  audio.play().then(() => tap(audio), done);             // autoplay blocked until the user interacts with the page
}

export function stopSpeaking(): void {
  generation += 1;
  queue.splice(0).forEach((clip) => { clip.dead = true; if (clip.url) URL.revokeObjectURL(clip.url); });
  if (current) {
    current.pause();
    URL.revokeObjectURL(currentUrl);
    current = null;
    currentUrl = "";
  }
  notify(null);
}

/** Speak `text` in this window only, in a role's voice or an exact voice id. Resolves once the audio is fetched
 * and queued (clips keep the order they were asked in); rejects when the engine could not make it. */
export async function speakText(text: string, options: { role?: string; voice?: string; rate?: string } = {}): Promise<void> {
  const load = fetchAudio("/api/voice/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, role: options.role ?? "reply", voice: options.voice ?? "", rate: options.rate ?? "+0%", session: "voice" }),
  });
  enqueue(load, text.slice(0, 80), text);
  await load;
}

/** Run `play` in exactly one window for this `voice.say` id. */
async function claim(sayId: string, play: () => Promise<void>): Promise<void> {
  const locks = (navigator as Navigator & { locks?: LockManager }).locks;
  const mark = `nyx.voice.played.${sayId}`;
  const decide = async () => {
    try {
      if (localStorage.getItem(mark)) return; // another window took it
      localStorage.setItem(mark, "1");
      window.setTimeout(() => { try { localStorage.removeItem(mark); } catch { /* ignore */ } }, 120_000);
    } catch { /* storage blocked: just play */ }
    await play();
  };
  if (document.hidden) await new Promise((resolve) => window.setTimeout(resolve, 350)); // visible windows go first
  if (!locks) { await decide(); return; }
  await locks.request("nyx-voice-claim", async () => { await decide(); });
}

/** Start listening for `voice.say`. Safe to call more than once. */
export function startVoicePlayer(): void {
  if (started) return;
  started = true;
  onWorkspaceEvent((event) => {
    const e = event as { type: string; audio_url?: string; text?: string; say_id?: string };
    if (e.type !== "voice.say" || !e.audio_url) return;
    const audioUrl = e.audio_url;
    // Fetch before claiming so the lock is only held for a moment.
    void fetchAudio(audioUrl).then(
      (url) => claim(e.say_id ?? audioUrl, async () => {
        enqueue(url, e.text ?? "");
      }).finally(() => {
        if (!queue.some((clip) => clip.url === url) && currentUrl !== url) URL.revokeObjectURL(url);
      }),
      () => { /* audio expired or engine restarting */ },
    );
  });
}
