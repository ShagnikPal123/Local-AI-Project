/** Settings › Storage › Reset chats (owner, 2026-10-14: "add that as an option if the user feels their chats have
 * gotten out of hand", and "add a clear for whatsapp chat as well"). Backed by POST /api/chat-reset (chat_reset.py).
 *
 * Everything it touches is copied to a backup folder first, and chats go to Recently deleted, never straight out.
 */

import { useState } from "react";
import { api } from "../../api";

type Part = "voice" | "mods" | "messages" | "avatars" | "whatsapp";

const PARTS: { id: Part; label: string; hint: string; on: boolean }[] = [
  { id: "voice", label: "How Ichos talks", hint: "Drops any personality stuck to a chat, puts the notch back to Ichos's own voice and forgets cached answers. Avatars keep their own.", on: true },
  { id: "mods", label: "“Talk like…” mods", hint: "Pauses mods with standing instructions. Switch them back on in Mods.", on: true },
  { id: "messages", label: "My chats", hint: "Moves every Ichos chat to Recently deleted (restore for 30 days).", on: false },
  { id: "avatars", label: "Avatar chats", hint: "Moves each avatar's own chat to Recently deleted. Their settings and notes stay.", on: false },
  { id: "whatsapp", label: "WhatsApp chat", hint: "Clears the phone line's chats and log. The pairing stays.", on: false },
];

interface ResetResult {
  backup: string; chat_voices_cleared?: number; mods_paused?: string[]; chats_moved?: number;
  avatar_chats_moved?: number; whatsapp?: { cleared?: boolean; error?: string };
}

function summary(r: ResetResult): string {
  const parts: string[] = [];
  if (r.chat_voices_cleared !== undefined) parts.push("voice reset");
  if (r.mods_paused?.length) parts.push(`paused ${r.mods_paused.join(", ")}`);
  if (r.chats_moved !== undefined) parts.push(`${r.chats_moved} chat${r.chats_moved === 1 ? "" : "s"} moved`);
  if (r.avatar_chats_moved !== undefined) parts.push(`${r.avatar_chats_moved} avatar chat${r.avatar_chats_moved === 1 ? "" : "s"} moved`);
  if (r.whatsapp) parts.push(r.whatsapp.cleared ? "WhatsApp cleared" : `WhatsApp not cleared (${r.whatsapp.error ?? "error"})`);
  return `Done: ${parts.join(" · ") || "nothing needed changing"}. Backup: ${r.backup}`;
}

export function ChatResetSection() {
  const [picked, setPicked] = useState<Set<Part>>(new Set(PARTS.filter((p) => p.on).map((p) => p.id)));
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const toggle = (id: Part) => setPicked((old) => {
    const next = new Set(old);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  async function run() {
    const moving = picked.has("messages") || picked.has("avatars") || picked.has("whatsapp");
    if (moving && !window.confirm("Move the chosen chats to Recently deleted? A backup is made first.")) return;
    setBusy(true);
    const result = await api.post<ResetResult>("/api/chat-reset", { parts: [...picked] });
    setBusy(false);
    setNote(result.ok ? summary(result.data) : "That did not work. Nothing was changed.");
  }

  return (
    <div className="appearance">
      <span className="appearance__hint">If chats have gotten out of hand (a voice that will not go away, an avatar talking where it should not), reset what you pick below.</span>
      {PARTS.map((part) => (
        <div className="appearance__row" key={part.id}>
          <label className="appearance__custom">
            <input type="checkbox" checked={picked.has(part.id)} onChange={() => toggle(part.id)} aria-label={part.label} />
            <span className="appearance__label">{part.label}</span>
          </label>
          <span className="appearance__hint">{part.hint}</span>
        </div>
      ))}
      <div className="appearance__row">
        <button type="button" className="btn" onClick={() => void run()} disabled={busy || picked.size === 0}>{busy ? "Resetting…" : "Reset chosen"}</button>
        <span className="appearance__hint" role="status">{note}</span>
      </div>
    </div>
  );
}
