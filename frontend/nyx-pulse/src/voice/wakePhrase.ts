/** The Equalize wake phrase: listening for "hey Io" (or whatever the owner chose) while voice is off.
 *
 * The owner (Fixer Upper S2): "You can say a phrase or make a sound which you record to activate it … like a double
 * clap and a phrase like wake up which the AI responds to." The Equalize setup saved a wake phrase, but nothing
 * listened for it. This runs the browser's recognizer only while voice is off and the phrase is set; on hearing it,
 * it stops, and the caller turns voice on (the voice engine then owns the microphone). Words said straight after the
 * phrase ("hey Io, what's the weather") are handed back so they are not lost.
 *
 * The recognizer in Edge and Chrome is an online service, and Nyx's own app window (WebView2) has none at all. There,
 * offline, or once the recognizer keeps failing, the phrase is heard on this PC instead (`localEar`: one short
 * sentence per pause, turned into words by Whisper or Windows dictation), so the phrase works in the app window too.
 */

import { localEarEngine, startLocalEar, stopLocalEar } from "./localEar";
import { startVad, vadRunning } from "./micVad";
import { onVoiceMode } from "./voiceBus";

/** A wake sentence is short; longer speech in the room is not sent to the PC to transcribe. */
const WAKE_LONGEST_MS = 6000;
/** A pause this long ends a wake sentence. */
const WAKE_PAUSE_MS = 700;
/** How often the local ear checks that its microphone is still open (voice turning off closes the shared one). */
const WATCH_MS = 2000;

type Recognition = {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onend: (() => void) | null; onerror: ((e: { error?: string }) => void) | null;
  start: () => void; stop: () => void; abort?: () => void;
};

function words(text: string): string[] {
  return (text || "").toLowerCase().replace(/[’]/g, "'").match(/[a-z0-9']+/g) ?? [];
}

/** Whether the phrase is in what was heard, and the words after it. Tolerates one misheard word in phrases of three words or more. */
export function findWake(heard: string, phrase: string): { found: boolean; rest: string } {
  const said = words(heard);
  const wanted = words(phrase);
  if (!wanted.length || said.length < wanted.length) return { found: false, rest: "" };
  const allowedMisses = wanted.length >= 3 ? 1 : 0;
  for (let start = 0; start + wanted.length <= said.length; start += 1) {
    let misses = 0;
    for (let i = 0; i < wanted.length && misses <= allowedMisses; i += 1) {
      if (said[start + i] !== wanted[i]) misses += 1;
    }
    if (misses <= allowedMisses) {
      return { found: true, rest: said.slice(start + wanted.length).join(" ") };
    }
  }
  return { found: false, rest: "" };
}

let engine: Recognition | null = null;
let wanted = "";
let onWake: ((rest: string) => void) | null = null;
let stopped = true;
let failures = 0;
let local = false;
let watch = 0;

function inAppWindow(): boolean {
  return Boolean((window as unknown as { chrome?: { webview?: unknown } }).chrome?.webview)
    || Boolean((window as unknown as { pywebview?: unknown }).pywebview);
}

/** What was heard, from either ear: on the phrase, stop and hand the words after it to the caller. */
function heardWords(heard: string): void {
  const hit = findWake(heard, wanted);
  if (!hit.found) return;
  const callback = onWake;
  stopWakePhrase();
  callback?.(hit.rest);
}

// The local ear is one per page: the moment voice turns on, the voice engine needs it, so the wake ear lets go first
// (mode listeners run before the engine's effect opens its own).
onVoiceMode((mode) => { if (mode !== "off" && local) stopWakePhrase(); });

/** Listen for the phrase on this PC. Returns false when nothing here can transcribe. */
async function listenLocally(): Promise<boolean> {
  if (local) return true;
  local = true;
  const [micOpen, engineName] = await Promise.all([startVad(), localEarEngine()]);
  if (stopped) { local = false; return false; }
  if (!micOpen || !engineName) { stopWakePhrase(); return false; }
  const open = () => startLocalEar({ heard: (text) => { if (text) heardWords(text); } }, () => WAKE_PAUSE_MS, WAKE_LONGEST_MS);
  if (!open()) { stopWakePhrase(); return false; }
  watch = window.setInterval(() => {
    if (stopped || vadRunning()) return;
    stopLocalEar();
    void startVad().then((ok) => { if (ok && !stopped) open(); });
  }, WATCH_MS);
  return true;
}

/** Listen for `phrase` until it is heard or `stopWakePhrase` is called. Safe to call again to change the phrase. */
export function startWakePhrase(phrase: string, woke: (rest: string) => void): boolean {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  const Speech = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!words(phrase).length) return false;
  wanted = phrase;
  onWake = woke;
  if (engine || local) return true;
  stopped = false;
  failures = 0;
  if (!Speech || inAppWindow() || !navigator.onLine) { void listenLocally(); return true; }
  const begin = () => {
    if (stopped) return;
    const recognition = new Speech();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";
    recognition.onresult = (event) => {
      let heard = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) heard += event.results[i][0].transcript;
      failures = 0;
      heardWords(heard);
    };
    recognition.onerror = (event) => {
      // Blocked: stop. No speech service here (offline, or a window without one): listen on this PC instead.
      if (event?.error === "not-allowed") stopWakePhrase();
      else if (event?.error && ["network", "service-not-allowed", "language-not-supported", "audio-capture"].includes(event.error)) {
        failures += 1;
        if (failures >= 3) {
          const broken = engine;
          engine = null;
          try { broken?.abort ? broken.abort() : broken?.stop(); } catch { /* already stopped */ }
          void listenLocally();
        }
      }
    };
    recognition.onend = () => {
      if (engine === recognition) engine = null;
      if (!stopped && !local) window.setTimeout(begin, 400);   // the recognizer ends itself after a quiet spell
    };
    engine = recognition;
    try { recognition.start(); } catch { /* already running */ }
  };
  begin();
  return true;
}

export function stopWakePhrase(): void {
  stopped = true;
  onWake = null;
  if (local) {
    local = false;
    window.clearInterval(watch);
    watch = 0;
    stopLocalEar();                                       // the voice engine opens its own ear when it starts
  }
  const running = engine;
  engine = null;
  try { running?.abort ? running.abort() : running?.stop(); } catch { /* already stopped */ }
}

export function wakePhraseListening(): boolean {
  return !stopped;
}
