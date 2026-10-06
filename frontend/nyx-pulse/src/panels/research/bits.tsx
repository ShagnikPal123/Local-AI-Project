/** Small pieces both Research views use: a citation as it reads in print, Copy, and a delete that asks once. */

import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "../../components/chat/Icon";
import { copyText } from "./save";

/** A formatted citation: `*venue*` in italics (the styles' own markup) and its address as a real link. */
export function CiteText({ text }: { text: string }) {
  const parts = text.split(/(\*[^*]+\*|https?:\/\/[^\s<>"]+[^\s<>".,;:)])/g);
  return (
    <>
      {parts.map((part, i) => {
        if (/^\*[^*]+\*$/.test(part)) return <em key={i}>{part.slice(1, -1)}</em>;
        if (/^https?:\/\//.test(part)) {
          return (
            <a key={i} href={part} target="_blank" rel="noopener noreferrer">
              {part}
            </a>
          );
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

/** Copy, then say so for a moment. A citation copies as plain text, without the italics markers. */
export function CopyButton({ text, label = "Copy", className = "rs-btn rs-btn--quiet" }: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");
  const timer = useRef<number | null>(null);
  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);
  return (
    <button
      type="button"
      className={className}
      onClick={() => {
        void copyText(text.replace(/\*([^*]+)\*/g, "$1")).then((ok) => {
          setState(ok ? "done" : "failed");
          if (timer.current) window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => setState("idle"), 1600);
        });
      }}
    >
      <Icon name={state === "done" ? "check" : "copy"} /> {state === "done" ? "Copied" : state === "failed" ? "Copy blocked" : label}
    </button>
  );
}

/** Deleting research cannot be undone, so the first press only arms the button; it settles back if left alone. */
export function ConfirmButton({ onConfirm, children, armed = "Delete for good?", className = "rs-btn rs-btn--quiet", title }: {
  onConfirm: () => void;
  children: ReactNode;
  armed?: string;
  className?: string;
  title?: string;
}) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!ready) return;
    const timer = window.setTimeout(() => setReady(false), 5000);
    return () => window.clearTimeout(timer);
  }, [ready]);
  return (
    <button
      type="button"
      className={`${className}${ready ? " is-armed" : ""}`}
      title={title}
      aria-label={ready ? armed : title}
      onClick={() => {
        if (ready) {
          setReady(false);
          onConfirm();
        } else setReady(true);
      }}
    >
      {ready ? armed : children}
    </button>
  );
}
