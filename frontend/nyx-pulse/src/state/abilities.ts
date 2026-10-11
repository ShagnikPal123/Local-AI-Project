/** Abilities: the things a chat can use, picked from the composer and shown as rounded boxes (owner, 2026-10-10:
 * "for the + I would rather a divide, 1 for files and similar things, the other for skills/agent calls with the
 * ability for the other tabs you have now … I would like it in the same as a box rounded edges so the user knows they
 * have added what that can do, they can click on it to add as a tab like normal"; "remove build and add to the + as
 * the AI can use it as a box and the user can double click to open").
 *
 * Two kinds of box sit above the message box:
 *  - picked: the owner added an ability; the next message tells Ichos it may use it;
 *  - offered: Ichos made something (a graph, a court case, a game) — instead of a pane jumping open on the right, it
 *    arrives as a box. Double-click any box to open it full size.
 */

export interface Ability {
  id: string;
  label: string;
  glyph: string;
  hint: string;
  /** What Ichos is told it may use. */
  use: string;
  open: { tab: string } | { window: string };
}

export const ABILITIES: Ability[] = [
  { id: "build", label: "Build", glyph: "◇", hint: "3D build studio", use: "the Build studio (3D parts and assemblies)", open: { window: "build" } },
  { id: "game", label: "Game Studio", glyph: "◆", hint: "Make or play a game", use: "Game Studio (ui_open_window kind game)", open: { window: "game" } },
  { id: "graph", label: "Graph", glyph: "∿", hint: "Plot, derive, solve", use: "plot_function and math_symbolic for graphs and exact maths", open: { window: "graph" } },
  { id: "notes", label: "Notes", glyph: "✎", hint: "Your notes", use: "the owner's notes (read and write notes)", open: { window: "notes" } },
  { id: "quiz", label: "Quiz", glyph: "?", hint: "Quiz or flashcards on a topic", use: "make_quiz to build a quiz or flashcards that open as a bar on the right", open: { window: "quiz" } },
  { id: "court", label: "Court", glyph: "⚖", hint: "Bots argue it before judges", use: "court_case to put the question on trial", open: { window: "court" } },
  { id: "predict", label: "Predict", glyph: "◎", hint: "A swarm forecasts it", use: "predict to run a swarm forecast", open: { tab: "predict" } },
  { id: "office", label: "Office & World", glyph: "▦", hint: "Teams of agents", use: "office_create / world_create for a team of agents", open: { window: "office" } },
  { id: "s2c", label: "Screenshot → Code", glyph: "⌘", hint: "Turn a UI image into a page", use: "screenshot_to_code for the attached UI image", open: { window: "s2c" } },
  { id: "brain", label: "Second Brain", glyph: "◐", hint: "Everything Ichos remembers", use: "brain_recall over the owner's memories", open: { window: "brain" } },
  { id: "computer", label: "Ichos Computer", glyph: "▭", hint: "Its own sandboxed desktop", use: "Ichos's own computer", open: { window: "computer" } },
  { id: "mail", label: "Mail", glyph: "✉", hint: "Your inbox", use: "email tools (read, search, draft)", open: { window: "email" } },
  { id: "texts", label: "Texts", glyph: "✆", hint: "WhatsApp with your phone", use: "WhatsApp messaging", open: { window: "whatsapp" } },
];

export interface Box { key: string; label: string; glyph: string; kind: "picked" | "offered"; ability?: string;
  window?: string; tab?: string; title?: string; props?: Record<string, unknown> }

let boxes: Box[] = [];
const listeners = new Set<(b: Box[]) => void>();
const emit = () => listeners.forEach((l) => l(boxes));

export function onBoxes(listener: (b: Box[]) => void): () => void {
  listeners.add(listener);
  listener(boxes);
  return () => listeners.delete(listener);
}

export function pickAbility(id: string): void {
  const a = ABILITIES.find((x) => x.id === id);
  if (!a || boxes.some((b) => b.ability === id && b.kind === "picked")) return;
  boxes = [...boxes, { key: `p-${id}`, label: a.label, glyph: a.glyph, kind: "picked", ability: id,
    ...("tab" in a.open ? { tab: a.open.tab } : { window: a.open.window }) }];
  emit();
}

/** Something Ichos made, offered as a box (replaces opening a pane on the right). */
export function offerWindow(window: string, title?: string, props?: Record<string, unknown>): void {
  const a = ABILITIES.find((x) => "window" in x.open && x.open.window === window);
  boxes = [...boxes.filter((b) => !(b.kind === "offered" && b.window === window && !props)),
    { key: `o-${window}-${Date.now()}`, label: title || a?.label || window, glyph: a?.glyph ?? "▣", kind: "offered" as const, window, title, props }]
    .slice(-8);
  emit();
}

export function removeBox(key: string): void {
  boxes = boxes.filter((b) => b.key !== key);
  emit();
}

/** Open a box full size: a tab, or a window that fills the chat (no side pane). */
export function openBox(box: Box): void {
  if (box.tab) {
    window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: box.tab } }));
    return;
  }
  window.dispatchEvent(new CustomEvent("ichos:open-window", { detail: { kind: box.window, title: box.title, props: box.props, dock: "full" } }));
}

/** The line added to the next message for the abilities the owner picked; picked boxes clear after sending. */
export function takeAbilitiesNote(): string {
  const picked = boxes.filter((b) => b.kind === "picked");
  if (!picked.length) return "";
  const uses = picked.map((b) => ABILITIES.find((a) => a.id === b.ability)?.use).filter(Boolean);
  boxes = boxes.filter((b) => b.kind !== "picked");
  emit();
  return `\n\n[The owner added these abilities for this message — use them if they help: ${uses.join("; ")}.]`;
}
