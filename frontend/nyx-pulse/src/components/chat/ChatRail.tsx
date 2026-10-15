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
 *  • "Hide empty chats" (Fixer Upper S25 auto filter) keeps chats with no messages out of the list. The open chat and a
 *    chat still answering always stay, so a brand-new chat never vanishes the moment it is made. Remembered.
 *  • The Second Brain card at the foot (the owner: "for second mind it seems to be gone ... combine with the screen we
 *    have of nyx chat now") shows the memory field's size and opens it.
 *
 * The rail folds to a thin strip; how the owner left it is remembered.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../../api";
import { Spinner } from "./AgentDisc";
import type { ChatSummaryView } from "./types";
import { PersonaBadge } from "./PersonaBadge";
import { WhatsAppMark, useWhatsAppChats } from "./WhatsAppMark";
import { AttentionMark, useAttention } from "../commander/attention";
import { openChatPane, startChatDrag } from "./panes/paneDrag";
import { ownerName } from "./phrases";

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
const PINS_KEY = "nyx.rail.pins";

function readPins(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(PINS_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string") : [];
  } catch { return []; }
}

/** Open a tab, at one of its sections when given (the section is saved first, so the hub opens on it). */
function openPlace(tab: string, section?: string): void {
  if (section) {
    try { localStorage.setItem(`ichos.hub.${tab}`, section); } catch { /* not kept */ }
    window.dispatchEvent(new CustomEvent("ichos:open-section", { detail: { hub: tab, section } }));
  }
  window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab } }));
}

/** The places at the top of Claude's sidebar, mapped to where they live in Ichos (owner's 2026-10-15 images). */
const NAV: { id: string; label: string; icon: string; open: () => void; badge?: string }[] = [
  { id: "projects", label: "Projects", icon: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z", open: () => openPlace("projects", "projects"), badge: "Beta" },
  { id: "artifacts", label: "Artifacts", icon: "M12 3 3 8l9 5 9-5-9-5zM3 13l9 5 9-5", open: () => openPlace("projects", "artifacts") },
  { id: "scheduled", label: "Scheduled", icon: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z", open: () => openPlace("projects", "scheduled") },
  { id: "customize", label: "Customize", icon: "M4 7h10M18 7h2M4 17h4M12 17h8M14 4v6M8 14v6", open: () => window.dispatchEvent(new CustomEvent("ichos:open-settings", { detail: { page: "appearance" } })) },
];

const MORE: { tab: string; label: string }[] = [
  { tab: "code", label: "Code" },
  { tab: "notes", label: "Notes" },
  { tab: "research", label: "Research Lab" },
  { tab: "agents", label: "Agents" },
  { tab: "connectors", label: "Connections" },
  { tab: "improve", label: "Improve" },
];

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";
}

function NavIcon({ d }: { d: string }) {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
  );
}

export function ChatRail({ chats, activeId, runningByChat, onSelect, onNew, onRename, onDelete, onMake, onRestored,
  brain, onOpenBrain, projects }: {
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
  /** The compact chat's Projects list (ProjectHome.tsx), shown above the chats like Claude's. */
  projects?: ReactNode;
}) {
  const whatsapp = useWhatsAppChats();
  const needs = useAttention();  // which chats need the owner: a mark beside the name (Drive doc 1, item 1.19)
  const [folded, setFolded] = useState(() => { try { return localStorage.getItem("nyx.rail.folded") === "1"; } catch { return false; } });
  const [query, setQuery] = useState("");
  const [menu, setMenu] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleted, setDeleted] = useState<DeletedChat[] | null>(null);
  const [hideEmpty, setHideEmpty] = useState(() => { try { return localStorage.getItem("nyx.rail.hideEmpty") === "1"; } catch { return false; } });
  const menuRef = useRef<HTMLDivElement>(null);
  // Pinned chats sit above the dated groups, like Claude's Pinned list (kept in this browser).
  const [pins, setPins] = useState<string[]>(readPins);
  const [moreOpen, setMoreOpen] = useState(false);
  const togglePin = (id: string) => setPins((current) => {
    const next = current.includes(id) ? current.filter((x) => x !== id) : [id, ...current];
    try { localStorage.setItem(PINS_KEY, JSON.stringify(next)); } catch { /* not kept */ }
    window.setTimeout(() => window.dispatchEvent(new Event("nyx:pins")), 0);  // the Overview's Pinned group follows
    return next;
  });

  useEffect(() => { try { localStorage.setItem("nyx.rail.folded", folded ? "1" : "0"); } catch { /* not kept */ } }, [folded]);
  useEffect(() => { try { localStorage.setItem("nyx.rail.hideEmpty", hideEmpty ? "1" : "0"); } catch { /* not kept */ } }, [hideEmpty]);

  // A click anywhere else closes the open ⋯ menu.
  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent) => { if (!menuRef.current?.contains(event.target as Node)) { setMenu(null); setConfirming(null); } };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [menu]);

  const titles = useMemo(() => Object.fromEntries(chats.map((c) => [c.id, c.title])), [chats]);
  // A chat counts as empty only when the engine says it has no messages; an unknown count is kept.
  const isEmpty = useCallback((chat: ChatSummaryView) =>
    chat.messageCount === 0 && chat.id !== activeId && !runningByChat[chat.id], [activeId, runningByChat]);
  const hiddenCount = hideEmpty ? chats.filter(isEmpty).length : 0;
  const groups = useMemo(() => {
    const now = new Date();
    const wanted = query.trim().toLowerCase();
    const out: Record<string, ChatSummaryView[]> = {};
    for (const chat of chats) {
      if (wanted && !chat.title.toLowerCase().includes(wanted)) continue;
      if (hideEmpty && isEmpty(chat)) continue;
      if (pins.includes(chat.id)) { (out.Pinned ??= []).push(chat); continue; }
      (out[groupOf(when(chat.updatedAt), now)] ??= []).push(chat);
    }
    return out;
  }, [chats, query, hideEmpty, isEmpty, pins]);

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
        <input className="chat-rail__search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search"
               aria-label="Search chats" />
        <button type="button" className="chat-rail__icon" onClick={() => setFolded(true)} aria-label="Hide the chat list" title="Hide the chat list">⟨</button>
      </div>
      <ul className="chat-rail__nav" aria-label="Places">
        <li><button type="button" className="chat-rail__navitem" onClick={onNew}><NavIcon d="M12 5v14M5 12h14" /> New</button></li>
        {NAV.map((item) => (
          <li key={item.id}>
            <button type="button" className="chat-rail__navitem" onClick={item.open}>
              <NavIcon d={item.icon} /> {item.label}{item.badge && <span className="chat-rail__badge">{item.badge}</span>}
            </button>
          </li>
        ))}
        <li>
          <button type="button" className="chat-rail__navitem" aria-expanded={moreOpen} onClick={() => setMoreOpen((v) => !v)}>
            <NavIcon d="M5 12h.01M12 12h.01M19 12h.01" /> More
          </button>
          {moreOpen && (
            <ul className="chat-rail__more-list">
              {MORE.map((m) => (
                <li key={m.tab}><button type="button" className="chat-rail__navitem is-sub" onClick={() => openPlace(m.tab)}>{m.label}</button></li>
              ))}
            </ul>
          )}
        </li>
      </ul>
      {projects}
      <label className="chat-rail__filter" title="Chats with no messages stay out of the list (the open one always shows)">
        <input type="checkbox" checked={hideEmpty} onChange={(e) => setHideEmpty(e.target.checked)} />
        Hide empty chats{hiddenCount > 0 ? ` (${hiddenCount} hidden)` : ""}
      </label>

      <div className="chat-rail__list">
        {chats.length === 0 && <p className="chat-rail__empty">Your conversations will appear here.</p>}
        {chats.length > 0 && ["Pinned", ...GROUPS].every((g) => !groups[g]?.length) && (
          <p className="chat-rail__empty">{query.trim() ? `No chat matches “${query}”.` : "Every chat here is empty — untick Hide empty chats to see them."}</p>
        )}
        {["Pinned", ...GROUPS].filter((g) => groups[g]?.length).map((group) => (
          <section key={group} aria-label={group}>
            <h3 className="chat-rail__group">{group}</h3>
            <ul>
              {groups[group].map((chat) => {
                const made = chat.kind && KIND_WORDS[chat.kind];
                const parent = chat.parentId ? titles[chat.parentId] : "";
                return (
                  <li key={chat.id} className={`chat-rail__item${chat.id === activeId ? " is-active" : ""}`}
                    data-chat-id={chat.id} data-chat-title={chat.title || "New chat"}>
                    {renaming === chat.id ? (
                      <input className="chat-rail__rename" value={draft} autoFocus aria-label="Chat name"
                             onChange={(e) => setDraft(e.target.value)} onBlur={() => finishRename(chat.id)}
                             onKeyDown={(e) => { if (e.key === "Enter") finishRename(chat.id); if (e.key === "Escape") setRenaming(null); }} />
                    ) : (
                      <button type="button" className="chat-rail__open" onClick={() => onSelect(chat.id)}
                              draggable onDragStart={(e) => startChatDrag(e, chat.id, chat.title || "New chat")}
                              aria-current={chat.id === activeId ? "page" : undefined}
                              title={made && parent ? `${made} of “${parent}”` : chat.title}>
                        <span className="chat-rail__title">{chat.title || "New chat"}</span>
                        <AttentionMark need={needs[chat.id]} />
                        <PersonaBadge persona={chat.persona} small />
                        <WhatsAppMark on={whatsapp.linked.has(chat.id)} />
                        {made && <span className="chat-rail__made">{made}{parent ? ` of ${parent}` : ""}</span>}
                      </button>
                    )}
                    {runningByChat[chat.id] && <Spinner className="nyx-spinner--xs" />}
                    <button type="button" className="chat-rail__more" aria-haspopup="menu" aria-expanded={menu === chat.id}
                            aria-label={`More for ${chat.title}`} onClick={() => { setMenu(menu === chat.id ? null : chat.id); setConfirming(null); }}>⋯</button>
                    {menu === chat.id && (
                      <div ref={menuRef} className="chat-rail__menu" role="menu">
                        <button role="menuitem" onClick={() => { setMenu(null); openChatPane(chat.id, "right"); }}>
                          Open beside<small>or drag it onto the chat — any side</small>
                        </button>
                        <button role="menuitem" onClick={() => { setMenu(null); togglePin(chat.id); }}>{pins.includes(chat.id) ? "Unpin" : "Pin"}</button>
                        <button role="menuitem" onClick={() => { setMenu(null); setDraft(chat.title); setRenaming(chat.id); }}>Rename</button>
                        {whatsapp.available && (
                          <button role="menuitem" onClick={() => { setMenu(null); void whatsapp.toggle(chat.id); }}>
                            {whatsapp.linked.has(chat.id) ? "Take off WhatsApp" : "Connect to WhatsApp"}
                            <small>{whatsapp.linked.has(chat.id) ? "the phone stops seeing this chat" : "carry on from your phone with /chat"}</small>
                          </button>
                        )}
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
        <button type="button" className="chat-rail__me" title="Settings"
          onClick={() => window.dispatchEvent(new CustomEvent("ichos:open-settings", { detail: {} }))}>
          <span className="chat-rail__avatar" aria-hidden="true">{initials(ownerName() || "You")}</span>
          <span className="chat-rail__me-name">{ownerName() || "You"}</span>
          <span className="chat-rail__me-role">Owner</span>
        </button>
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
