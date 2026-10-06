/** ID0 + All — Big Kahuna's own chat, floating over every tab (Request S21).
 *
 * "has its own chat which is where the thinking occurs and can talk to the user even when the main chat is open. Can
 * switch on and off. Similar to a companion."
 *
 * Shows Big Kahuna's thoughts after each main-chat answer (who led, what it expects next), what it did by voice
 * (opened Gmail, filled a draft), and lets the owner talk to it directly without touching the main chat. It can read
 * its replies aloud. Hidden entirely while the mode is off.
 *
 * Update 1 (U15, owner: "the button for big kahuna is obstructive"): it used to open by itself as a 360 px window in
 * the bottom-right corner — exactly over the chat's Send button — and folded to an orb in the same spot. Now its
 * button lives in the top bar (`KahunaBarButton`), the window starts closed, opens in the bottom-left, and can be
 * dragged by its header anywhere; where it was left is remembered.
 */

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { onKahunaAll, setKahunaAll } from "../../state/kahuna";
import { speakText, stopSpeaking } from "../../voice/voicePlayer";
import { Icon } from "../chat/Icon";
import "./companion.css";

interface Entry { ts: number; role: "kahuna" | "owner"; kind: string; text: string }
interface Spot { x: number; y: number }

// --- open / closed, shared by the bar button and the window ------------------------------------------------------

const OPEN_KEY = "nyx.kahuna.window";
let windowOpen = (() => { try { return localStorage.getItem(OPEN_KEY) === "1"; } catch { return false; } })();
const openListeners = new Set<(open: boolean) => void>();

function setWindowOpen(open: boolean) {
  windowOpen = open;
  try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch { /* not kept */ }
  for (const listener of openListeners) listener(open);
}

function useWindowOpen(): boolean {
  const [open, setOpen] = useState(windowOpen);
  useEffect(() => { openListeners.add(setOpen); return () => { openListeners.delete(setOpen); }; }, []);
  return open;
}

function useKahunaAll(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => onKahunaAll(setOn), []);
  return on;
}

/** The top-bar button: only while ID0 + All is on. A dot tells the owner Big Kahuna said something new. */
export function KahunaBarButton() {
  const on = useKahunaAll();
  const open = useWindowOpen();
  const [unread, setUnread] = useState(false);

  useEffect(() => {
    if (!on) return;
    return onWorkspaceEvent((event) => {
      if (event.type === "kahuna.companion" && !windowOpen) setUnread(true);
    });
  }, [on]);
  useEffect(() => { if (open) setUnread(false); }, [open]);

  if (!on) return null;
  return (
    <button type="button" className={`kc-bar${open ? " is-open" : ""}`} aria-expanded={open}
      onClick={() => setWindowOpen(!open)} title={open ? "Hide Big Kahuna's chat" : "Open Big Kahuna's chat"}>
      <span className="kc-dot" aria-hidden="true" />
      Big Kahuna
      {unread && <span className="kc-bar__new" aria-label="new message" />}
    </button>
  );
}

const SPOT_KEY = "nyx.kahuna.spot";

function readSpot(): Spot | null {
  try {
    const raw = JSON.parse(localStorage.getItem(SPOT_KEY) || "null") as Spot | null;
    return raw && Number.isFinite(raw.x) && Number.isFinite(raw.y) ? raw : null;
  } catch { return null; }
}

/** Keep the window on screen, whatever size the window was when it was left there. */
function clampSpot(spot: Spot, box: DOMRect | undefined): Spot {
  const width = box?.width ?? 360;
  const height = box?.height ?? 200;
  return {
    x: Math.min(Math.max(8, spot.x), Math.max(8, window.innerWidth - width - 8)),
    y: Math.min(Math.max(8, spot.y), Math.max(8, window.innerHeight - height - 8)),
  };
}

export function Companion() {
  const on = useKahunaAll();
  const open = useWindowOpen();
  const [speak, setSpeak] = useState(() => {
    try { return localStorage.getItem("nyx.kahuna.speak") === "1"; } catch { return false; }
  });
  const [entries, setEntries] = useState<Entry[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [spot, setSpot] = useState<Spot | null>(readSpot);
  const list = useRef<HTMLOListElement>(null);
  const box = useRef<HTMLElement>(null);
  const speakRef = useRef(speak);
  speakRef.current = speak;

  useEffect(() => { try { localStorage.setItem("nyx.kahuna.speak", speak ? "1" : "0"); } catch { /* not kept */ } }, [speak]);

  useEffect(() => {
    if (!on) return;
    void api.get<{ messages: Entry[] }>("/api/identity0/companion").then((result) => {
      if (result.ok) setEntries(result.data.messages);
    });
    return onWorkspaceEvent((event) => {
      if (event.type !== "kahuna.companion") return;
      const entry = (event as unknown as { message?: Entry }).message;
      if (!entry) return;
      setEntries((current) => [...current.slice(-199), entry]);
      if (speakRef.current && entry.role === "kahuna" && entry.kind !== "thought") {
        void speakText(entry.text, { role: "reply" }).catch(() => undefined);
      }
    });
  }, [on]);

  useEffect(() => {
    list.current?.lastElementChild?.scrollIntoView({ block: "end" });
  }, [entries.length, open]);

  if (!on || !open) return null;

  const ask = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setBusy(true);
    setError("");
    const result = await api.post("/api/identity0/companion/ask", { text }, 120000);
    setBusy(false);
    if (!result.ok) setError(result.error);
  };

  // Drag by the header. Pointer capture keeps the drag going when the pointer outruns the window.
  const startDrag = (event: ReactPointerEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest("button")) return;
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return;
    const offset = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    let last: Spot = { x: rect.left, y: rect.top };
    const move = (e: PointerEvent) => {
      last = clampSpot({ x: e.clientX - offset.x, y: e.clientY - offset.y }, rect);
      setSpot(last);
    };
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      try { localStorage.setItem(SPOT_KEY, JSON.stringify(last)); } catch { /* not kept */ }
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
  };

  const placed = spot ? clampSpot(spot, box.current?.getBoundingClientRect()) : null;

  return (
    <aside ref={box} className="kc" aria-label="Big Kahuna — ID0 + All"
      style={placed ? { left: placed.x, top: placed.y, bottom: "auto" } : undefined}>
      <header className="kc-head" onPointerDown={startDrag} title="Drag to move">
        <span className="kc-dot" aria-hidden="true" />
        <div className="kc-title"><b>Big Kahuna</b><span>ID0 + All</span></div>
        <button className={`kc-icon${speak ? " is-on" : ""}`} onClick={() => { if (speak) stopSpeaking(); setSpeak(!speak); }}
                aria-pressed={speak} aria-label={speak ? "Stop reading replies aloud" : "Read replies aloud"}>
          <Icon name="speaker" size={16} />
        </button>
        <button className="kc-icon" onClick={() => setWindowOpen(false)} aria-label="Close Big Kahuna's chat"><Icon name="close" size={16} /></button>
      </header>
      <ol className="kc-list" ref={list} aria-live="polite">
        {entries.length === 0 && <li className="kc-empty">I'm here, thinking alongside your chats. Ask me anything, or turn on
          Talk in the chat and say “open Gmail and write an email to…”.</li>}
        {entries.map((entry, index) => (
          <li key={`${entry.ts}-${index}`} className={`kc-item kc-item--${entry.role} kc-item--${entry.kind}`}>
            {entry.kind === "action" && <Icon name="bolt" size={13} />}
            {entry.kind === "thought" && <Icon name="sparkle" size={13} />}
            <span>{entry.text}</span>
          </li>
        ))}
        {busy && <li className="kc-item kc-item--kahuna kc-item--thought"><span>Thinking…</span></li>}
      </ol>
      {error && <p className="kc-error" role="alert">{error}</p>}
      <form className="kc-compose" onSubmit={(event) => { event.preventDefault(); void ask(); }}>
        <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Ask Big Kahuna…"
               aria-label="Ask Big Kahuna" />
        <button type="submit" className="kc-send" disabled={!draft.trim() || busy} aria-label="Send"><Icon name="send" size={15} /></button>
      </form>
      <button className="kc-off" onClick={() => { setWindowOpen(false); void setKahunaAll(false); }}>Turn ID0 + All off</button>
    </aside>
  );
}
