/** A question you answer with a click (Project Null N85).
 *
 * The owner asked for questions "the user can click and send to the ai … a list of
 * answers and what each means as well as a box for typing if the user had a
 * different approach". So each answer carries its consequence, not just a label —
 * the point of the card is that you can choose without having to ask what the
 * options mean.
 *
 * The answer goes back as an ordinary message (`nyx:chat-send`), so it is part of
 * the transcript and works the same in every mode. Once answered the card says
 * what was chosen instead of inviting a second, contradictory answer.
 */

import { useState } from "react";

interface Option { label: string; means?: string; recommended?: boolean }
interface Card { question: string; options: Option[]; multi?: boolean; other?: string }

/** One card from a JSON object. Models also send arrays and {questions: […]}; see `parseAll`. */
function parseOne(raw: unknown): Card | null {
  try {
    const data = (raw ?? {}) as Record<string, unknown>;
    const question = String(data.question ?? data.title ?? "").trim();
    const given = (data.options ?? data.answers) as unknown;
    const options: Option[] = Array.isArray(given)
      ? given.slice(0, 6).map((item) => typeof item === "string"
          ? { label: item }
          : { label: String((item as Option).label ?? ""), means: String((item as Option).means ?? ""), recommended: Boolean((item as Option).recommended) })
        .filter((option) => option.label.trim())
      : [];
    if (!question || options.length < 2) return null;
    return { question, options, multi: Boolean(data.multi), other: String(data.other ?? "Something else — tell me your approach") };
  } catch {
    return null;
  }
}

/** Where a bare question (or plan) object starts and ends in an answer.
 *
 * Small models write the JSON correctly and then forget the code fence, which
 * left the owner reading `{"question": …}` in the chat. Rather than nag the
 * model, find the object and render it: scan from the opening brace, balancing
 * braces and ignoring anything inside strings.
 */
export function findCardJson(text: string, kind: "question" | "plan"): { start: number; end: number }[] {
  const opener = kind === "question" ? /[[{]\s*"(?:question|questions)"\s*:/g : /\{\s*"(?:goal|spec)"\s*:/g;
  const found: { start: number; end: number }[] = [];
  let match: RegExpExecArray | null;
  while ((match = opener.exec(text))) {
    const start = match.index;
    let depth = 0, inString = false, escaped = false, end = -1;
    for (let i = start; i < text.length; i++) {
      const char = text[i];
      if (escaped) { escaped = false; continue; }
      if (char === "\\") { escaped = true; continue; }
      if (char === '"') { inString = !inString; continue; }
      if (inString) continue;
      if (char === "{" || char === "[") depth++;
      else if (char === "}" || char === "]") {
        depth--;
        if (depth === 0) { end = i + 1; break; }
      }
    }
    if (end === -1) continue;
    const slice = text.slice(start, end);
    const usable = kind === "question" ? parseAll(slice).length > 0 : isPlanJson(slice);
    if (usable) {
      found.push({ start, end });
      opener.lastIndex = end;
    }
  }
  return found;
}

function isPlanJson(source: string): boolean {
  try {
    const data = JSON.parse(source) as Record<string, unknown>;
    return Boolean(data && typeof data === "object" && (Array.isArray(data.spec) || Array.isArray(data.steps)));
  } catch {
    return false;
  }
}

/** Every card in one block: an object, an array of them, or {questions: […]}. */
function parseAll(source: string): Card[] {
  let data: unknown;
  try {
    data = JSON.parse(source);
  } catch {
    return [];
  }
  const list = Array.isArray(data)
    ? data
    : Array.isArray((data as { questions?: unknown }).questions)
      ? (data as { questions: unknown[] }).questions
      : [data];
  return list.slice(0, 4).map(parseOne).filter((card): card is Card => card !== null);
}

function send(text: string): void {
  window.dispatchEvent(new CustomEvent("nyx:chat-send", { detail: { text } }));
}

export function QuestionCard({ source }: { source: string }) {
  const cards = parseAll(source);
  if (cards.length === 0) return null;
  return <>{cards.map((card, index) => <OneQuestion key={index} card={card} />)}</>;
}

function OneQuestion({ card }: { card: Card }) {
  const [picked, setPicked] = useState<string[]>([]);
  const [other, setOther] = useState("");
  const [answered, setAnswered] = useState<string | null>(null);

  if (!card) return null;

  const toggle = (label: string) => {
    if (answered) return;
    if (!card.multi) { answer([label], ""); return; }
    setPicked((current) => current.includes(label) ? current.filter((l) => l !== label) : [...current, label]);
  };

  function answer(labels: string[], typed: string) {
    if (!card) return;
    const lines = [`**${card.question}**`];
    const meanings = new Map(card.options.map((o) => [o.label, o.means ?? ""]));
    for (const label of labels) {
      const means = meanings.get(label);
      lines.push(`→ ${label}${means ? ` (${means})` : ""}`);
    }
    if (typed.trim()) lines.push(`→ My own approach: ${typed.trim()}`);
    const text = lines.join("\n");
    setAnswered(labels.length ? labels.join(", ") + (typed.trim() ? " + my own" : "") : "my own approach");
    send(text);
  }

  return (
    <section className={`q-card${answered ? " is-answered" : ""}`} aria-label="A question for you">
      <p className="q-card__q">{card.question}</p>
      <div className="q-card__options">
        {card.options.map((option) => {
          const chosen = picked.includes(option.label);
          return (
            <button
              key={option.label}
              type="button"
              className={`q-card__option${chosen ? " is-chosen" : ""}${option.recommended ? " is-first" : ""}`}
              aria-pressed={card.multi ? chosen : undefined}
              disabled={Boolean(answered)}
              onClick={() => toggle(option.label)}
            >
              <b>{option.label}{option.recommended && <span className="q-card__tag">would pick</span>}</b>
              {option.means && <span>{option.means}</span>}
            </button>
          );
        })}
      </div>
      {!answered && (
        <form
          className="q-card__other"
          onSubmit={(event) => { event.preventDefault(); if (other.trim() || picked.length) answer(picked, other); }}
        >
          <input
            value={other}
            onChange={(event) => setOther(event.target.value)}
            placeholder={card.other}
            aria-label="Your own approach"
          />
          <button type="submit" className="nyx-btn nyx-btn--sm" disabled={!other.trim() && picked.length === 0}>
            {card.multi && picked.length ? `Send ${picked.length} chosen` : "Send"}
          </button>
        </form>
      )}
      {answered && <p className="q-card__answered">You answered: {answered}</p>}
    </section>
  );
}
