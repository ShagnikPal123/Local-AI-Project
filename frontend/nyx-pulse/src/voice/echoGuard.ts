/** Keeps Nyx from answering itself.
 *
 * The owner: "As it talks it also listens. Make sure it doesn't pick up its own
 * voice." The microphone stays open while Nyx speaks, so the speaker's output
 * comes back through it. Two defences, because neither alone is enough:
 *
 *  1. Words. Everything Nyx says is registered here while it plays, plus a
 *     grace period after it ends (the recognizer reports late). Heard text that
 *     mostly repeats words Nyx just said is thrown away.
 *  2. Sound. `micVad` runs on an echo-cancelled microphone stream, where the
 *     browser has already subtracted what it is playing. If that stream is
 *     quiet, whatever the recognizer produced was the speaker, not a person.
 *
 * `isEcho` is deliberately strict about short phrases: "yes" or "stop" said by
 * a person must get through even while Nyx is mid-sentence, so single-word
 * matches only count as echo when they were part of a longer line just spoken.
 */

/** How long after a clip ends its words still count as echo. */
const TAIL_MS = 1400;
/** Speaking rate used to guess how long a clip lasts when the audio doesn't say. */
const MS_PER_WORD = 380;

type Spoken = { words: Set<string>; phrase: string; until: number };

const spoken: Spoken[] = [];

function tokens(text: string): string[] {
  return (text || "").toLowerCase().match(/[a-z0-9']+/g) ?? [];
}

function sweep(now: number): void {
  for (let i = spoken.length - 1; i >= 0; i -= 1) {
    if (spoken[i].until < now) spoken.splice(i, 1);
  }
}

/**
 * Register a line Nyx is about to say. `durationMs` comes from the audio
 * element when it is known; otherwise it is guessed from the word count.
 * Returns a function that extends the window when playback really ends.
 */
export function registerSpoken(text: string, durationMs?: number): () => void {
  const words = tokens(text);
  if (!words.length) return () => undefined;
  const now = Date.now();
  sweep(now);
  const length = durationMs && durationMs > 0 ? durationMs : words.length * MS_PER_WORD;
  const entry: Spoken = { words: new Set(words), phrase: words.join(" "), until: now + length + TAIL_MS };
  spoken.push(entry);
  return () => { entry.until = Date.now() + TAIL_MS; };
}

/** True when `heard` looks like Nyx's own voice coming back. */
export function isEcho(heard: string): boolean {
  const now = Date.now();
  sweep(now);
  if (!spoken.length) return false;
  const words = tokens(heard);
  if (!words.length) return false;
  const phrase = words.join(" ");
  for (const entry of spoken) {
    // A fragment of a line Nyx just said — the usual case for a clean echo.
    if (entry.phrase.includes(phrase)) return true;
    const shared = words.filter((word) => entry.words.has(word)).length;
    const ratio = shared / words.length;
    if (words.length >= 4 && ratio >= 0.6) return true;
    if (words.length >= 2 && ratio === 1 && entry.words.size > words.length) return true;
  }
  return false;
}

/** Nothing Nyx said is still in the air. */
export function quiet(): boolean {
  sweep(Date.now());
  return spoken.length === 0;
}

/** Forget everything (used when speech is stopped part-way). */
export function clearSpoken(): void {
  spoken.splice(0);
}
