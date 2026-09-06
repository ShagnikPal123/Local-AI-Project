import { useRef, useState } from "react";
import { endpoints } from "../api";
import { PanelShell } from "../components/Panel";
import type { AvatarState } from "../components/NyxAvatar";

interface Message {
  role: "user" | "assistant" | "error";
  content: string;
  provider?: string;
  elapsedMs?: number;
}

export function ChatPanel({ onActivity }: { onActivity?: (s: AvatarState) => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;

    setMessages((m) => [...m, { role: "user", content: text }]);
    setDraft("");
    setBusy(true);
    onActivity?.("thinking");

    const started = performance.now();
    const result = await endpoints.chat(text);
    const elapsedMs = Math.round(performance.now() - started);

    setMessages((m) => [
      ...m,
      result.ok
        ? { role: "assistant", content: (result.data as any).reply || (result.data as any).response || "", provider: result.data.provider, elapsedMs }
        : { role: "error", content: result.error, elapsedMs },
    ]);
    setBusy(false);
    onActivity?.(result.ok ? "idle" : "error");
    queueMicrotask(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight }));
  }

  return (
    <PanelShell title="Chat" subtitle={busy ? "Thinking…" : "Auto mode — speed selected per turn"}>
      <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, gap: 12 }}>
        <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
          {messages.length === 0 && (
            <div style={{ color: "var(--color-neutral-600)", fontSize: 13, lineHeight: 1.7 }}>
              Ask anything. Simple questions take the fast path automatically; anything needing
              tools, fresh data, or code uses the full pipeline.
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

        <div style={{ display: "flex", gap: 8, flex: "none" }}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
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
    </PanelShell>
  );
}
