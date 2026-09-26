/** The context bar: how much room the answering model has left in this chat, and Compact (Request Q, 2026-09-17).
 *
 * Owner: "Add a context bar and compact context skill."
 *
 * Designed with the apple-design skill:
 *   • gauges.md › Best practices — a succinct label with the current value and both ends of the range
 *     ("38% · 24k of 128k tokens"); gauges.md › Desktop — a continuous capacity track whose fill changes colour at
 *     significant levels, and the level is also said in words ("Getting full"), never colour alone (accessibility.md).
 *   • feedback.md — status lives quietly in the interface next to what it describes; compaction confirms itself inline,
 *     no alert.
 *   • generative-ai.md › Outputs — say specifically what is happening ("Summarizing 16 earlier messages"), and make the
 *     result easy to revert (Undo).
 * Quiet until it matters: a thin line and a number; the Compact button gains prominence only past 70 %.
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";

interface Measure {
  used: number; window: number; percent: number; messages: number; level: "ok" | "warn" | "full";
  parts: { instructions: number; memory: number; summary: number; conversation: number; tools: number; images: number };
  can_compact: boolean; can_undo: boolean; auto_compact: boolean; threshold: number; keep_last: number; compacted: boolean;
}
interface CompactResult { compacted_messages: number; saved_tokens: number; source: string; after: Measure; before: Measure }

const PART_LABEL: [keyof Measure["parts"], string][] = [
  ["conversation", "Conversation"], ["tools", "Tool results"], ["memory", "Memory & skills"], ["instructions", "Nyx's instructions"],
  ["summary", "Earlier summary"], ["images", "Images"],
];

function k(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

const STATE_TEXT: Record<Measure["level"], string> = { ok: "", warn: "Getting full", full: "Almost full" };

export function ContextBar({ chatId, provider, refreshKey }: { chatId: string; provider: string; refreshKey?: string }) {
  const [measure, setMeasure] = useState<Measure | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [focus, setFocus] = useState("");
  const [note, setNote] = useState<{ text: string; tone: "ok" | "warn" } | null>(null);
  const panelId = useId();
  const noteTimer = useRef<number | undefined>(undefined);

  const load = useCallback(async () => {
    if (!chatId) return;
    const result = await api.get<Measure>(`/api/chats/${encodeURIComponent(chatId)}/context?provider=${encodeURIComponent(provider || "")}`);
    if (result.ok) setMeasure(result.data);
  }, [chatId, provider]);

  useEffect(() => { void load(); }, [load, refreshKey]);
  useEffect(() => onWorkspaceEvent((event) => {
    if (event.type === "context.changed" && (!event.chat_id || event.chat_id === chatId)) void load();
  }), [chatId, load]);

  const say = (text: string, tone: "ok" | "warn" = "ok") => {
    setNote({ text, tone });
    window.clearTimeout(noteTimer.current);
    noteTimer.current = window.setTimeout(() => setNote(null), 12_000);
  };

  const compact = useCallback(async (keepExactly = focus) => {
    if (!measure || busy) return;
    setBusy(true);
    const result = await api.post<CompactResult>(`/api/chats/${encodeURIComponent(chatId)}/compact`,
      { focus: keepExactly, provider, keep_last: measure.keep_last }, 90_000);
    setBusy(false);
    if (!result.ok) { say(result.error, "warn"); return; }
    setMeasure({ ...result.data.after, can_undo: true });
    setFocus("");
    say(`Summarized ${result.data.compacted_messages} earlier messages · ${k(result.data.saved_tokens)} tokens freed${result.data.source === "offline" ? " (offline summary)" : ""}`);
  }, [busy, chatId, focus, measure, provider]);

  // "/compact keep the file paths" in the composer arrives here.
  useEffect(() => {
    const onCompact = (event: Event) => void compact((event as CustomEvent<{ focus?: string }>).detail?.focus ?? "");
    window.addEventListener("nyx:context-compact", onCompact);
    return () => window.removeEventListener("nyx:context-compact", onCompact);
  }, [compact]);

  async function undo() {
    setBusy(true);
    const result = await api.post<{ after: Measure }>(`/api/chats/${encodeURIComponent(chatId)}/compact/undo`, { provider });
    setBusy(false);
    if (!result.ok) { say(result.error, "warn"); return; }
    setMeasure({ ...result.data.after, can_undo: false });
    say("Restored the full conversation.");
  }

  async function saveSettings(changes: Partial<Pick<Measure, "auto_compact" | "threshold" | "keep_last">>) {
    const result = await api.put<{ auto_compact: boolean; threshold: number; keep_last: number }>("/api/context/settings", changes);
    if (result.ok && measure) setMeasure({ ...measure, ...result.data });
  }

  if (!measure || measure.messages === 0) return null;
  const pct = Math.max(0, Math.min(100, measure.percent));
  const valueText = `Context ${Math.round(pct)} percent full, ${k(measure.used)} of ${k(measure.window)} tokens${STATE_TEXT[measure.level] ? `, ${STATE_TEXT[measure.level].toLowerCase()}` : ""}`;
  const prominent = measure.level !== "ok";

  return (
    <div className={`context-bar is-${measure.level}`}>
      <div className="context-bar__row">
        <button type="button" className="context-bar__toggle" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((v) => !v)}
          title="What fills the context, and compaction settings">
          <span className="context-bar__label">Context</span>
          <span className="context-bar__track" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-valuetext={valueText}>
            <span className="context-bar__fill" style={{ width: `${Math.max(pct, 1.5)}%` }} />
            <span className="context-bar__tick" style={{ left: `${measure.threshold}%` }} aria-hidden="true" />
          </span>
          <span className="context-bar__value">
            {Math.round(pct)}% <span className="context-bar__of">· {k(measure.used)} of {k(measure.window)}</span>
            {STATE_TEXT[measure.level] && <b className="context-bar__state"> · {measure.level === "full" ? "▲" : "●"} {STATE_TEXT[measure.level]}</b>}
          </span>
        </button>
        {busy ? (
          <span className="context-bar__busy" role="status"><span className="context-bar__spinner" aria-hidden="true" />
            {measure.can_undo && !measure.can_compact ? "Restoring…" : `Summarizing ${Math.max(0, measure.messages - measure.keep_last)} earlier messages…`}
          </span>
        ) : (
          measure.can_compact && (
            <button type="button" className={`btn ${prominent ? "btn-primary" : "btn-secondary"} context-bar__compact`} onClick={() => void compact()}>
              Compact
            </button>
          )
        )}
      </div>
      {note && (
        <p className={`context-bar__note is-${note.tone}`} role="status">
          {note.text}
          {note.tone === "ok" && measure.can_undo && !busy && <button type="button" className="chat-inline" onClick={() => void undo()}>Undo</button>}
        </p>
      )}
      {open && (
        <div className="context-bar__panel" id={panelId} role="region" aria-label="Context details">
          <ul className="context-bar__parts">
            {PART_LABEL.filter(([key]) => measure.parts[key] > 0).map(([key, label]) => (
              <li key={key}>
                <span className={`context-bar__swatch is-${key}`} aria-hidden="true" />
                <span>{label}</span>
                <span className="context-bar__num">{k(measure.parts[key])}</span>
                <span className="context-bar__share">{Math.round((measure.parts[key] / Math.max(1, measure.used)) * 100)}%</span>
              </li>
            ))}
          </ul>
          <p className="context-bar__hint">
            {measure.messages} messages in the model's copy of this chat. Compacting turns older ones into a short summary and keeps the last
            {" "}{measure.keep_last} word for word — your transcript stays exactly as it is. Token counts are estimates.
          </p>
          <label className="context-bar__field">
            <span>Keep exactly <em>optional</em></span>
            <input value={focus} maxLength={300} placeholder="e.g. the file paths and the budget numbers" onChange={(e) => setFocus(e.target.value)} />
          </label>
          <div className="context-bar__settings">
            <label className="context-bar__check">
              <button type="button" className="switch" role="switch" aria-checked={measure.auto_compact} aria-label="Compact automatically"
                onClick={() => void saveSettings({ auto_compact: !measure.auto_compact })} />
              <span>Compact automatically at</span>
            </label>
            <select value={measure.threshold} aria-label="Automatic compaction threshold" disabled={!measure.auto_compact}
              onChange={(e) => void saveSettings({ threshold: Number(e.target.value) })}>
              {[70, 80, 85, 90, 95].map((v) => <option key={v} value={v}>{v}%</option>)}
            </select>
            <label className="context-bar__keep">
              <span>Keep last</span>
              <select value={measure.keep_last} aria-label="Messages kept word for word" onChange={(e) => void saveSettings({ keep_last: Number(e.target.value) })}>
                {[4, 6, 8, 12, 20].map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </label>
          </div>
          <div className="context-bar__actions">
            {measure.can_undo && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void undo()}>Undo Compaction</button>}
            <button type="button" className="btn btn-primary" disabled={busy || !measure.can_compact} onClick={() => void compact()}>
              {measure.can_compact ? "Compact Now" : "Nothing to Compact Yet"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
