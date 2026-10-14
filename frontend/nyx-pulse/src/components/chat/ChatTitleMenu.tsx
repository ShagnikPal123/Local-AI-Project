/** The "⋯" next to the chat's name in the middle of the screen: Rename and Delete (Fixer Upper S25).
 *
 * The left list already deletes; the owner also wanted it beside the name, where the chat is open. Delete asks once
 * ("sure?") and the caller shows the Undo toast, because the chat only moves to Recently deleted for 30 days.
 * Styled with the same classes as ChatActions so the two pull-downs read as a pair.
 */

import { useEffect, useRef, useState } from "react";

interface Props {
  chatId: string;
  title: string;
  /** The new name, already trimmed and different from the old one. */
  onRename: (chatId: string, title: string) => void;
  onDelete: (chatId: string) => void;
  disabled?: boolean;
}

export function ChatTitleMenu({ chatId, title, onRename, onDelete, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [sure, setSure] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(title);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) { setSure(false); setRenaming(false); return; }
    menuRef.current?.focus();
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node) && !buttonRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div className="chat-actions-menu">
      <button ref={buttonRef} className="chat-switcher__edit" aria-haspopup="menu" aria-expanded={open}
        aria-label={`Actions for ${title}`} title="Rename or delete this chat" disabled={disabled} onClick={() => setOpen((v) => !v)}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" /></svg>
      </button>
      {open && (
        <div ref={menuRef} role="menu" tabIndex={-1} className="chat-switcher__menu chat-actions-menu__list"
          onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); setOpen(false); buttonRef.current?.focus(); } }}>
          {renaming ? (
            <form className="chat-switcher__row" onSubmit={(e) => {
              e.preventDefault();
              const next = draft.trim();
              setOpen(false);
              if (next && next !== title) onRename(chatId, next);
            }}>
              <input autoFocus value={draft} maxLength={80} aria-label="New chat name" onChange={(e) => setDraft(e.target.value)} />
            </form>
          ) : (
            <div role="menuitem" className="chat-switcher__row" onClick={() => { setDraft(title); setRenaming(true); }}>
              <span className="chat-switcher__name">Rename</span>
            </div>
          )}
          {sure ? (
            <div role="menuitem" className="chat-switcher__row is-risk" onClick={() => { setOpen(false); onDelete(chatId); }}>
              <span className="chat-switcher__name">Delete: sure?</span>
              <span className="chat-switcher__meta">Restorable for 30 days</span>
            </div>
          ) : (
            <div role="menuitem" className="chat-switcher__row is-risk" onClick={() => setSure(true)}>
              <span className="chat-switcher__name">Delete</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
