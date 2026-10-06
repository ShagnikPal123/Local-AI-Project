/** How this chat works: Normal · Co-work · Plan · Swarm · Auto (Project Null N82–N84, Update 1 U5/U6).
 *
 * They are genuinely different jobs, not settings, so they sit under the
 * composer where you can see which one you are in before you press Send:
 *
 *  - **Normal** — quick back and forth; it thinks out loud while it answers.
 *  - **Co-work** — it keeps working in the background while you do something else.
 *  - **Plan** — it writes the plan first and changes nothing until you approve it.
 *  - **Swarm** — many agents at once, as many as the slider beside it allows (and the PC can carry).
 *  - **Auto** — picks one of the four for each message and says which, and why.
 *
 * The choice is remembered per chat, because "this chat is the one where it is
 * building something" is a property of the chat, not of the app. The swarm size is
 * one setting for the whole app (it is about the machine, not the chat).
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../../api";

export type ChatMode = "normal" | "cowork" | "plan" | "swarm" | "auto";

export const MODE_LABELS: Record<ChatMode, { name: string; short: string; means: string }> = {
  normal: { name: "Normal", short: "Fast chat", means: "Quick answers. You see it think as it goes." },
  cowork: { name: "Co-work", short: "Works in the background", means: "It keeps working while you do something else, and keeps a checklist." },
  plan: { name: "Plan", short: "Plan first, then work", means: "It writes a spec, asks what it needs, and changes nothing until you approve." },
  swarm: { name: "Swarm", short: "Many agents at once", means: "It splits the job across many agents working side by side, then merges what they did." },
  auto: { name: "Auto", short: "Picks for you", means: "It picks Normal, Co-work, Plan or Swarm for each message, and tells you which." },
};

const KEY = "nyx.chat.mode";
const BUSY_NOTE = " It is working now — send another and it runs alongside.";

interface SwarmState { size: number; min: number; ceiling: number; parallel: number; reason: string; summary: string }

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

/** The swarm's size: the owner's limit, never past what this PC can carry (swarm.py clamps it too). */
function SwarmSize() {
  const [state, setState] = useState<SwarmState | null>(null);
  const [draft, setDraft] = useState<number | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    void api.get<SwarmState>("/api/swarm").then((result) => { if (alive && result.ok) setState(result.data); });
    return () => { alive = false; window.clearTimeout(timer.current); };
  }, []);

  if (!state) return null;
  const size = draft ?? state.size;

  const change = (next: number) => {
    setDraft(next);
    // Saved once the thumb settles, not on every pixel of the drag.
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      const result = await api.post<SwarmState>("/api/swarm", { size: next });
      if (result.ok) { setState(result.data); setDraft(null); }
    }, 350);
  };

  return (
    <label className="mode-slider__swarm" title={state.reason}>
      <span>Agents</span>
      <input type="range" min={state.min} max={state.ceiling} step={1} value={size} aria-label="Swarm size: how many agents"
        aria-valuetext={`${size} agents, at most ${state.ceiling} on this PC`}
        onChange={(e) => change(Number(e.target.value))} />
      <b aria-hidden="true">{size}</b>
      <span className="mode-slider__swarm-note">of {state.ceiling} · {Math.min(size, state.parallel)} at a time</span>
    </label>
  );
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
      {/* Only after a click, never on hover: a control appearing under the pointer would move the row. */}
      {mode === "swarm" && <SwarmSize />}
      {/* Every description is laid out on top of the others and only one is shown, so
          the box is always as tall as the longest. It used to hold just the one being shown:
          hovering Plan swapped in a longer line, the row grew, the switch jumped up out from
          under the mouse, the hover ended, the row shrank back under the mouse — and it kept
          bouncing until the pointer happened to rest somewhere else. */}
      <span className="mode-slider__means">
        {(Object.keys(MODE_LABELS) as ChatMode[]).map((key) => (
          <span key={key} id={`mode-means-${key}`} data-shown={(open ?? mode) === key} aria-hidden={(open ?? mode) !== key}>
            {MODE_LABELS[key].means}
            {(key === "cowork" || key === "swarm") && busy && mode === key ? BUSY_NOTE : ""}
          </span>
        ))}
      </span>
    </div>
  );
}
