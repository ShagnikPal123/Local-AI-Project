/** The "/" command menu that opens above the composer (Request G5).
 *
 * Type "/" and every command is listed; each letter narrows the list. When
 * nothing matches, Nyx guesses what you meant (a quick model call with an
 * offline fallback) and offers to make the command on the spot, or to open the
 * skill creator with your words already filled in.
 *
 * The composer keeps focus the whole time — this is a listbox driven from the
 * textarea's keys (↑ ↓ Tab Enter Esc), like a search field's suggestions.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";

export interface SlashCommand {
  name: string;
  title: string;
  description?: string;
  args?: string;
  kind: "client" | "prompt" | "skill" | "agent";
  action?: string;
  template?: string;
  origin?: string;
  /** kind "agent": the agent this command calls (``/coder [3] …`` opens its boxes). */
  agent?: string;
  emoji?: string;
  made_by?: string;
}

export interface CommandSuggestion {
  name: string;
  title: string;
  description: string;
  template: string;
}

interface GuessResult {
  query: string;
  matches: (SlashCommand & { score: number })[];
  suggestion: CommandSuggestion | null;
  source: "fuzzy" | "model" | "offline";
}

export type SlashRow =
  | { type: "command"; command: SlashCommand; guessed?: boolean }
  | { type: "make"; suggestion: CommandSuggestion }
  | { type: "skill"; text: string }
  | { type: "send" };

export interface SlashHandlers {
  commands: SlashCommand[];
  run: (command: SlashCommand, args: string) => void;
  create: (suggestion: CommandSuggestion, args: string) => void;
  openSkillCreator: (text: string) => void;
}

const SYNONYMS: Record<string, string[]> = {
  image: ["picture", "draw", "img", "photo"], search: ["google", "lookup", "find", "web"], model: ["switch", "change", "provider"],
  duplicate: ["copy", "clone"], rename: ["title", "name"], quiz: ["test", "exam", "questions"], flashcards: ["cards", "memorize"],
  summarize: ["tldr", "summary"], explain: ["teach", "steps"], new: ["start", "blank"], stop: ["cancel", "halt"], newagent: ["subagent", "agent"],
};

/** Prefix beats word-start beats substring beats letters-in-order. 0 means no match. */
export function commandScore(query: string, command: SlashCommand): number {
  const q = query.toLowerCase();
  if (!q) return 1;
  const name = command.name.toLowerCase();
  const title = command.title.toLowerCase();
  if (name === q) return 100;
  if (name.startsWith(q)) return 90 - (name.length - q.length);
  if (title.split(/\s+/).some((w) => w.startsWith(q))) return 70;
  if (name.includes(q) || title.includes(q)) return 55;
  if ((SYNONYMS[name] ?? []).some((s) => s.startsWith(q) || (q.length >= 3 && q.startsWith(s)))) return 50;
  let i = 0;
  for (const ch of name) if (ch === q[i]) i += 1;
  return i === q.length && q.length >= 2 ? 30 : 0;
}

/** Parse the draft: is the menu relevant, what is typed after the slash? */
export function slashState(value: string): { active: boolean; head: string; args: string; hasArgs: boolean } {
  if (!value.startsWith("/") || value.includes("\n")) return { active: false, head: "", args: "", hasArgs: false };
  const body = value.slice(1);
  const match = body.match(/^(\S*)(\s+([\s\S]*))?$/);
  const head = (match?.[1] ?? "").toLowerCase();
  return { active: true, head, args: (match?.[3] ?? "").trim(), hasArgs: Boolean(match?.[2]) };
}

/** A "/word" being typed after the start of the message, at the caret (Request H13). */
export function inlineSlash(value: string, caret: number): { active: boolean; head: string; start: number; end: number } {
  const before = value.slice(0, Math.max(0, Math.min(caret, value.length)));
  const match = before.match(/(^|\s)\/([a-z0-9-]*)$/i);
  if (!match) return { active: false, head: "", start: 0, end: 0 };
  const start = before.length - match[2].length - 1;
  // A command that starts the message on its own is the classic menu (it can run right away).
  if (start === 0 && !value.slice(before.length).trim()) return { active: false, head: "", start: 0, end: 0 };
  return { active: true, head: match[2].toLowerCase(), start, end: before.length };
}

/** Known commands written anywhere in the draft, the way the server finds them. */
export function commandsIn(value: string, commands: SlashCommand[]): string[] {
  const known = new Set(commands.map((c) => c.name));
  const seen: string[] = [];
  for (const match of value.matchAll(/(?:^|\s)\/([a-z0-9][a-z0-9-]{0,31})(?=$|[\s.,;:!?)])/gi)) {
    const name = match[1].toLowerCase();
    if (known.has(name) && !seen.includes(name)) seen.push(name);
  }
  return seen;
}

export function useSlashRows(value: string, handlers: SlashHandlers | undefined, dismissed: boolean, caret = value.length) {
  const leading = slashState(value);
  const inline = leading.active ? { active: false, head: "", start: 0, end: 0 } : inlineSlash(value, caret);
  const state = inline.active ? { active: true, head: inline.head, args: "", hasArgs: false } : leading;
  const [guess, setGuess] = useState<GuessResult | null>(null);
  const [guessing, setGuessing] = useState(false);

  const exact = handlers?.commands.find((c) => c.name === state.head);
  const filtered = useMemo(() => {
    if (!handlers || !state.active) return [];
    return handlers.commands
      .map((command) => ({ command, s: commandScore(state.head, command) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .map((x) => x.command);
  }, [handlers, state.active, state.head]);

  const needsGuess = Boolean(handlers && leading.active && !dismissed && state.head.length >= 2 && !exact && filtered.length === 0);
  const guessKey = needsGuess ? `${state.head} ${state.args}`.trim() : "";

  useEffect(() => {
    if (!guessKey) { setGuess(null); setGuessing(false); return; }
    let alive = true;
    setGuessing(true);
    const timer = window.setTimeout(async () => {
      const result = await api.post<GuessResult>("/api/commands/guess", { text: guessKey });
      if (!alive) return;
      setGuessing(false);
      setGuess(result.ok ? result.data : { query: guessKey, matches: [], suggestion: null, source: "offline" });
    }, 450);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [guessKey]);

  let rows: SlashRow[] = [];
  if (handlers && inline.active && !dismissed) {
    // Mid-message: the menu only completes the name; everything is sent together with the message.
    rows = filtered.filter((c) => c.kind !== "client").slice(0, 8).map((command) => ({ type: "command", command }));
  } else if (handlers && state.active && !dismissed) {
    if (state.hasArgs && exact) rows = [{ type: "command", command: exact }];
    else if (filtered.length > 0 && !state.hasArgs) rows = filtered.map((command) => ({ type: "command", command }));
    else if (state.head.length > 0) {
      const guessed: SlashRow[] = (guess?.matches ?? []).map((command) => ({ type: "command", command, guessed: true }));
      rows = [
        ...guessed,
        ...(guess?.suggestion ? [{ type: "make", suggestion: guess.suggestion } as SlashRow] : []),
        { type: "skill", text: `${state.head.replace(/-/g, " ")} ${state.args}`.trim() },
        { type: "send" },
      ];
    }
  }
  return { state, rows, exact: inline.active ? undefined : exact, guessing, guessSource: guess?.source, inline: inline.active ? inline : null };
}

export function SlashMenu({ rows, cursor, state, guessing, guessSource, onHover, onChoose, inline }: {
  inline?: boolean;
  rows: SlashRow[];
  cursor: number;
  state: ReturnType<typeof slashState>;
  guessing: boolean;
  guessSource?: string;
  onHover: (index: number) => void;
  onChoose: (index: number) => void;
}) {
  useEffect(() => {
    document.getElementById(`slash-row-${cursor}`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (rows.length === 0) return null;
  const unknown = rows.every((r) => r.type !== "command" || r.guessed);
  return (
    <div className="slash-menu" role="listbox" id="slash-menu" aria-label="Commands">
      <div className="slash-menu__head">
        {inline ? (
          <span>Add a command — it goes with your message, and Nyx reads it first</span>
        ) : unknown ? (
          <span>No command called <b>/{state.head}</b>{guessing ? " — guessing what you meant…" : guessSource === "model" ? " — Nyx's best guesses" : ""}</span>
        ) : (
          <span>Commands</span>
        )}
        <span className="slash-menu__keys">{inline ? "↑↓ move · Tab or Enter insert · Esc close" : "↑↓ move · Tab complete · Enter run · Esc close"}</span>
      </div>
      {rows.map((row, index) => {
        const common = {
          id: `slash-row-${index}`,
          role: "option",
          "aria-selected": index === cursor,
          className: `slash-menu__row${index === cursor ? " is-cursor" : ""}`,
          onMouseEnter: () => onHover(index),
          onMouseDown: (e: React.MouseEvent) => { e.preventDefault(); onChoose(index); },
        } as const;
        if (row.type === "command") {
          const c = row.command;
          return (
            <div key={`c-${c.name}`} {...common}>
              <span className="slash-menu__name">/{c.name}</span>
              <span className="slash-menu__title">{c.title}</span>
              <span className="slash-menu__desc">{row.guessed ? "Did you mean this? " : ""}{c.description}</span>
              {c.args && <span className="slash-menu__args">{c.args}</span>}
              {c.kind === "skill" && <span className="slash-menu__badge">skill</span>}
              {c.kind === "agent" && <span className="slash-menu__badge">{c.made_by === "nyx" ? "agent · made by Nyx" : "agent"}</span>}
              {c.origin === "owner" && <span className="slash-menu__badge">yours</span>}
            </div>
          );
        }
        if (row.type === "make") {
          return (
            <div key="make" {...common}>
              <span className="slash-menu__name">+ /{row.suggestion.name}</span>
              <span className="slash-menu__title">Make this command</span>
              <span className="slash-menu__desc">Sends: “{row.suggestion.template.replace("{args}", state.args || "…")}”</span>
            </div>
          );
        }
        if (row.type === "skill") {
          return (
            <div key="skill" {...common}>
              <span className="slash-menu__name">✦</span>
              <span className="slash-menu__title">Create a skill instead</span>
              <span className="slash-menu__desc">Opens the skill creator with “{row.text}”</span>
            </div>
          );
        }
        return (
          <div key="send" {...common}>
            <span className="slash-menu__name">↵</span>
            <span className="slash-menu__title">Send as a message</span>
            <span className="slash-menu__desc">Nyx reads it as plain text</span>
          </div>
        );
      })}
    </div>
  );
}
