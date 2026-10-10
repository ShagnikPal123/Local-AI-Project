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

type Clip = { url: string; label: string; spoken?: string };

const queue: Clip[] = [];
let current: HTMLAudioElement | null = null;
let currentUrl = "";
let started = false;
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

async function playNext(): Promise<void> {
  if (current || queue.length === 0) return;
  const clip = queue.shift()!;
  const audio = new Audio(clip.url);
  current = audio;
  currentUrl = clip.url;
  notify(clip.label);
  // While this plays, these words are Nyx's own: the microphone will hear them
  // and the echo guard has to know not to treat them as something the owner said.
  let endWindow = registerSpoken(clip.spoken ?? clip.label);
  audio.onloadedmetadata = () => {
    if (Number.isFinite(audio.duration) && audio.duration > 0) {
      endWindow = registerSpoken(clip.spoken ?? clip.label, audio.duration * 1000);
    }
  };
  const done = () => {
    endWindow();
    URL.revokeObjectURL(clip.url);
    if (current === audio) { current = null; currentUrl = ""; }
    notify(null);
    void playNext();
  };
  audio.onended = done;
  audio.onerror = done;
  try {
    await audio.play();
  } catch {
    done(); // autoplay blocked until the user interacts with the page
  }
}

export function stopSpeaking(): void {
  queue.splice(0).forEach((clip) => URL.revokeObjectURL(clip.url));
  if (current) {
    current.pause();
    URL.revokeObjectURL(currentUrl);
    current = null;
  }
  notify(null);
}

/** Speak `text` in this window only, in a role's voice or an exact voice id. */
export async function speakText(text: string, options: { role?: string; voice?: string; rate?: string } = {}): Promise<void> {
  const url = await fetchAudio("/api/voice/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, role: options.role ?? "reply", voice: options.voice ?? "", rate: options.rate ?? "+0%", session: "voice" }),
  });
  queue.push({ url, label: text.slice(0, 80), spoken: text });
  void playNext();
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
        queue.push({ url, label: e.text ?? "" });
        void playNext();
      }).finally(() => {
        if (!queue.some((clip) => clip.url === url) && currentUrl !== url) URL.revokeObjectURL(url);
      }),
      () => { /* audio expired or engine restarting */ },
    );
  });
}
