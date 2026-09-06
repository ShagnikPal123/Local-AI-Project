/** Sessions & Memory tab (ROADMAP BB4, E3, E4).
 *
 * Shows the memory layers as they actually are: a permanent knowledge base, a
 * dynamic working memory, and per-chat history. Being explicit about which layer
 * a fact lives in matters, because "why did it forget that" is almost always a
 * question about which layer something landed in.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";

interface MemoryResponse {
  important?: { topic: string; content: string }[];
  preferences?: Record<string, unknown>;
}

interface ChatsResponse {
  chats?: { id?: string; title?: string; message_count?: number }[];
  count?: number;
}

interface KnowledgeResponse {
  entries?: number;
  loaded?: boolean;
  path?: string;
  [key: string]: unknown;
}

function Layer({ title, subtitle, children }: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card">
      <div className="label" style={{ marginBottom: 3 }}>{title}</div>
      <div style={{ fontSize: 12, color: "var(--color-neutral-600)", marginBottom: 11, lineHeight: 1.55 }}>
        {subtitle}
      </div>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>{text}</div>;
}

export function WorkPanel() {
  const [memory, setMemory] = useState<MemoryResponse | null>(null);
  const [chats, setChats] = useState<ChatsResponse | null>(null);
  const [knowledge, setKnowledge] = useState<KnowledgeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void Promise.all([
      api.get<MemoryResponse>("/api/memory"),
      api.get<ChatsResponse>("/api/chats"),
      api.get<KnowledgeResponse>("/api/knowledge"),
    ]).then(([m, c, k]) => {
      if (!alive) return;
      if (m.ok) setMemory(m.data);
      else setError(m.error);
      if (c.ok) setChats(c.data);
      if (k.ok) setKnowledge(k.data);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (error && !memory) {
    return <PanelShell title="Sessions & Memory"><ErrorState error={error} /></PanelShell>;
  }
  if (!memory) {
    return <PanelShell title="Sessions & Memory"><Loading what="Reading memory" /></PanelShell>;
  }

  const important = memory.important ?? [];
  const preferences = Object.entries(memory.preferences ?? {});
  const chatList = chats?.chats ?? [];

  return (
    <PanelShell title="Sessions & Memory" subtitle="What the agent remembers, and where it lives">
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Layer
          title="Permanent knowledge"
          subtitle="Foundational facts loaded at startup. Survives every session."
        >
          {knowledge?.loaded ? (
            <div style={{ fontSize: 13 }}>
              Loaded
              {typeof knowledge.entries === "number" && ` · ${knowledge.entries} entries`}
              {knowledge.path && (
                <div style={{
                  fontSize: 11, color: "var(--color-neutral-600)",
                  fontFamily: "var(--font-mono)", marginTop: 4,
                }}>
                  {String(knowledge.path)}
                </div>
              )}
            </div>
          ) : (
            <Empty text="No permanent knowledge loaded. general_knowledge.md exists in the project but is not yet wired in (roadmap E3)." />
          )}
        </Layer>

        <Layer
          title="Working memory"
          subtitle="Facts and preferences the agent picked up while talking to you."
        >
          {important.length === 0 && preferences.length === 0 ? (
            <Empty text="Nothing saved yet. This fills as you chat." />
          ) : (
            <>
              {important.map((item, i) => (
                <div key={i} style={{ padding: "7px 0", boxShadow: "inset 0 -1px 0 var(--color-divider)" }}>
                  <div style={{ fontSize: 12, color: "var(--color-accent)", fontFamily: "var(--font-mono)" }}>
                    {item.topic}
                  </div>
                  <div style={{ fontSize: 13, marginTop: 2, lineHeight: 1.55 }}>{item.content}</div>
                </div>
              ))}
              {preferences.map(([key, value]) => (
                <div key={key} style={{
                  display: "flex", justifyContent: "space-between", gap: 12,
                  padding: "6px 0", fontSize: 13,
                }}>
                  <span style={{ color: "var(--color-neutral-500)" }}>{key}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{String(value)}</span>
                </div>
              ))}
            </>
          )}
        </Layer>

        <Layer
          title="Sessions"
          subtitle="Each chat keeps its own history and its own service instance."
        >
          {chatList.length === 0 ? (
            <Empty text="No saved chats yet." />
          ) : (
            chatList.map((chat, i) => (
              <div key={chat.id ?? i} style={{
                display: "flex", justifyContent: "space-between", gap: 12,
                padding: "7px 0", fontSize: 13,
              }}>
                <span>{chat.title || chat.id || `Chat ${i + 1}`}</span>
                {typeof chat.message_count === "number" && (
                  <span style={{ color: "var(--color-neutral-600)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                    {chat.message_count} msgs
                  </span>
                )}
              </div>
            ))
          )}
        </Layer>

        <div className="card" style={{ borderLeft: "3px solid var(--color-accent-700)" }}>
          <div className="label" style={{ marginBottom: 6 }}>Still to build</div>
          <div style={{ fontSize: 12, color: "var(--color-neutral-400)", lineHeight: 1.65 }}>
            Obsidian as the primary store with this memory demoted to secondary (E2), a RAG
            search box over stored memories (E1), and editing or deleting entries from here.
            Right now memory is read-only in the UI.
          </div>
        </div>
      </div>
    </PanelShell>
  );
}
