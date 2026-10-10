/** The transcript: user and assistant bubbles in order, pinned to the newest.
 *
 * Auto-scroll follows the stream only while the reader is already at the
 * bottom — scrolled up to read something means scroll position is theirs, not
 * the stream's. The empty state offers real first prompts and says the thing
 * the owner asked to be obvious: agents are created in chat.
 */

import { useEffect, useRef, useState } from "react";
import type { MessageListProps } from "./types";
import { MessageBubble } from "./MessageBubble";
import { OrbHero } from "../orbs/OrbHero";

const SUGGESTIONS = [
  "What can you do on this computer?",
  "Search the web for the latest AI news and summarise it",
  "Make me a tab that tracks my daily tasks",
  "What are my PC specs?",
];

export function MessageList({ messages, onAction, emptyState }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  // Track whether the reader is at the bottom, so streaming never yanks them.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
      setPinned(gap < 48);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Follow the newest content only while pinned. Content changes, not just
  // message count, so answer deltas keep the view pinned too.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinned) el.scrollTop = el.scrollHeight;
  });

  const suggestions = emptyState?.suggestions ?? SUGGESTIONS;

  if (messages.length === 0) {
    return (
      <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "8px 2px" }}>
        <OrbHero
          intro={"Simple questions take a fast path; anything needing tools, fresh data or code runs the full "
            + "pipeline, and the orb shows which kind of work is happening. Agents are made right here in the "
            + "chat whenever a task needs one."}
          suggestions={suggestions}
          onSuggestion={(s) => emptyState?.onSuggestion(s)}
        />
      </div>
    );
  }

  return (
    <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12, padding: "8px 2px" }}>
      {messages.map((message, index) => (
        <MessageBubble
          key={message.id}
          message={message}
          onAction={onAction}
          isLatest={index === messages.length - 1}
        />
      ))}
    </div>
  );
}
