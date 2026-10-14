/** The Equalize wake phrase: listening for "hey Io" (or whatever the owner chose) while voice is off.
 *
 * The owner (Fixer Upper S2): "You can say a phrase or make a sound which you record to activate it … like a double
 * clap and a phrase like wake up which the AI responds to." The Equalize setup saved a wake phrase, but nothing
 * listened for it. This runs the browser's recognizer only while voice is off and the phrase is set; on hearing it,
 * it stops, and the caller turns voice on (the voice engine then owns the microphone). Words said straight after the
 * phrase ("hey Io, what's the weather") are handed back so they are not lost.
 *
 * The recognizer in Edge and Chrome is an online service: the phrase works only with internet, which the Equalize
 * setup says next to the field.
 */

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

/** Listen for `phrase` until it is heard or `stopWakePhrase` is called. Safe to call again to change the phrase. */
export function startWakePhrase(phrase: string, woke: (rest: string) => void): boolean {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  const Speech = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Speech || !words(phrase).length) return false;
  wanted = phrase;
  onWake = woke;
  if (engine) return true;
  stopped = false;
  failures = 0;
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
      const hit = findWake(heard, wanted);
      if (!hit.found) return;
      const callback = onWake;
      stopWakePhrase();
      callback?.(hit.rest);
    };
    recognition.onerror = (event) => {
      // Blocked, or no speech service here (offline, or the app window): stop instead of retrying forever.
      if (event?.error === "not-allowed") stopWakePhrase();
      else if (event?.error && ["network", "service-not-allowed", "language-not-supported", "audio-capture"].includes(event.error)) {
        failures += 1;
        if (failures >= 3) stopWakePhrase();
      }
    };
    recognition.onend = () => {
      engine = null;
      if (!stopped) window.setTimeout(begin, 400);       // the recognizer ends itself after a quiet spell
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
  const running = engine;
  engine = null;
  try { running?.abort ? running.abort() : running?.stop(); } catch { /* already stopped */ }
}

export function wakePhraseListening(): boolean {
  return !stopped;
}
