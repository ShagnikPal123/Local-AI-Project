/** The chat list: every conversation, which one is open, which is still working.
 *
 * A chat whose turn is running elsewhere (another tab or window) shows its
 * live status here — the "chats keep running outside their window" promise,
 * visible at a glance. Rename is inline; delete asks once.
 */

import { useState } from "react";
import type { ChatSidebarProps, ChatSummaryView } from "./types";
import { Spinner } from "./AgentDisc";
import "./chat.css";

function ChatRow({
  chat,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  chat: ChatSummaryView;
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(chat.title);
  const [confirming, setConfirming] = useState(false);

  if (editing) {
    return (
      <div className="chat-row is-active" style={{ padding: "4px 6px" }}>
        <input
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              const title = draft.trim();
              if (title && title !== chat.title) onRename(title);
              setEditing(false);
            }
            if (e.key === "Escape") setEditing(false);
          }}
          onBlur={() => setEditing(false)}
          aria-label="Chat name"
          className="chat-rename"
        />
      </div>
    );
  }

  return (
    <div className={`chat-row${active ? " is-active" : ""}`}>
      <button
        onClick={onSelect}
        title={chat.status || chat.title}
        className="chat-row__select"
        aria-current={active ? "true" : undefined}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{chat.title}</span>
        {chat.running && <Spinner className="nyx-spinner--xs" />}
      </button>
      {chat.running && chat.status && <span className="chat-row__status">{chat.status}</span>}
      <button
        onClick={() => { setDraft(chat.title); setEditing(true); }}
        aria-label={`Rename ${chat.title}`}
        title="Rename"
        className="chat-row__action"
      >
        ✎
      </button>
      {confirming ? (
        <span className="chat-switcher__confirm" role="alertdialog" aria-label={`Delete ${chat.title}?`}>
          <button className="chat-switcher__confirm-go" autoFocus onClick={() => { setConfirming(false); onDelete(); }}>
            Delete
          </button>
          <button className="chat-switcher__confirm-no" onClick={() => setConfirming(false)}>Keep</button>
        </span>
      ) : (
        <button
          onClick={() => setConfirming(true)}
          aria-label={`Delete ${chat.title}`}
          title="Delete this chat (it stays in Recently deleted)"
          className="chat-row__action is-danger"
        >
          ✕
        </button>
      )}
    </div>
  );
}

export function ChatSidebar({ chats, activeId, onSelect, onNew, onRename, onDelete }: ChatSidebarProps) {
  return (
    <nav aria-label="Chats" style={{ flex: "none", maxHeight: 200, overflowY: "auto", padding: "4px 8px" }}>
      <button
        className="btn btn-secondary"
        onClick={onNew}
        style={{ width: "100%", fontSize: 12, padding: "5px 10px", marginBottom: 4 }}
      >
        + New chat
      </button>
      {chats.length === 0 && (
        <div style={{ fontSize: 11, color: "var(--color-neutral-600)", padding: "4px 0" }}>
          Your conversations will appear here.
        </div>
      )}
      {chats.map((chat) => (
        <ChatRow
          key={chat.id}
          chat={chat}
          active={chat.id === activeId}
          onSelect={() => onSelect(chat.id)}
          onRename={(title) => onRename(chat.id, title)}
          onDelete={() => onDelete(chat.id)}
        />
      ))}
    </nav>
  );
}
