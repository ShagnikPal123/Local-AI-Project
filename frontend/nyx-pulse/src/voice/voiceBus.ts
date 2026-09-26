/** One place that knows whether Nyx is listening, and what it heard.
 *
 * The voice engine (`voiceEngine.ts`) is the only writer. Everything else —
 * the chat bar, the Proto Voice dock, the hands-off bar on the desktop, the
 * clap detector — reads from here, so there is one microphone and one truth
 * about the mode instead of a listener per feature.
 *
 * The mode is remembered between sessions:
 *   off   — nothing is listening.
 *   talk  — active talk in the chat: speak, and the answer comes back spoken.
 *   proto — Proto Voice: always listening, and allowed to act on the computer.
 */

export type VoiceMode = "off" | "talk" | "proto";

export type VoiceEvent =
  /** Listening started or stopped. */
  | { type: "start"; mode: VoiceMode }
  | { type: "stop"; mode: VoiceMode }
  /** Words as they are being said, then the finished sentence. Same utteranceId. */
  | { type: "partial"; text: string; utteranceId: string }
  | { type: "final"; text: string; utteranceId: string }
  /** What Nyx is saying out loud right now, or null when it goes quiet. */
  | { type: "speaking"; text: string | null }
  /** Proto Voice standby: it only wakes on its name (or a clap) while `on`. */
  | { type: "away"; on: boolean }
  /** The owner started talking over Nyx. */
  | { type: "bargein" }
  | { type: "error"; message: string };

const MODE_KEY = "nyx.voice.mode";
const LEGACY_TALK_KEY = "nyx.voice.activetalk";

const listeners = new Set<(event: VoiceEvent) => void>();
const modeListeners = new Set<(mode: VoiceMode) => void>();

let mode: VoiceMode = readMode();
let speakingText: string | null = null;

function readMode(): VoiceMode {
  try {
    const stored = localStorage.getItem(MODE_KEY);
    if (stored === "talk" || stored === "proto" || stored === "off") return stored;
    // Before Project Null the only switch was active talk.
    return localStorage.getItem(LEGACY_TALK_KEY) === "1" ? "talk" : "off";
  } catch {
    return "off";
  }
}

/** Listen to everything the voice engine reports. Returns the unsubscribe. */
export function onVoice(listener: (event: VoiceEvent) => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** The voice engine calls this; nothing else should. */
export function emitVoice(event: VoiceEvent): void {
  if (event.type === "speaking") speakingText = event.text;
  listeners.forEach((listener) => {
    try { listener(event); } catch { /* one bad listener must not stop the others */ }
  });
}

export function voiceMode(): VoiceMode {
  return mode;
}

/** Turn listening on or off. Any window, any tab, the desktop bar's Stop button. */
export function setVoiceMode(next: VoiceMode): void {
  if (next === mode) return;
  const previous = mode;
  mode = next;
  try {
    localStorage.setItem(MODE_KEY, next);
    localStorage.setItem(LEGACY_TALK_KEY, next === "talk" ? "1" : "0");
  } catch { /* not remembered, still works for this session */ }
  modeListeners.forEach((listener) => {
    try { listener(next); } catch { /* ignore */ }
  });
  emitVoice(next === "off" ? { type: "stop", mode: previous } : { type: "start", mode: next });
}

export function onVoiceMode(listener: (mode: VoiceMode) => void): () => void {
  modeListeners.add(listener);
  return () => { modeListeners.delete(listener); };
}

/** What Nyx is saying out loud, or null. */
export function speaking(): string | null {
  return speakingText;
}
