/** Thinking words and new-chat greetings, like Claude's (Drive doc 1, item 1.15, image 01-b).
 *
 * One list so the chat, the notch and the assistant can all say the same things. Picks are seeded (by turn or chat
 * id) so a phrase doesn't jump around on every re-render, and only change on the timer that asks them to.
 */

/** One-word "it's thinking" lines: kitchen verbs, plain thinking verbs and a few pop-culture ones. */
export const THINKING_PHRASES = [
  "Baking", "Leavening", "Simmering", "Marinating", "Percolating", "Brewing", "Whisking", "Kneading",
  "Pondering", "Mulling", "Noodling", "Cogitating", "Ruminating", "Musing", "Scheming", "Tinkering",
  "Conjuring", "Wrangling", "Untangling", "Distilling", "Synthesizing", "Crystallizing", "Herding thoughts",
  "Consulting the Force", "Engaging warp drive", "Reticulating splines", "Charging the flux capacitor",
  "Asking the Oracle", "Entering the Matrix", "Rolling for insight", "Loading the next level",
];

/** Greetings for an empty chat. ``{name}`` lines are used only when the owner's name is known. */
export const GREETINGS = [
  "Let's cook", "What's up", "What are we building?", "Ready when you are", "What's on your mind?",
  "Let's make something", "Where do we start?", "Hit me with it",
  "Let's cook, {name}", "What's up, {name}?", "Good to see you, {name}", "What are we building today, {name}?",
];

const NAME_KEY = "nyx.ownerName";

function hash(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** A thinking phrase for ``seed``; ``tick`` moves to the next one (the status line bumps it every few seconds). */
export function thinkingPhrase(seed: string, tick = 0): string {
  return THINKING_PHRASES[(hash(seed) + tick) % THINKING_PHRASES.length];
}

/** Status lines that say nothing ("Thinking", "Working…"), which a thinking phrase replaces. */
export function isGenericStatus(status?: string | null): boolean {
  const s = (status || "").trim().replace(/[.…]+$/, "").toLowerCase();
  return s === "" || s === "thinking" || s === "working" || s === "starting";
}

export function ownerName(): string {
  try { return (localStorage.getItem(NAME_KEY) || "").trim().slice(0, 40); } catch { return ""; }
}

export function setOwnerName(name: string): void {
  try { localStorage.setItem(NAME_KEY, name.trim().slice(0, 40)); } catch { /* private window: just not kept */ }
}

/** A greeting for ``seed`` (the chat id), with the owner's name when there is one. */
export function greeting(seed: string, name = ownerName()): string {
  const usable = GREETINGS.filter((g) => name || !g.includes("{name}"));
  return usable[hash(seed) % usable.length].replace("{name}", name);
}
