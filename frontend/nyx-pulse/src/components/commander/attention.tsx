/** Which chats need the owner right now, for a mark next to a chat's name in any list (Drive doc 1, item 1.19: the
 *  symbol next to a chat changes when the AI needs help or approval, like Claude Code). Reads commander.attention()
 *  through /api/commander/attention, which covers every chat (normal, project and thread), not only threads. */

import { useEffect, useState } from "react";
import { api } from "../../api";
import "./attention.css";

export interface Attention { chat_id: string; status: "needs_you" | "working"; kind: string; line: string; label: string }

export function useAttention(pollMs = 4000): Record<string, Attention> {
  const [byChat, setByChat] = useState<Record<string, Attention>>({});
  useEffect(() => {
    let live = true;
    const load = async () => {
      if (document.hidden) return;
      const r = await api.get<{ chats: Attention[] }>("/api/commander/attention");
      if (live && r.ok) setByChat(Object.fromEntries(r.data.chats.map((c) => [c.chat_id, c])));
    };
    void load();
    const timer = window.setInterval(() => void load(), pollMs);
    return () => { live = false; window.clearInterval(timer); };
  }, [pollMs]);
  return byChat;
}

/** "!" for an approval, "?" for a question or a "Waiting on you" line; nothing when the chat needs nothing. */
export function AttentionMark({ need }: { need?: Attention }) {
  if (!need || need.status !== "needs_you") return null;
  const what = need.kind === "approval" ? "wants approval" : "needs your answer";
  return <span className="attn-mark" role="img" title={`${need.label}: ${need.line}`} aria-label={`${what}: ${need.line}`}>{need.kind === "approval" ? "!" : "?"}</span>;
}
