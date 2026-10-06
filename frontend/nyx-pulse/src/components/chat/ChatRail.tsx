/** The chats down the left side of the Nyx tab, like Claude's (Update 1, U48).
 *
 * The owner (2026-10-05): "we move chats to the left side so we can click a dropdown for the chats there and select a
 * new one, or old one, or branch one, or semi branch one along with everything else we have, similar to Claude setup".
 *
 *  • **New chat** at the top, then a search box, then every chat grouped Today / Yesterday / This week / Older.
 *  • Each chat's ⋯ menu: Rename, **Branch** (a linked copy of every message — go another way from here), **Semi-branch**
 *    (a linked chat that starts from a summary of this one, so it is light), Duplicate, Delete. A chat made that way
 *    says so under its name, and where it came from.
 *  • Recently deleted at the bottom brings a chat back.
 *  • The Second Brain card at the foot (the owner: "for second mind it seems to be gone ... combine with the screen we
 *    have of nyx chat now") shows the memory field's size and opens it.
 *
 * The rail folds to a thin strip; how the owner left it is remembered.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import { Spinner } from "./AgentDisc";
import type { ChatSummaryView } from "./types";

export type RailMakeKind = "branch" | "fork" | "duplicate";

interface DeletedChat { id: string; title: string; deleted_at?: string | null }

const KIND_WORDS: Record<string, string> = { branch: "Branch", fork: "Semi-branch", duplicate: "Copy" };

function when(value: number | string | undefined): number {
  if (value === undefined || value === null || value === "") return 0;
  if (typeof value === "number") return value > 1e12 ? value : value * 1000;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function groupOf(ms: number, now: Date): string {
  if (!ms) return "Older";
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (ms >= start) return "Today";
  if (ms >= start - 86_400_000) return "Yesterday";
  if (ms >= start - 6 * 86_400_000) return "This week";
  return "Older";
}

const GROUPS = ["Today", "Yesterday", "This week", "Older"];

export function ChatRail({ chats, activeId, runningByChat, onSelect, onNew, onRename, onDelete, onMake, onRestored,
  brain, onOpenBrain }: {
  chats: ChatSummaryView[];
  activeId: string;
  runningByChat: Record<string, string | undefined>;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  /** Branch, semi-branch or duplicate a chat — any chat in the list, not only the open one. */
  onMake: (id: string, kind: RailMakeKind) => void;
  onRestored: () => void;
  /** The Second Brain at a glance, when the field has loaded. */
  brain?: { memories: number; today: number } | null;
  onOpenBrain?: () => void;
}) {
  const [folded, setFolded] = useState(() => { try { return localStorage.getItem("nyx.rail.folded") === "1"; } catch { return false; } });
  const [query, setQuery] = useState("");
  const [menu, setMenu] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleted, setDeleted] = useState<DeletedChat[] | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => { try { localStorage.setItem("nyx.rail.folded", folded ? "1" : "0"); } catch { /* not kept */ } }, [folded]);

  // A click anywhere else closes the open ⋯ menu.
  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent) => { if (!menuRef.current?.contains(event.target as Node)) { setMenu(null); setConfirming(null); } };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [menu]);

  const titles = useMemo(() => Object.fromEntries(chats.map((c) => [c.id, c.title])), [chats]);
  const groups = useMemo(() => {
    const now = new Date();
    const wanted = query.trim().toLowerCase();
    const out: Record<string, ChatSummaryView[]> = {};
    for (const chat of chats) {
      if (wanted && !chat.title.toLowerCase().includes(wanted)) continue;
      (out[groupOf(when(chat.updatedAt), now)] ??= []).push(chat);
    }
    return out;
  }, [chats, query]);

  const loadDeleted = useCallback(async () => {
    const result = await api.get<{ chats: DeletedChat[] }>("/api/chat-trash");
    setDeleted(result.ok ? result.data.chats || [] : []);
  }, []);

  const restore = async (id: string) => {
    const result = await api.post(`/api/chat-trash/${encodeURIComponent(id)}/restore`, {});
    if (result.ok) { onRestored(); void loadDeleted(); }
  };

  const finishRename = (id: string) => {
    const title = draft.trim();
    setRenaming(null);
    if (title && title !== titles[id]) onRename(id, title);
  };

  if (folded) {
    return (
      <nav className="chat-rail is-folded" aria-label="Chats">
        <button type="button" className="chat-rail__icon" onClick={() => setFolded(false)} aria-label="Show your chats" title="Show your chats">☰</button>
        <button type="button" className="chat-rail__icon" onClick={onNew} aria-label="New chat" title="New chat">＋</button>
        {onOpenBrain && <button type="button" className="chat-rail__icon" onClick={onOpenBrain} aria-label="Open the Second Brain" title="Second Brain">◐</button>}
      </nav>
    );
  }

  return (
    <nav className="chat-rail" aria-label="Chats">
      <div className="chat-rail__top">
        <button type="button" className="chat-rail__new" onClick={onNew}>＋ New chat</button>
        <button type="button" className="chat-rail__icon" onClick={() => setFolded(true)} aria-label="Hide the chat list" title="Hide the chat list">⟨</button>
      </div>
      <input className="chat-rail__search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search chats"
             aria-label="Search chats" />

      <div className="chat-rail__list">
        {chats.length === 0 && <p className="chat-rail__empty">Your conversations will appear here.</p>}
        {chats.length > 0 && GROUPS.every((g) => !groups[g]?.length) && <p className="chat-rail__empty">No chat matches “{query}”.</p>}
        {GROUPS.filter((g) => groups[g]?.length).map((group) => (
          <section key={group} aria-label={group}>
            <h3 className="chat-rail__group">{group}</h3>
            <ul>
              {groups[group].map((chat) => {
                const made = chat.kind && KIND_WORDS[chat.kind];
                const parent = chat.parentId ? titles[chat.parentId] : "";
                return (
                  <li key={chat.id} className={`chat-rail__item${chat.id === activeId ? " is-active" : ""}`}>
                    {renaming === chat.id ? (
                      <input className="chat-rail__rename" value={draft} autoFocus aria-label="Chat name"
                             onChange={(e) => setDraft(e.target.value)} onBlur={() => finishRename(chat.id)}
                             onKeyDown={(e) => { if (e.key === "Enter") finishRename(chat.id); if (e.key === "Escape") setRenaming(null); }} />
                    ) : (
                      <button type="button" className="chat-rail__open" onClick={() => onSelect(chat.id)}
                              aria-current={chat.id === activeId ? "page" : undefined}
                              title={made && parent ? `${made} of “${parent}”` : chat.title}>
                        <span className="chat-rail__title">{chat.title || "New chat"}</span>
                        {made && <span className="chat-rail__made">{made}{parent ? ` of ${parent}` : ""}</span>}
                      </button>
                    )}
                    {runningByChat[chat.id] && <Spinner className="nyx-spinner--xs" />}
                    <button type="button" className="chat-rail__more" aria-haspopup="menu" aria-expanded={menu === chat.id}
                            aria-label={`More for ${chat.title}`} onClick={() => { setMenu(menu === chat.id ? null : chat.id); setConfirming(null); }}>⋯</button>
                    {menu === chat.id && (
                      <div ref={menuRef} className="chat-rail__menu" role="menu">
                        <button role="menuitem" onClick={() => { setMenu(null); setDraft(chat.title); setRenaming(chat.id); }}>Rename</button>
                        <button role="menuitem" onClick={() => { setMenu(null); onMake(chat.id, "branch"); }}>
                          Branch<small>every message, then go another way</small>
                        </button>
                        <button role="menuitem" onClick={() => { setMenu(null); onMake(chat.id, "fork"); }}>
                          Semi-branch<small>starts from a summary, stays linked</small>
                        </button>
                        <button role="menuitem" onClick={() => { setMenu(null); onMake(chat.id, "duplicate"); }}>Duplicate</button>
                        {confirming === chat.id ? (
                          <button role="menuitem" className="is-risk" onClick={() => { setMenu(null); setConfirming(null); onDelete(chat.id); }}>
                            Delete — sure?
                          </button>
                        ) : (
                          <button role="menuitem" className="is-risk" onClick={() => setConfirming(chat.id)}>Delete</button>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>

      <div className="chat-rail__foot">
        <button type="button" className="chat-rail__link" onClick={() => (deleted ? setDeleted(null) : void loadDeleted())}
                aria-expanded={deleted !== null}>Recently deleted</button>
        {deleted && (
          <ul className="chat-rail__deleted">
            {deleted.length === 0 && <li className="chat-rail__empty">Nothing deleted.</li>}
            {deleted.slice(0, 12).map((item) => (
              <li key={item.id}><span>{item.title}</span><button type="button" onClick={() => void restore(item.id)}>Restore</button></li>
            ))}
          </ul>
        )}
        {onOpenBrain && (
          <button type="button" className="chat-rail__brain" onClick={onOpenBrain} title="Open the Second Brain — the memory field and voice">
            <span className="chat-rail__brain-mark" aria-hidden="true">◐</span>
            <span><b>Second Brain</b><small>{brain ? `${brain.memories.toLocaleString()} memories · +${brain.today.toLocaleString()} today` : "the memory field and voice"}</small></span>
          </button>
        )}
      </div>
    </nav>
  );
}
