/** How this chat works: Normal · Co-work · Plan (Project Null N82–N84).
 *
 * The three are genuinely different jobs, not settings, so they sit under the
 * composer where you can see which one you are in before you press Send:
 *
 *  - **Normal** — quick back and forth; it thinks out loud while it answers.
 *  - **Co-work** — it keeps working in the background while you do something else.
 *  - **Plan** — it writes the plan first and changes nothing until you approve it.
 *
 * The choice is remembered per chat, because "this chat is the one where it is
 * building something" is a property of the chat, not of the app.
 */

import { useEffect, useState } from "react";

export type ChatMode = "normal" | "cowork" | "plan";

export const MODE_LABELS: Record<ChatMode, { name: string; short: string; means: string }> = {
  normal: { name: "Normal", short: "Fast chat", means: "Quick answers. You see it think as it goes." },
  cowork: { name: "Co-work", short: "Works in the background", means: "It keeps working while you do something else, and keeps a checklist." },
  plan: { name: "Plan", short: "Plan first, then work", means: "It writes a spec, asks what it needs, and changes nothing until you approve." },
};

const KEY = "nyx.chat.mode";
const BUSY_NOTE = " It is working now — send another and it runs alongside.";

export function readMode(chatId: string): ChatMode {
  try {
    const saved = localStorage.getItem(`${KEY}.${chatId}`) as ChatMode | null;
    if (saved && saved in MODE_LABELS) return saved;
  } catch { /* private browsing: the default is fine */ }
  return "normal";
}

function rememberMode(chatId: string, mode: ChatMode): void {
  try { localStorage.setItem(`${KEY}.${chatId}`, mode); } catch { /* not worth telling anyone */ }
}

export function ModeSlider({ chatId, mode, onChange, busy }: {
  chatId: string;
  mode: ChatMode;
  onChange: (mode: ChatMode) => void;
  busy?: boolean;
}) {
  const [open, setOpen] = useState<ChatMode | null>(null);

  // Following the chat: switching chats brings that chat's mode back.
  useEffect(() => { onChange(readMode(chatId)); }, [chatId]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (next: ChatMode) => {
    rememberMode(chatId, next);
    onChange(next);
    setOpen(null);
  };

  return (
    <div className="mode-slider" role="group" aria-label="How this chat works">
      <div className="mode-slider__track" data-mode={mode}>
        {(Object.keys(MODE_LABELS) as ChatMode[]).map((key) => (
          <button
            key={key}
            type="button"
            className="mode-slider__option"
            aria-pressed={mode === key}
            aria-describedby={`mode-means-${key}`}
            onClick={() => pick(key)}
            onMouseEnter={() => setOpen(key)}
            onMouseLeave={() => setOpen(null)}
            onFocus={() => setOpen(key)}
            onBlur={() => setOpen(null)}
          >
            {MODE_LABELS[key].name}
          </button>
        ))}
      </div>
      {/* All three descriptions are laid out on top of each other and only one is shown, so
          the box is always as tall as the longest. It used to hold just the one being shown:
          hovering Plan swapped in a longer line, the row grew, the switch jumped up out from
          under the mouse, the hover ended, the row shrank back under the mouse — and it kept
          bouncing until the pointer happened to rest somewhere else. */}
      <span className="mode-slider__means">
        {(Object.keys(MODE_LABELS) as ChatMode[]).map((key) => (
          <span key={key} id={`mode-means-${key}`} data-shown={(open ?? mode) === key} aria-hidden={(open ?? mode) !== key}>
            {MODE_LABELS[key].means}
            {key === "cowork" && busy && mode === "cowork" ? BUSY_NOTE : ""}
          </span>
        ))}
      </span>
    </div>
  );
}
