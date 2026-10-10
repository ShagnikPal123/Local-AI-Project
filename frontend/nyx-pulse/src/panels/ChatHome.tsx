/** Chat — the home screen (redesign 2026-10-10).
 *
 * The owner: chat is home; Game Studio, drawing and the Second Brain are things the chat does, not tabs to travel to;
 * screen sharing is "a choice in there". So this is the chat with a pane of windows beside it (ChatWindows), docked
 * wherever the owner put it. The Chat/Second Brain switch that made one tab feel like two is gone: the brain opens as
 * a window from the rail card or the + menu, and never covers the conversation again.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AvatarState } from "../components/NyxAvatar";
import { ChatWindowPane, DRAG_TYPE, openChatWindow, readDrag, useChatWindows } from "../components/windows/ChatWindows";
import { ActivityRail } from "../components/activity/ActivityRail";
import { ChatPanel } from "./ChatPanel";
import { lazy, Suspense } from "react";
import { voiceMode, onVoiceMode } from "../voice/voiceBus";
import { useStyle } from "../style/styleMix";
import { StudioHeader } from "../components/studio/StudioHeader";
import { StudioSide } from "../components/studio/StudioSide";
const VoiceStage = lazy(() => import("../components/voice/VoiceStage").then((m) => ({ default: m.VoiceStage })));

export function ChatHome({ onActivity, provider, onProvider, who, onSearch, onStatus }: {
  onActivity?: (s: AvatarState) => void;
  provider: string;
  onProvider: (provider: string) => void;
  /** Studio Glass greeting and profile card (the signed-in person; the owner when nobody signed in). */
  who?: { name: string; role: string };
  onSearch?: () => void;
  onStatus?: () => void;
}) {
  const studio = useStyle("studio");
  const person = who ?? { name: "Shagnik", role: "Owner" };
  const w = useChatWindows();
  const shell = useRef<HTMLDivElement>(null);
  const [brain, setBrain] = useState<{ memories: number; today: number } | null>(null);
  useEffect(() => {
    let alive = true;
    void api.get<{ memories: number; memories_24h: number }>("/api/brain/summary").then((r) => {
      if (alive && r.ok) setBrain({ memories: r.data.memories, today: r.data.memories_24h });
    });
    return () => { alive = false; };
  }, []);

  // The voice band (Equalize's orb) loads only when voice is on — it brings three.js with it.
  const [voiceOn, setVoiceOn] = useState(voiceMode() !== "off");
  useEffect(() => onVoiceMode((mode) => setVoiceOn(mode !== "off")), []);
  const hasWindow = w.open.length > 0;
  // What Ichos touched, on the right (owner: "show more like files used, code accessed, things done"). Remembered.
  const [railOn, setRailOn] = useState(() => { try { return localStorage.getItem("ichos.activity") !== "0"; } catch { return true; } });
  useEffect(() => { try { localStorage.setItem("ichos.activity", railOn ? "1" : "0"); } catch { /* not kept */ } }, [railOn]);
  // Room check: with a window open on a narrow screen the activity list steps aside (its tab stays) so the chat
  // keeps a readable width; it comes back by itself when there is room.
  const [width, setWidth] = useState(1600);
  useEffect(() => {
    const el = shell.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const railFits = !hasWindow || width >= 1240;
  const [peek, setPeek] = useState(false);
  const showRail = railOn && (railFits || peek);
  // Dragging something openable with no window open yet: show where to drop it.
  const [dragging, setDragging] = useState(false);
  return (
    <div ref={shell} className={`chat-shell${hasWindow ? ` is-${w.dock}` : ""}`}
      onDragEnter={(e) => { if (!hasWindow && e.dataTransfer.types.includes(DRAG_TYPE)) setDragging(true); }}
      onDragEnd={() => setDragging(false)}>
      {dragging && (
        <div className="drop-hint" onDragOver={(e) => e.preventDefault()} onDragLeave={() => setDragging(false)}
          onDrop={(e) => { const item = readDrag(e); setDragging(false); if (item) { e.preventDefault(); openChatWindow(item.kind, item.title, item.props); } }}>
          Drop to open beside the chat
        </div>
      )}
      <div className="chat-shell__chat">
        {voiceOn && <Suspense fallback={null}><VoiceStage /></Suspense>}
        <div className="chat-shell__row">
        {(() => {
          const chat = (
            <ChatPanel
              variant="home"
              onActivity={onActivity}
              provider={provider}
              onProvider={onProvider}
              brain={brain}
              onOpenBrain={() => openChatWindow("brain")}
            />
          );
          const rail = showRail ? <ActivityRail onClose={() => { if (railFits) setRailOn(false); setPeek(false); }} />
            : <button type="button" className="activity-tab" onClick={() => { setRailOn(true); setPeek(true); }}>Activity</button>;
          if (!studio) return <>{chat}{rail}</>;
          // Studio Glass (owner, 2026-10-10): greeting + vitals over the chat in one glass panel; profile, calendar
          // and the activity list ("Scheduled" in the reference) in a second panel on the right.
          return (
            <>
              <div className="studio-main">
                <StudioHeader name={person.name} onSearch={() => onSearch?.()} onBell={() => onStatus?.()} />
                {chat}
              </div>
              {showRail ? (
                <aside className="studio-side">
                  <StudioSide name={person.name} role={person.role} memories={brain?.memories} today={brain?.today} onProfile={() => onStatus?.()} />
                  {rail}
                </aside>
              ) : rail}
            </>
          );
        })()}
        </div>
      </div>
      {hasWindow && <ChatWindowPane w={w} containerRef={shell} />}
    </div>
  );
}
