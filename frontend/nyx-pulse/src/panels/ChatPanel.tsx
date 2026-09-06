/** The chat tab.
 *
 * This panel deliberately owns no conversation state. It used to hold messages
 * in `useState`, which meant switching to any other tab unmounted it and threw
 * the conversation away — the single most visible bug in the app. The transcript
 * now lives in App, which stays mounted for the life of the session, so a tab
 * switch is just a remount over the same data.
 *
 * The provider dropdown sits with the composer because that is the moment the
 * choice matters: it applies to the next message, not retroactively.
 */

import { useEffect, useRef, useState } from "react";
import { api, endpoints, type ChatMessage } from "../api";
import { PanelShell } from "../components/Panel";
import { AUTO_PROVIDER, ProviderPicker } from "../components/ProviderPicker";
import type { AvatarState } from "../components/NyxAvatar";

export function ChatPanel({
  onActivity,
  messages,
  onMessages,
  draft,
  onDraft,
  busy,
  onBusy,
  provider,
  onProvider,
  restored,
}: {
  onActivity?: (s: AvatarState) => void;
  messages: ChatMessage[];
  onMessages: (update: (m: ChatMessage[]) => ChatMessage[]) => void;
  draft: string;
  onDraft: (draft: string) => void;
  busy: boolean;
  onBusy: (busy: boolean) => void;
  provider: string;
  onProvider: (provider: string) => void;
  /** Where the transcript on screen came from, shown so it is not a mystery. */
  restored?: "server" | "local" | null;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Remounting after a tab switch starts scrolled to the top; the last thing
  // said is the thing you want to see.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length]);

  // A spinner says "something is happening"; it does not say "still happening".
  // A request that takes twelve seconds looks identical to one that has hung,
  // so the bar carries an elapsed count and names the provider being waited on.
  const [elapsed, setElapsed] = useState(0);
  const [waitingOn, setWaitingOn] = useState<string>("");

  useEffect(() => {
    if (!busy) { setElapsed(0); return; }
    const started = Date.now();
    const id = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 100) / 10), 100);
    return () => window.clearInterval(id);
  }, [busy]);

  const [forking, setForking] = useState(false);

  async function fork() {
    if (forking) return;
    setForking(true);
    const result = await api.post<{ chat: { id: string; title: string } }>(
      "/api/chats/fork", {},
    );
    setForking(false);
    if (result.ok) {
      // Say what happened rather than silently switching context. A branch that
      // appears with no explanation is indistinguishable from losing the thread.
      onMessages((m) => [...m, {
        role: "assistant",
        content:
          `Branched into "${result.data.chat.title}". It starts with this conversation's recent ` +
          "context and both chats remember the link, so they can be worked on separately and " +
          "still be related afterwards.",
      }]);
    } else {
      onMessages((m) => [...m, { role: "error", content: result.error }]);
    }
  }

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;

    onMessages((m) => [...m, { role: "user", content: text }]);
    onDraft("");
    onBusy(true);
    onActivity?.("thinking");
    setWaitingOn(provider === AUTO_PROVIDER ? "auto" : provider);

    const started = performance.now();
    const result = await endpoints.chat(text, provider || undefined);
    const elapsedMs = Math.round(performance.now() - started);

    onMessages((m) => [
      ...m,
      result.ok
        ? {
            role: "assistant",
            content: result.data.reply || "",
            provider: result.data.provider,
            elapsedMs,
          }
        : { role: "error", content: result.error, elapsedMs },
    ]);
    onBusy(false);
    onActivity?.(result.ok ? "idle" : "error");
  }

  const subtitle = busy
    ? "Thinking…"
    : provider === AUTO_PROVIDER
      ? "Auto mode — speed and provider selected per turn"
      : `Sending to ${provider}`;

  return (
    <PanelShell
      title="Chat"
      subtitle={subtitle}
      actions={
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="btn btn-secondary"
            onClick={() => void fork()}
            disabled={forking}
            title="Start a linked chat that carries this conversation's context. Both chats remember the link, so work can be split and still be related."
          >
            {forking ? "Branching…" : "Branch"}
          </button>
          {messages.length > 0 && (
            <button
              className="btn btn-secondary"
              onClick={() => onMessages(() => [])}
              title="Clear the transcript shown here"
            >
              Clear
            </button>
          )}
        </div>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, gap: 12 }}>
        {busy && (
          <div aria-live="polite">
            <div style={{
              display: "flex", justifyContent: "space-between",
              fontSize: 11, color: "var(--color-neutral-500)", marginBottom: 5,
            }}>
              <span>
                {waitingOn && waitingOn !== "auto"
                  ? `Waiting on ${waitingOn}…`
                  : "Choosing a model and answering…"}
              </span>
              <span>{elapsed.toFixed(1)}s</span>
            </div>
            {/* Indeterminate on purpose: the server does not report progress, and
                a bar that pretends to know how far along it is would be a lie. */}
            <div className="nyx-progress"><span /></div>
          </div>
        )}
        <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
          {messages.length === 0 && (
            <div style={{ color: "var(--color-neutral-600)", fontSize: 13, lineHeight: 1.7 }}>
              Ask anything. Simple questions take the fast path automatically; anything needing
              tools, fresh data, or code uses the full pipeline. The conversation stays here when
              you switch tabs.
            </div>
          )}
          {messages.length > 0 && restored === "local" && (
            <div style={{ fontSize: 11, color: "var(--color-neutral-600)", lineHeight: 1.5 }}>
              Restored from this browser. The backend keeps its own copy of the conversation but
              does not expose it over HTTP yet, so this transcript is per-device.
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
              <div
                className="card"
                style={{
                  maxWidth: "78%",
                  background: m.role === "user" ? "var(--color-accent-900)" : "var(--color-surface)",
                  borderLeft: m.role === "error" ? "3px solid var(--color-danger)" : undefined,
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.6,
                  fontSize: 14,
                }}
              >
                {m.content}
                {(m.provider || m.elapsedMs !== undefined) && (
                  <div style={{ marginTop: 8, fontSize: 11, color: "var(--color-neutral-600)", fontFamily: "var(--font-mono)" }}>
                    {m.provider ?? "error"}
                    {m.elapsedMs !== undefined && ` · ${(m.elapsedMs / 1000).toFixed(2)}s`}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: "none" }}>
          <ProviderPicker value={provider} onChange={onProvider} compact />
          <div style={{ display: "flex", gap: 8 }}>
            <textarea
              value={draft}
              onChange={(e) => onDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
              rows={2}
              placeholder="Message Nyx…  (Enter to send, Shift+Enter for a new line)"
              style={{
                flex: 1,
                resize: "none",
                background: "var(--color-surface)",
                color: "var(--color-text)",
                border: "none",
                borderRadius: "var(--radius)",
                padding: "10px 12px",
                font: "inherit",
                fontSize: 14,
                boxShadow: "inset 0 0 0 1px var(--color-divider)",
              }}
            />
            <button className="btn btn-primary" onClick={() => void send()} disabled={busy || !draft.trim()}
              style={{ opacity: busy || !draft.trim() ? 0.5 : 1, alignSelf: "stretch", padding: "0 18px" }}>
              {busy ? "…" : "Send"}
            </button>
          </div>
        </div>
      </div>
    </PanelShell>
  );
}
