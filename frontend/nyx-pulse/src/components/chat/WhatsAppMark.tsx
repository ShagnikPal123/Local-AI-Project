/** Which chats are connected to WhatsApp (Drive doc 1, item 1.8): a small green phone mark beside their name in the
 * chat list, and a "WhatsApp" item in each chat's ⋯ menu to connect it or take it off.
 *
 * Read from /api/whatsapp/chats (the `whatsapp` flag per chat) when the list opens, every minute after, and right
 * after a change. When WhatsApp isn't set up the call fails quietly and nothing is drawn.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";

export function useWhatsAppChats(): { linked: Set<string>; available: boolean; toggle: (id: string) => Promise<string | null> } {
  const [linked, setLinked] = useState<Set<string>>(new Set());
  const [available, setAvailable] = useState(false);
  const load = useCallback(async () => {
    const r = await api.get<{ chats: { id: string; whatsapp?: boolean }[] }>("/api/whatsapp/chats");
    if (!r.ok) { setAvailable(false); return; }
    setAvailable(true);
    const next = new Set(r.data.chats.filter((c) => c.whatsapp).map((c) => c.id));
    setLinked((old) => old.size === next.size && [...next].every((id) => old.has(id)) ? old : next);
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(timer);
  }, [load]);
  const toggle = useCallback(async (id: string) => {
    const r = await api.post("/api/whatsapp/link-chat", { chat_id: id, linked: !linked.has(id) });
    await load();
    return r.ok ? null : r.error;
  }, [linked, load]);
  return { linked, available, toggle };
}

export function WhatsAppMark({ on }: { on: boolean }) {
  if (!on) return null;
  return (
    <span className="wa-mark" title="Connected to WhatsApp: you can carry on from your phone with /chat" aria-label="On WhatsApp">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm5.3 14.1c-.2.6-1.3 1.2-1.8 1.2-.5.1-1 .2-3.3-.7-2.8-1.1-4.6-4-4.7-4.2-.1-.2-1.1-1.5-1.1-2.9s.7-2 1-2.3c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.8 2c.1.2.1.4 0 .5l-.3.5-.4.4c-.1.1-.3.3-.1.6.2.3.7 1.2 1.6 2 1.1 1 2 1.3 2.3 1.4.3.1.4.1.6-.1l.8-1c.2-.3.4-.2.6-.1l1.9.9c.3.1.5.2.5.3.1.2.1.7-.1 1.3z" />
      </svg>
    </span>
  );
}
