/** The world chat: what the owner says to the world government, and what comes back (U41's "first" box).
 *
 * The conversation itself is the backing office's main chat — the government is its top manager — so the owner
 * reads exactly what the office reads. What the owner types goes to the world (``/say``): mid-project it reaches the
 * government at once, between projects it becomes the next project, and on a world that is not running it starts it.
 */

import { useEffect, useRef, useState } from "react";
import { Markdown } from "../../components/chat/Markdown";
import type { OfficeMessage } from "../office/types";
import { when } from "./format";

export function WorldChat({ messages, government, queued, running, thinking, onSend, sending }: {
  messages: OfficeMessage[];
  government: string;
  queued: string[];
  running: boolean;
  thinking: boolean;
  onSend: (text: string) => Promise<void> | void;
  sending: boolean;
}) {
  const [text, setText] = useState("");
  const list = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

  const send = async () => {
    const body = text.trim();
    if (!body || sending) return;
    setText("");
    await onSend(body);
  };

  return (
    <section className="ofc-chat wld-chat" aria-label={`Chat with ${government}`}>
      <header className="ofc-chat__head">
        <h2>World chat</h2>
        <span className="ofc-chat__sub">Goes to the {government}, and down to everyone.</span>
      </header>
      <div className="ofc-chat__list" ref={list}>
        {messages.length === 0 && (
          <div className="ofc-chat__empty">
            <p>Tell the world what to work toward.</p>
            <p className="ofc-muted">
              Say how long, too — “Build a recipe site with a weekly plan, work on it for 2 days”. The government
              turns it into projects, and the planet grows as its AIs deliver them.
            </p>
          </div>
        )}
        {messages.map((message) => (
          <article key={message.id} className={`ofc-msg${message.by === "owner" ? " is-owner" : ""}`}>
            <header>
              <b>{message.by_name}</b>
              <time>{when(message.ts)}</time>
            </header>
            {message.by === "owner"
              ? <p className="ofc-msg__plain">{message.text}</p>
              : <Markdown text={message.by === "world" ? firstLines(message.text) : message.text} />}
          </article>
        ))}
        {thinking && <p className="ofc-muted wld-thinking"><i aria-hidden="true" />The government is deciding the next project…</p>}
      </div>
      {queued.length > 0 && (
        <ul className="wld-queued" aria-label="Waiting for the next project">
          {queued.map((item, index) => <li key={index}>⏳ {item}</li>)}
        </ul>
      )}
      <div className="ofc-compose">
        <textarea value={text} rows={3}
                  placeholder={running ? "Say anything — commands go to everyone…" : "What should this world work toward?"}
                  onChange={(event) => setText(event.currentTarget.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send();
                  }} />
        <div className="ofc-compose__row">
          <span className="ofc-muted">Ctrl/⌘ + Enter sends</span>
          <button type="button" className="ofc-btn ofc-btn--primary" onClick={() => void send()}
                  disabled={!text.trim() || sending}>
            {sending ? "Sending…" : running ? "Tell the world" : "Start with this"}
          </button>
        </div>
      </div>
    </section>
  );
}

/** A government brief is long (laws, decisions, time left); the chat shows its head, the Timeline keeps the rest. */
function firstLines(text: string): string {
  const lines = text.split("\n");
  return lines.length > 8 ? `${lines.slice(0, 8).join("\n")}\n\n*…the full brief went to the office.*` : text;
}
