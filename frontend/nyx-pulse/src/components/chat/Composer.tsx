/** The composer: what you type, what you attach, and the two buttons that matter.
 *
 * Attachments upload immediately on pick (progress per chip, thumbnail for
 * images) so pressing Send is never the moment a 50 MB file starts moving.
 * Typing `@` offers the team's agents; Enter sends, Shift+Enter is a newline,
 * and while a turn runs the primary button becomes Stop.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import type { BusyMode, ComposerProps, PendingAttachment } from "./types";
import { Icon } from "./Icon";
import { SlashMenu, useSlashRows, commandsIn } from "./SlashMenu";
import { usePasteFiles } from "../../files/fileIntake";
import { ComposerLinks } from "./ComposerLinks";

const BUSY_LABELS: Record<BusyMode, { short: string; long: string }> = {
  queue: { short: "Queue", long: "Queue — send when this answer finishes" },
  interrupt: { short: "Interrupt", long: "Interrupt — stop this answer and send now" },
  parallel: { short: "Run alongside", long: "Run alongside — another AI answers at the same time" },
  branch: { short: "Branch", long: "Branch — a new branch chat with this, current one keeps going" },
};

type Recognition = {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onend: (() => void) | null; onerror: (() => void) | null;
  start: () => void; stop: () => void;
};

function speechRecognition(): (new () => Recognition) | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** Predictive text from Nyx Core's word model (Settings → Predictions can turn it off). */
function usePredictions(value: string, enabled: boolean): string[] {
  const [suggestions, setSuggestions] = useState<string[]>([]);
  useEffect(() => {
    if (!enabled || !value.trim() || value.length > 400) { setSuggestions([]); return; }
    let alive = true;
    const timer = window.setTimeout(async () => {
      const result = await api.get<{ suggestions: string[] }>(`/api/core/complete?prefix=${encodeURIComponent(value.slice(-120))}`);
      if (alive && result.ok) setSuggestions(result.data.suggestions.slice(0, 3));
    }, 220);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [value, enabled]);
  return suggestions;
}

function predictionsEnabled(): boolean {
  try { return localStorage.getItem("nyx.predict.text") !== "0"; } catch { return true; }
}

function AttachmentChip({
  attachment,
  onRemove,
}: {
  attachment: PendingAttachment;
  onRemove: () => void;
}) {
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11,
        padding: "3px 8px", borderRadius: 999, boxShadow: "inset 0 0 0 1px var(--color-divider)",
        maxWidth: 220,
      }}
      title={attachment.error || attachment.name}
    >
      {attachment.mime.startsWith("image/") && attachment.previewUrl ? (
        <img src={attachment.previewUrl} alt="" width={16} height={16} style={{ borderRadius: 3, objectFit: "cover" }} />
      ) : (
        <Icon name="file" size={12} />
      )}
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{attachment.name}</span>
      {attachment.status === "uploading" && <span style={{ color: "var(--color-neutral-600)" }}>uploading…</span>}
      {attachment.status === "error" && <span style={{ color: "var(--color-danger)" }}>failed</span>}
      <button
        onClick={onRemove}
        aria-label={`Remove ${attachment.name}`}
        style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-neutral-600)", padding: 0, font: "inherit" }}
      >
        <Icon name="close" size={11} />
      </button>
    </span>
  );
}

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  attachments,
  onAttachFiles,
  onRemoveAttachment,
  agents,
  placeholder,
  disabled,
  slash,
  onBusySend,
  busyAdvice,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<Recognition | null>(null);
  const baseRef = useRef("");
  const Speech = speechRecognition();
  const [slashCursor, setSlashCursor] = useState(0);
  const [slashDismissed, setSlashDismissed] = useState(false);
  const [caret, setCaret] = useState(value.length);
  const slashMenu = useSlashRows(value, slash, slashDismissed, caret);
  const inlineCommands = slash ? commandsIn(value, slash.commands) : [];
  const slashOpen = slashMenu.rows.length > 0;
  const [busyMenu, setBusyMenu] = useState(false);
  const suggestions = usePredictions(value, predictionsEnabled() && !listening && !value.startsWith("/"));

  // A picture on the clipboard (Ctrl+V, or a Win+Shift+S snip) attaches like a
  // dropped file, so the owner sees which one it is before sending.
  usePasteFiles(textareaRef, (files) => onAttachFiles(files), { enabled: !disabled });

  useEffect(() => { setSlashCursor(0); }, [slashMenu.state.head, slashMenu.rows.length]);
  useEffect(() => { if (!value.startsWith("/") && !slashMenu.inline) setSlashDismissed(false); }, [value, slashMenu.inline]);
  useEffect(() => { setSlashDismissed(false); }, [slashMenu.inline?.start]);
  useEffect(() => { if (!busy || !value.trim()) setBusyMenu(false); }, [busy, value]);

  /** Enter / click on a menu row. Returns true when the key was used by the menu. */
  function chooseSlash(index: number): boolean {
    const row = slashMenu.rows[index];
    if (!row || !slash) return false;
    if (slashMenu.inline && row.type === "command") {
      const { start, end } = slashMenu.inline;
      const insert = `/${row.command.name} `;
      const next = `${value.slice(0, start)}${insert}${value.slice(end).replace(/^\s+/, "")}`;
      onChange(next);
      const at = start + insert.length;
      setCaret(at);
      window.requestAnimationFrame(() => { const el = textareaRef.current; if (el) { el.focus(); el.setSelectionRange(at, at); } });
      return true;
    }
    const { args, hasArgs } = slashMenu.state;
    if (row.type === "command") {
      const command = row.command;
      // An agent opens its boxes straight away ("/coder" pulls up the coder); other commands with arguments complete first.
      if (command.args && !hasArgs && !row.guessed && command.kind !== "agent") {
        onChange(`/${command.name} `);
        textareaRef.current?.focus();
        return true;
      }
      slash.run(command, args);
      return true;
    }
    if (row.type === "make") { slash.create(row.suggestion, args); return true; }
    if (row.type === "skill") { slash.openSkillCreator(row.text); return true; }
    setSlashDismissed(true);
    if (canSend) onSend();
    return true;
  }

  const canSend = !busy && !disabled && (value.trim().length > 0 || attachments.some((a) => a.status === "ready"));

  function acceptSuggestion(word: string) {
    const trimmed = value.replace(/[^\s]*$/, (partial) => (word.startsWith(partial.toLowerCase()) ? "" : partial));
    const joiner = trimmed === "" || /\s$/.test(trimmed) ? "" : " ";
    onChange(`${trimmed}${joiner}${word} `);
    textareaRef.current?.focus();
  }

  function toggleDictation() {
    if (!Speech) return;
    if (listening) { recognitionRef.current?.stop(); return; }
    const recognition = new Speech();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";
    baseRef.current = value ? `${value.replace(/\s*$/, "")} ` : "";
    recognition.onresult = (event) => {
      let finalText = "", interim = "";
      for (let i = 0; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) finalText += result[0].transcript;
        else interim += result[0].transcript;
      }
      onChange(`${baseRef.current}${finalText}${interim}`.replace(/\s+/g, " ").trimStart());
    };
    recognition.onend = () => { setListening(false); recognitionRef.current = null; };
    recognition.onerror = () => { setListening(false); recognitionRef.current = null; };
    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
  }

  useEffect(() => () => recognitionRef.current?.stop(), []);

  function handleChange(next: string) {
    onChange(next);
    // `@` at the start of the draft (or after a space) opens agent mentions.
    const last = next.charAt(next.length - 1);
    setMentionOpen(last === "@");
  }

  function pickAgent(name: string) {
    setMentionOpen(false);
    const withoutDanglingAt = value.replace(/@$/, "");
    onChange(`${withoutDanglingAt}${withoutDanglingAt ? " " : ""}@${name} `);
    textareaRef.current?.focus();
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: "none", position: "relative" }}>
      {slashOpen && (
        <SlashMenu
          rows={slashMenu.rows}
          cursor={slashCursor}
          state={slashMenu.state}
          guessing={slashMenu.guessing}
          guessSource={slashMenu.guessSource}
          onHover={setSlashCursor}
          onChoose={(index) => { chooseSlash(index); }}
          inline={Boolean(slashMenu.inline)}
        />
      )}
      {!slashOpen && inlineCommands.length > 0 && !(inlineCommands.length === 1 && value.startsWith(`/${inlineCommands[0]}`)) && (
        <div className="slash-reads" aria-live="polite">
          Nyx reads {inlineCommands.map((name) => `/${name}`).join(", ")} first
        </div>
      )}
      {mentionOpen && agents.length > 0 && (
        <div
          role="listbox"
          aria-label="Ask an agent"
          style={{
            display: "flex", gap: 6, flexWrap: "wrap", padding: 8,
            borderRadius: "var(--radius)", boxShadow: "inset 0 0 0 1px var(--color-divider)",
            background: "var(--color-nav)",
          }}
        >
          {agents.map((agent) => (
            <button
              key={agent.agentId}
              role="option"
              aria-selected={false}
              className="btn btn-secondary chat-mention"
              onClick={() => pickAgent(agent.name)}
              title={agent.goal || `Ask ${agent.name}`}
            >
              {agent.emoji ? `${agent.emoji} ` : ""}
              {agent.name}
            </button>
          ))}
        </div>
      )}

      {suggestions.length > 0 && !mentionOpen && (
        <div className="composer-predictions" aria-label="Predicted next words (Tab accepts the first)">
          {suggestions.map((word) => (
            <button key={word} className="chip" onClick={() => acceptSuggestion(word)} title="Nyx Core predicted this from how you write">
              {word}
            </button>
          ))}
        </div>
      )}

      {attachments.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {attachments.map((attachment) => (
            <AttachmentChip key={attachment.localId} attachment={attachment} onRemove={() => onRemoveAttachment(attachment.localId)} />
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
        <input
          ref={fileRef}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            onAttachFiles(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
        <button
          className="btn btn-secondary"
          onClick={() => fileRef.current?.click()}
          disabled={busy || disabled}
          title="Attach images or files — Nyx can look at images and read documents"
          style={{ flex: "none", padding: "8px 10px" }}
          aria-label="Attach files"
        >
          <Icon name="file" size={15} />
        </button>

        <div className="composer-box">
        <ComposerLinks value={value} textareaRef={textareaRef} caret={caret} />
        <textarea
          className="composer-input"
          ref={textareaRef}
          data-nyx-paste="composer"
          value={value}
          onChange={(e) => { setCaret(e.target.selectionStart ?? e.target.value.length); handleChange(e.target.value); }}
          onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? value.length)}
          onKeyDown={(e) => {
            if (slashOpen) {
              if (e.key === "ArrowDown") { e.preventDefault(); setSlashCursor((i) => Math.min(slashMenu.rows.length - 1, i + 1)); return; }
              if (e.key === "ArrowUp") { e.preventDefault(); setSlashCursor((i) => Math.max(0, i - 1)); return; }
              if (e.key === "Escape") { e.preventDefault(); setSlashDismissed(true); return; }
              if (e.key === "Tab" && !e.shiftKey) {
                const row = slashMenu.rows[slashCursor];
                if (row?.type === "command" && slashMenu.inline) { e.preventDefault(); chooseSlash(slashCursor); return; }
                if (row?.type === "command") { e.preventDefault(); onChange(`/${row.command.name}${row.command.args ? " " : ""}`); return; }
              }
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (slashMenu.inline) { chooseSlash(slashCursor); return; }
                if (slashMenu.exact && (slashMenu.state.hasArgs || !slashMenu.exact.args)) { slash?.run(slashMenu.exact, slashMenu.state.args); return; }
                chooseSlash(slashCursor);
                return;
              }
            }
            if (busy && e.key === "Enter" && !e.shiftKey && value.trim() && onBusySend) {
              e.preventDefault();
              onBusySend(busyAdvice?.mode ?? "queue");
              return;
            }
            if (e.key === "Tab" && !e.shiftKey && suggestions.length > 0 && value.trim()) {
              e.preventDefault();
              acceptSuggestion(suggestions[0]);
              return;
            }
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSend) onSend();
            }
          }}
          rows={Math.min(6, Math.max(2, value.split("\n").length))}
          placeholder={placeholder ?? "Message Nyx…  (Enter to send, Shift+Enter for a new line)"}
          disabled={disabled}
        />
        </div>

        {Speech && (
          <button
            className={`btn btn-secondary composer-mic${listening ? " is-listening" : ""}`}
            onClick={toggleDictation}
            disabled={busy || disabled}
            aria-pressed={listening}
            aria-label={listening ? "Stop dictation" : "Speak your message"}
            title={listening ? "Listening — click to stop" : "Speak instead of typing"}
            style={{ flex: "none", padding: "8px 10px", alignSelf: "stretch" }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
            </svg>
          </button>
        )}

        {busy && value.trim() && onBusySend && (
          <div className="busy-send">
            <button
              className="btn btn-primary busy-send__main"
              onClick={() => onBusySend(busyAdvice?.mode ?? "queue")}
              title={busyAdvice ? `${BUSY_LABELS[busyAdvice.mode].long}. ${busyAdvice.reason}` : "Deciding…"}
            >
              {BUSY_LABELS[busyAdvice?.mode ?? "queue"].short}
              {busyAdvice?.source === "model" && <span className="busy-send__ai" aria-label="picked by Nyx">✦</span>}
            </button>
            <button
              className="btn btn-primary busy-send__more"
              aria-haspopup="menu"
              aria-expanded={busyMenu}
              aria-label="Other ways to send"
              onClick={() => setBusyMenu((v) => !v)}
            >
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 6.5 5 3.5 8 6.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
            </button>
            {busyMenu && (
              <div className="busy-send__menu" role="menu">
                {busyAdvice && <div className="busy-send__why">Nyx suggests {BUSY_LABELS[busyAdvice.mode].short}: {busyAdvice.reason}</div>}
                {(Object.keys(BUSY_LABELS) as BusyMode[]).map((mode) => (
                  <button key={mode} role="menuitem" className={`busy-send__item${busyAdvice?.mode === mode ? " is-picked" : ""}`}
                    onClick={() => { setBusyMenu(false); onBusySend(mode); }}>
                    {BUSY_LABELS[mode].long}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {busy ? (
          <button
            className="btn btn-secondary"
            onClick={onStop}
            title="Stop this turn — its work so far is kept"
            style={{ alignSelf: "stretch", padding: "0 16px" }}
          >
            Stop
          </button>
        ) : (
          <button
            className="btn btn-primary"
            onClick={() => {
              if (slashOpen && slash && !slashMenu.inline) {
                if (slashMenu.exact && (slashMenu.state.hasArgs || !slashMenu.exact.args)) slash.run(slashMenu.exact, slashMenu.state.args);
                else chooseSlash(slashCursor);
                return;
              }
              onSend();
            }}
            disabled={!canSend}
            style={{ alignSelf: "stretch", padding: "0 18px", opacity: canSend ? 1 : 0.5 }}
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}
