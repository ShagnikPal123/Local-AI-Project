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
import { ChatWindowPane, openChatWindow, useChatWindows } from "../components/windows/ChatWindows";
import { ChatPanel } from "./ChatPanel";
import { lazy, Suspense } from "react";
import { voiceMode, onVoiceMode } from "../voice/voiceBus";
const VoiceStage = lazy(() => import("../components/voice/VoiceStage").then((m) => ({ default: m.VoiceStage })));

export function ChatHome({ onActivity, provider, onProvider }: {
  onActivity?: (s: AvatarState) => void;
  provider: string;
  onProvider: (provider: string) => void;
}) {
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
  return (
    <div ref={shell} className={`chat-shell${hasWindow ? ` is-${w.dock}` : ""}`}>
      <div className="chat-shell__chat">
        {voiceOn && <Suspense fallback={null}><VoiceStage /></Suspense>}
        <ChatPanel
          variant="home"
          onActivity={onActivity}
          provider={provider}
          onProvider={onProvider}
          brain={brain}
          onOpenBrain={() => openChatWindow("brain")}
        />
      </div>
      {hasWindow && <ChatWindowPane w={w} containerRef={shell} />}
    </div>
  );
}
