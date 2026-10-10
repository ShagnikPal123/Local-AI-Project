/** Which thought-orb fits what Ichos is doing right now.
 *
 * The orb is not decoration: its shape says the kind of work. A turn's status
 * line or a tool step's label is matched against these verbs, first hit wins,
 * so "Searching the web for…" sweeps a globe, "Running Python" spins orbits,
 * "Asking the team" wires a constellation. Anything unknown just breathes.
 */

import type { OrbState } from "thinking-orbs";

export type { OrbState };

const RULES: Array<[OrbState, RegExp]> = [
  ["listening", /\b(listen|hear|voice|mic|transcri|dictat|speech)/i],
  ["weaving", /\b(court|debate|judge|verdict|rebuttal|merg|combin|swarm|sub-?agents?|several agents|in parallel)/i],
  ["connecting", /\b(connect|connector|agents?\b|team|delegat|hand(ing)? off|email|whatsapp|mcp|api\b|key|provider|account|sync|link)/i],
  ["searching", /\b(search|web|brows|fetch|look(ing)? up|research|find|scan|read(ing)? (the )?(page|site|file|docs?)|absorb|crawl|recall|memory|remember)/i],
  ["shaping", /\b(image|draw|sketch|design|diagram|chart|slide|layout|shape|game|world|office|3d|render|paint)/i],
  ["solving", /\b(solv|math|calculat|comput|reason|plan|analy[sz]|predict|decid|figur|optimi[sz]|check|verif|test)/i],
  ["working", /\b(run|execut|code|python|build|patch|edit|writ(e|ing) (a |the )?file|install|terminal|shell|claude|command|tool|download|deploy|compil)/i],
  ["composing", /\b(writ|draft|compos|answer|reply|respond|summar|translat|explain|stream)/i],
];

/** The orb for a free-text status ("Searching the web…") or tool label. */
export function orbStateFor(text: string | null | undefined, fallback: OrbState = "breathing"): OrbState {
  // Model ids ("ollama:nyx-absorbed:latest is thinking") name who, not what.
  const what = text?.replace(/\S+:\S+/g, " ");
  if (!what?.trim()) return fallback;
  for (const [state, pattern] of RULES) if (pattern.test(what)) return state;
  return fallback;
}

/** What each orb means, in the words the empty chat teaches them with. */
export const ORB_MEANING: Record<OrbState, string> = {
  breathing: "thinking it over",
  searching: "searching the web and memory",
  working: "running code and tools",
  solving: "reasoning through a problem",
  connecting: "calling agents and connectors",
  weaving: "several minds at once",
  composing: "writing the answer",
  shaping: "drawing and designing",
  listening: "listening to you",
};
