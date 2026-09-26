/** The "⋯" pull-down next to the chat picker: make a chat from this one.
 *
 * A pull-down, not a pop-up: these are actions, not a choice of state
 * (pull-down-buttons.md). Each item says what the new chat will contain, so
 * Duplicate / Branch / Fork are distinguishable without trying them.
 */

import { useEffect, useRef, useState } from "react";

export type ChatMakeKind = "new" | "duplicate" | "branch" | "fork";

const ITEMS: { kind: ChatMakeKind; label: string; detail: string }[] = [
  { kind: "new", label: "New Chat", detail: "Empty" },
  { kind: "duplicate", label: "Duplicate", detail: "Exact copy of every message" },
  { kind: "branch", label: "Branch", detail: "Linked copy — go a different way" },
  { kind: "fork", label: "Fork", detail: "Linked, starts from a summary" },
];

export function ChatActions({ onMake, disabled }: { onMake: (kind: ChatMakeKind) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setCursor(0);
    menuRef.current?.focus();
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node) && !buttonRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);

  function pick(kind: ChatMakeKind) {
    setOpen(false);
    buttonRef.current?.focus();
    onMake(kind);
  }

  return (
    <div className="chat-actions-menu">
      <button
        ref={buttonRef}
        className="chat-switcher__edit"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More chat actions"
        title="New, duplicate, branch or fork"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" /></svg>
      </button>
      {open && (
        <div
          ref={menuRef}
          role="menu"
          tabIndex={-1}
          className="chat-switcher__menu chat-actions-menu__list"
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setCursor((i) => Math.min(ITEMS.length - 1, i + 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((i) => Math.max(0, i - 1)); }
            else if (e.key === "Enter") { e.preventDefault(); pick(ITEMS[cursor].kind); }
            else if (e.key === "Escape") { e.preventDefault(); setOpen(false); buttonRef.current?.focus(); }
          }}
        >
          {ITEMS.map((item, index) => (
            <div
              key={item.kind}
              role="menuitem"
              className={`chat-switcher__row${index === cursor ? " is-cursor" : ""}`}
              onMouseEnter={() => setCursor(index)}
              onClick={() => pick(item.kind)}
            >
              <span className="chat-switcher__name">{item.label}</span>
              <span className="chat-switcher__meta">{item.detail}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
