/** The compact chat picker on the Nyx tab: a pop-up button plus a rename button.
 *
 * It replaced a native <select> whose popup painted near-white text on the
 * select's translucent fill — the names were unreadable (Request G4). A custom
 * menu owns its colours: #F5F5F7 on #15151C (16.8:1), secondary #A1A1AA (7.1:1).
 *
 * Names: Nyx titles a chat from its first message; a name typed here locks the
 * title (`chat_sessions.rename` sets `title_locked`) so Nyx never overwrites it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChatSummaryView } from "./types";
import { Spinner } from "./AgentDisc";
import { api } from "../../api";

interface DeletedChat {
  id: string;
  title: string;
  deleted_at?: string | null;
  message_count?: number;
}

export function ChatSwitcher({
  chats,
  activeId,
  runningByChat,
  onSelect,
  onRename,
  onDelete,
  onRestored,
}: {
  chats: ChatSummaryView[];
  activeId: string;
  runningByChat: Record<string, string | undefined>;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  /** Delete a chat. It goes to Recently deleted, so the caller can offer Undo. */
  onDelete?: (id: string) => void;
  /** A deleted chat came back, so the chat list needs reloading. */
  onRestored?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  // The id whose delete is waiting for a second click. Deleting a conversation
  // from a menu row is one slip away, so it always asks first.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleted, setDeleted] = useState<DeletedChat[]>([]);
  const [showDeleted, setShowDeleted] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const active = chats.find((c) => c.id === activeId);
  const activeTitle = active?.title || "Current chat";
  const [draft, setDraft] = useState(activeTitle);

  const loadDeleted = useCallback(async () => {
    const result = await api.get<{ chats: DeletedChat[] }>("/api/chat-trash");
    if (result.ok) setDeleted(result.data.chats || []);
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? chats.filter((c) => (c.title || "").toLowerCase().includes(q)) : chats;
  }, [chats, query]);

  useEffect(() => {
    if (!open) return;
    void loadDeleted();
    setConfirming(null);
    setCursor(Math.max(0, shown.findIndex((c) => c.id === activeId)));
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node) && !buttonRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
    // Only on open: the cursor should start on the current chat, not follow filtering.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    menuRef.current?.querySelector<HTMLElement>(`[data-index="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  function choose(id: string) {
    onSelect(id);
    setOpen(false);
    setQuery("");
    buttonRef.current?.focus();
  }

  function commitRename() {
    const title = draft.trim();
    if (title && title !== activeTitle && active) onRename(active.id, title);
    setEditing(false);
  }

  function remove(id: string) {
    setConfirming(null);
    onDelete?.(id);
    // The row leaves the list on the next load; Recently deleted grows by one.
    window.setTimeout(() => void loadDeleted(), 250);
  }

  async function restore(id: string) {
    const result = await api.post(`/api/chat-trash/${encodeURIComponent(id)}/restore`, {});
    if (result.ok) {
      onRestored?.();
      await loadDeleted();
    }
  }

  async function forget(id: string) {
    const result = await api.del(`/api/chat-trash/${encodeURIComponent(id)}`);
    if (result.ok) await loadDeleted();
  }

  function onMenuKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((i) => Math.min(shown.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((i) => Math.max(0, i - 1)); }
    else if (e.key === "Enter" && shown[cursor]) { e.preventDefault(); choose(shown[cursor].id); }
    else if ((e.key === "Delete" || e.key === "Backspace") && shown[cursor] && onDelete) {
      e.preventDefault();
      const id = shown[cursor].id;
      if (confirming === id) remove(id); else setConfirming(id);
    } else if (e.key === "Escape") {
      e.preventDefault();
      if (confirming) { setConfirming(null); return; }
      setOpen(false);
      buttonRef.current?.focus();
    }
  }

  if (editing) {
    return (
      <div className="chat-switcher">
        <input
          className="chat-switcher__rename"
          value={draft}
          autoFocus
          maxLength={80}
          aria-label="Chat name"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); commitRename(); }
            if (e.key === "Escape") { e.preventDefault(); setEditing(false); }
          }}
          onBlur={commitRename}
        />
      </div>
    );
  }

  return (
    <div className="chat-switcher">
      <button
        ref={buttonRef}
        className="chat-switcher__button"
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Switch conversation"
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => { if (e.key === "ArrowDown" && !open) { e.preventDefault(); setOpen(true); } }}
      >
        {runningByChat[activeId] && <Spinner className="nyx-spinner--xs" />}
        <span className="chat-switcher__title">{activeTitle}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
      </button>
      <button
        className="chat-switcher__edit"
        aria-label={`Rename “${activeTitle}”`}
        title="Rename this chat"
        disabled={!active}
        onClick={() => { setDraft(activeTitle); setEditing(true); }}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>
      </button>
      {onDelete && (
        confirming === activeId ? (
          <span className="chat-switcher__confirm" role="alertdialog" aria-label={`Delete “${activeTitle}”?`}>
            <button className="chat-switcher__confirm-go" autoFocus onClick={() => remove(activeId)}>Delete</button>
            <button className="chat-switcher__confirm-no" onClick={() => setConfirming(null)}>Keep</button>
          </span>
        ) : (
          <button
            className="chat-switcher__edit is-danger"
            aria-label={`Delete “${activeTitle}”`}
            title="Delete this chat (it stays in Recently deleted)"
            disabled={!active}
            onClick={() => setConfirming(activeId)}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M6 6l1 14h10l1-14" /></svg>
          </button>
        )
      )}

      {open && (
        <div ref={menuRef} className="chat-switcher__menu" onKeyDown={onMenuKey}>
          {chats.length > 7 && (
            <input
              className="chat-switcher__search"
              placeholder="Find a chat"
              aria-label="Find a chat"
              autoFocus
              value={query}
              onChange={(e) => { setQuery(e.target.value); setCursor(0); }}
            />
          )}
          <div role="listbox" aria-label="Conversations" tabIndex={chats.length > 7 ? -1 : 0} ref={(el) => { if (el && chats.length <= 7) el.focus(); }}>
            {shown.length === 0 && <div className="chat-switcher__empty">No chat matches “{query}”.</div>}
            {shown.map((chat, index) => {
              const selected = chat.id === activeId;
              return (
                <div
                  key={chat.id}
                  role="option"
                  aria-selected={selected}
                  data-index={index}
                  className={`chat-switcher__row${index === cursor ? " is-cursor" : ""}`}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => choose(chat.id)}
                >
                  <span className="chat-switcher__check" aria-hidden="true">{selected ? "✓" : ""}</span>
                  <span className="chat-switcher__name">{chat.title || "Untitled chat"}</span>
                  {confirming === chat.id ? (
                    <span className="chat-switcher__confirm" onClick={(e) => e.stopPropagation()}>
                      <button className="chat-switcher__confirm-go" autoFocus
                        onClick={(e) => { e.stopPropagation(); remove(chat.id); }}>Delete</button>
                      <button className="chat-switcher__confirm-no"
                        onClick={(e) => { e.stopPropagation(); setConfirming(null); }}>Keep</button>
                    </span>
                  ) : (
                    <>
                      {runningByChat[chat.id] ? (
                        <span className="chat-switcher__meta"><Spinner className="nyx-spinner--xs" /> working</span>
                      ) : typeof chat.messageCount === "number" ? (
                        <span className="chat-switcher__meta">{chat.messageCount}</span>
                      ) : null}
                      {onDelete && (
                        <button
                          className="chat-switcher__kill"
                          aria-label={`Delete “${chat.title || "Untitled chat"}”`}
                          title="Delete this chat"
                          onClick={(e) => { e.stopPropagation(); setConfirming(chat.id); }}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M6 6l1 14h10l1-14" /></svg>
                        </button>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>
          {deleted.length > 0 && (
            <div className="chat-switcher__deleted">
              <button
                className="chat-switcher__deleted-head"
                aria-expanded={showDeleted}
                onClick={(e) => { e.stopPropagation(); setShowDeleted((v) => !v); }}
              >
                <span>Recently deleted</span>
                <span className="chat-switcher__meta">{deleted.length}</span>
              </button>
              {showDeleted && deleted.map((item) => (
                <div key={item.id} className="chat-switcher__row is-deleted">
                  <span className="chat-switcher__name" title={item.title}>{item.title || "Untitled chat"}</span>
                  <button className="chat-switcher__inline" onClick={(e) => { e.stopPropagation(); void restore(item.id); }}>
                    Restore
                  </button>
                  <button className="chat-switcher__inline is-danger" onClick={(e) => { e.stopPropagation(); void forget(item.id); }}>
                    Delete forever
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
