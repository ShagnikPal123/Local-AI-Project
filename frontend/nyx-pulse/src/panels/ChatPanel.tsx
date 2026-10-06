/** The chat tab — wired to the streaming turn pipeline.
 *
 * This panel owns no conversation state of its own: turns live in the module
 * turn store (they survive tab switches), and finished transcripts live in a
 * module map seeded from the server (`/api/chats/{id}/messages`). A tab switch
 * is a remount over the same data; a reload reattaches to any turn still
 * running and re-reads the transcript from the engine.
 *
 * The provider dropdown sits with the composer because that is the moment the
 * choice matters: it applies to the next message, not retroactively.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type UploadRecord,
} from "../api";
import { uploadChecked, useFileTarget } from "../files/fileIntake";
import { AUTO_PROVIDER, ProviderPicker } from "../components/ProviderPicker";
import { PanelShell } from "../components/Panel";
import { AgentProperties } from "../components/AgentProperties";
import { AgentDetails } from "../components/AgentDetails";
import { DispatchCard, DispatchSheet, useRoster, type DispatchView } from "../components/agents/AgentBoxes";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { DiagramOverlay, type Diagram } from "../components/diagram/DiagramOverlay";
import { ActiveTalkBar, activeTalkSupported, useActiveTalk, VoiceSwitch } from "../components/chat/ActiveTalk";
import { onVoiceMode, setVoiceMode, voiceMode, type VoiceMode } from "../voice/voiceBus";
import { UsageBar } from "../components/UsageBar";
import { ContextBar } from "../components/chat/ContextBar";
import { ModeSlider, readMode, type ChatMode } from "../components/chat/ModeSlider";
import { ChatRail, type RailMakeKind } from "../components/chat/ChatRail";
import type { AvatarState } from "../components/NyxAvatar";
import {
  AgentDock,
  ChatActions,
  ChatSidebar,
  ChatSwitcher,
  type ChatMakeKind,
  Composer,
  MessageList,
  Toasts,
  type MessageAction,
} from "../components/chat";
import type {
  AttachmentRef,
  ChatMessageView,
  ChatSummaryView,
  PendingAttachment,
  TeamAgentView,
} from "../components/chat/types";
import { copyToClipboard } from "../components/chat/hooks";
import { useTurns } from "../hooks/useTurns";
import { openStream } from "../stream";
import type { CommandSuggestion, SlashCommand, SlashHandlers } from "../components/chat/SlashMenu";
import type { BusyMode } from "../components/chat/types";
import { pushToast, useToasts, dismissToast } from "../state/toastStore";
import { useStore } from "../state/store";
import { turnsStore, turnById } from "../state/turnStore";
import { uid } from "../state/store";

/** Finished conversations, per chat, outliving every remount. */
const transcripts = new Map<string, ChatMessageView[]>();
const ACTIVE_CHAT_KEY = "nyx.chat.active";

let counter = 0;
function nextId(): string {
  counter += 1;
  return `m${Date.now().toString(36)}-${counter}`;
}

export function ChatPanel({
  onActivity,
  provider,
  onProvider,
  variant = "full",
  onSent,
  brain,
  onOpenBrain,
}: {
  onActivity?: (s: AvatarState) => void;
  provider: string;
  onProvider: (provider: string) => void;
  /** "sheet": the compact layout that floats over the brain on the Nyx tab.
   *  "home": chats down the left and the conversation in the middle, like Claude (Update 1, U48). */
  variant?: "full" | "sheet" | "home";
  /** Called with the text of every message sent (the brain pulses the predicted cluster). */
  onSent?: (text: string) => void;
  /** "home" only: the Second Brain at a glance in the rail, and how to open it. */
  brain?: { memories: number; today: number } | null;
  onOpenBrain?: () => void;
}) {
  // Reopen the chat you were in. "default" is only a first-visit placeholder;
  // the server answers it with its active chat and the panel adopts the real id.
  const [activeChatId, setActiveChatId] = useState<string>(() => {
    try {
      return localStorage.getItem(ACTIVE_CHAT_KEY) || "default";
    } catch {
      return "default";
    }
  });
  useEffect(() => {
    try {
      if (activeChatId !== "default") localStorage.setItem(ACTIVE_CHAT_KEY, activeChatId);
    } catch {
      /* private browsing: the choice simply will not persist */
    }
  }, [activeChatId]);
  const [chats, setChats] = useState<ChatSummaryView[]>([]);
  const [draft, setDraft] = useState(() => {
    try {
      const prefill = sessionStorage.getItem("nyx.chat.prefill") ?? "";
      sessionStorage.removeItem("nyx.chat.prefill");
      return prefill;
    } catch { return ""; }
  });
  const [pending, setPending] = useState<PendingAttachment[]>([]);
  /** The slider under the composer: Normal · Co-work · Plan (Project Null N82–N84). */
  const [chatMode, setChatMode] = useState<ChatMode>("normal");
  const [dockCollapsed, setDockCollapsed] = useState(true);
  const [agentSheet, setAgentSheet] = useState<string | null>(null);
  const [teamDetails, setTeamDetails] = useState(false);
  /** Chats that belong to one agent: everything sent there is answered by them. */
  const [chatAgents, setChatAgents] = useState<Record<string, string>>({});
  /** "/coder [3] …" opens the agent boxes with this text (owner request, 2026-09-16). */
  const [dispatchText, setDispatchText] = useState<string | null>(null);
  /** Agent boxes working for this chat — started here, from the Core view, or by Nyx itself. */
  const [dispatches, setDispatches] = useState<DispatchView[]>([]);
  const roster = useRoster();
  const toasts = useToasts();

  const { runningTurn, send, stop, transcript, loadingTranscript, sending } = useTurns(activeChatId);
  const busy = Boolean(runningTurn && runningTurn.state === "streaming");

  const runningByChat = useStore(turnsStore, (s) => s.runningByChat);
  const [agents, setAgents] = useState<TeamAgentView[]>([]);

  // --- messages ---------------------------------------------------------------

  const [messages, setMessages] = useState<ChatMessageView[]>(() => transcripts.get("default") ?? []);

  const persist = useCallback((chatId: string, next: ChatMessageView[]) => {
    transcripts.set(chatId, next);
  }, []);

  // Switching chats swaps the transcript for that chat's own.
  useEffect(() => {
    setMessages(transcripts.get(activeChatId) ?? []);
  }, [activeChatId]);

  // A new chat's first turn names its real chat at turn.start: move there right away,
  // not only when the answer is done, so nothing can switch the view out from under it.
  useEffect(() => {
    const realChat = runningTurn?.chatId;
    if (activeChatId !== "default" || !realChat || realChat === "default") return;
    if (!transcripts.has(realChat)) transcripts.set(realChat, transcripts.get("default") ?? []);
    setActiveChatId(realChat);
  }, [runningTurn?.chatId, activeChatId]);

  // Server transcript for this chat (or null: the backend keeps per-service
  // history; a null is "nothing more than you already see", not an error).
  useEffect(() => {
    if (transcript === null || loadingTranscript) return;
    setMessages((current) => {
      // The server knows more than this view (an answer finished while another chat was
      // open): take the server's copy instead of keeping a transcript without it (H9).
      const shown = current.filter((m) => m.role === "user" || m.role === "assistant").length;
      if (current.length > 0 && transcript.length > shown && !turnsStore.get().runningByChat[activeChatId]) {
        const refreshed: ChatMessageView[] = transcript.map((m) => ({ id: nextId(), role: m.role, content: m.content, sources: m.sources }));
        persist(activeChatId, refreshed);
        return refreshed;
      }
      if (current.length > 0) return current;
      const seeded: ChatMessageView[] = transcript.map((m) => ({
        id: nextId(),
        role: m.role,
        content: m.content,
        sources: m.sources,
      }));
      persist(activeChatId, seeded);
      return seeded;
    });
  }, [transcript, loadingTranscript, activeChatId, persist]);

  // Fold a finished turn into the transcript exactly once.
  const foldedRef = useRef<string | null>(null);
  useEffect(() => {
    const turn = runningTurn;
    if (!turn || turn.state === "streaming") return;
    if (foldedRef.current === turn.turnId) return;
    foldedRef.current = turn.turnId;
    setMessages((current) => {
      if (current.some((m) => m.id === `turn:${turn.turnId}`)) return current;
      const next: ChatMessageView[] = [
        ...current,
        {
          id: `turn:${turn.turnId}`,
          role: turn.state === "error" ? "error" : "assistant",
          content: turn.answer || turn.error || "",
          turn,
          provider: turn.provider,
          createdAt: turn.startedAt,
        },
      ];
      persist(turn.chatId || activeChatId, next);
      return next;
    });
    // A first message sent from the "default" placeholder lands in a real chat;
    // follow it so a reload reopens this conversation.
    if (activeChatId === "default" && turn.chatId && turn.chatId !== "default") {
      transcripts.set(turn.chatId, transcripts.get("default") ?? []);
      setActiveChatId(turn.chatId);
    }
    onActivity?.(turn.state === "error" ? "error" : "idle");
  }, [runningTurn, activeChatId, onActivity, persist]);

  // The turn that is still running is shown as it happens — status, thinking,
  // steps, agents and the answer as it streams. Only finished turns are folded
  // into the stored transcript above; until then the live view is appended here.
  const visibleMessages = useMemo<ChatMessageView[]>(() => {
    const turn = runningTurn;
    if (!turn || turn.state !== "streaming") return messages;
    if (messages.some((m) => m.id === `turn:${turn.turnId}`)) return messages;
    return [
      ...messages,
      {
        id: `turn:${turn.turnId}`,
        role: "assistant",
        content: turn.answer,
        turn,
        provider: turn.provider,
        createdAt: turn.startedAt,
      },
    ];
  }, [messages, runningTurn]);

  // Avatar reflects the live turn while it runs.
  useEffect(() => {
    if (busy) onActivity?.("thinking");
  }, [busy, onActivity]);

  // A sub-agent's own chat, opened from the Sub-agents tab (owner request, 2026-09-15).
  useEffect(() => {
    const onOpen = (event: Event) => {
      const chatId = (event as CustomEvent<{ chatId?: string }>).detail?.chatId;
      if (chatId) { setActiveChatId(chatId); void loadChats(); }
    };
    window.addEventListener("nyx:open-chat", onOpen);
    try {
      const pending = sessionStorage.getItem("nyx.chat.open");
      if (pending) { sessionStorage.removeItem("nyx.chat.open"); setActiveChatId(pending); }
    } catch { /* not available in private windows */ }
    return () => window.removeEventListener("nyx:open-chat", onOpen);
    // loadChats is declared below and is stable enough for this listener.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Agent boxes for this chat, and the results they write into it when they finish.
  useEffect(() => {
    let alive = true;
    setDispatches([]);
    if (activeChatId !== "default") {
      void api.get<{ dispatches: DispatchView[] }>(`/api/dispatch?chat_id=${encodeURIComponent(activeChatId)}`).then((result) => {
        if (alive && result.ok) setDispatches(result.data.dispatches.filter((d) => d.status === "running" || Date.now() / 1000 - d.created_at < 1800));
      });
    }
    const off = onWorkspaceEvent((event) => {
      if (event.type === "agents.dispatch") {
        const dispatch = event.dispatch as DispatchView | undefined;
        if (!dispatch || dispatch.chat_id !== activeChatId) return;
        setDispatches((current) => current.some((d) => d.dispatch_id === dispatch.dispatch_id) ? current : [dispatch, ...current]);
      }
      if (event.type === "chat.appended" && event.chat_id === activeChatId) {
        void api.get<{ messages: { role: "user" | "assistant"; content: string }[] }>(`/api/chats/${encodeURIComponent(activeChatId)}/messages`)
          .then((result) => {
            if (!alive || !result.ok) return;
            setMessages((current) => {
              const shown = current.filter((m) => m.role === "user" || m.role === "assistant").length;
              if (result.data.messages.length <= shown || turnsStore.get().runningByChat[activeChatId]) return current;
              const extra = result.data.messages.slice(shown).map((m) => ({ id: nextId(), role: m.role, content: m.content }));
              const next = [...current, ...extra];
              persist(activeChatId, next);
              return next;
            });
          });
      }
    });
    return () => { alive = false; off(); };
  }, [activeChatId, persist]);

  // Python boxes (Request H10) draft "Explain this…" into the composer.
  useEffect(() => {
    const onCompose = (event: Event) => {
      const text = (event as CustomEvent<{ text?: string }>).detail?.text;
      if (text) setDraft(text);
    };
    window.addEventListener("nyx:compose", onCompose);
    return () => window.removeEventListener("nyx:compose", onCompose);
  }, []);

  // A click on a question card, or Approve on a plan, sends its answer as a
  // message (Project Null N84/N85). The plan carries its own mode so the
  // approved turn is the one allowed to act.
  useEffect(() => {
    const onCardSend = (event: Event) => {
      const detail = (event as CustomEvent<{ text?: string; mode?: string }>).detail;
      const text = detail?.text?.trim();
      if (text) void doSendRef.current(text, [], detail?.mode);
    };
    window.addEventListener("nyx:chat-send", onCardSend);
    return () => window.removeEventListener("nyx:chat-send", onCardSend);
  }, []);

  const handBack = useCallback(async () => {
    const result = await api.post(`/api/chats/${encodeURIComponent(activeChatId)}/agent`, { agent: "" });
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setChatAgents((current) => { const next = { ...current }; delete next[activeChatId]; return next; });
    pushToast("The Manager answers here again.", "ok");
  }, [activeChatId]);

  // --- chat list ----------------------------------------------------------------

  const loadChats = useCallback(async () => {
    const result = await api.get<{ active?: string | null; chats: { id: string; title: string; message_count?: number; updated_at?: number | string; agent?: string; parent_id?: string | null; kind?: string }[] }>(
      "/api/chats/summaries",
    );
    if (!result.ok) return;
    const known = new Set(result.data.chats.map((c) => c.id));
    setActiveChatId((current) => {
      if (current !== "default" && known.has(current)) return current;
      // A chat whose first answer is still being written may not be listed yet.
      // Jumping to the server's "active" chat here made the bubble vanish (Request H9).
      if (current !== "default" && turnsStore.get().runningByChat[current]) return current;
      const fallback = result.data.active && known.has(result.data.active) ? result.data.active : current;
      if (fallback !== current && current === "default") {
        const placeholder = transcripts.get("default");
        if (placeholder && !transcripts.has(fallback)) transcripts.set(fallback, placeholder);
      }
      return fallback;
    });
    setChatAgents(Object.fromEntries(result.data.chats.filter((c) => c.agent).map((c) => [c.id, c.agent as string])));
    setChats(
      result.data.chats.map((c) => ({
        id: c.id,
        title: c.title,
        messageCount: c.message_count,
        updatedAt: c.updated_at,
        parentId: c.parent_id || undefined,
        kind: c.kind && c.kind !== "chat" ? c.kind : undefined,
        running: Boolean(runningByChat[c.id]),
      })),
    );
  }, [runningByChat]);

  useEffect(() => {
    void loadChats();
  }, [loadChats]);

  // --- team ------------------------------------------------------------------

  useEffect(() => {
    let alive = true;
    void (async () => {
      const result = await api.get<{ agents?: Record<string, unknown>[] }>("/api/agents");
      if (!alive || !result.ok) return;
      const rows = Array.isArray(result.data.agents) ? result.data.agents : [];
      setAgents(
        rows.map((raw) => {
          const row = raw as Record<string, unknown>;
          const status = String(row.status ?? "idle");
          return {
            agentId: String(row.agent_id ?? row.name ?? uid("agent")),
            name: String(row.name ?? "Agent"),
            emoji: typeof row.emoji === "string" && row.emoji ? row.emoji : undefined,
            color: typeof row.color === "string" && row.color ? row.color : undefined,
            status: (["idle", "working", "blocked", "error", "done"].includes(status) ? status : "idle") as TeamAgentView["status"],
            step: typeof row.current_step === "string" ? row.current_step : undefined,
            goal: typeof row.goal === "string" ? row.goal : undefined,
            role: row.role === "master" ? "master" : "worker",
            createdInChat: typeof row.created_in_chat === "string" ? row.created_in_chat : undefined,
          };
        }),
      );
    })();
    return () => {
      alive = false;
    };
  }, []);

  // --- voice (Request R11, rebuilt for Project Null N90): hands-free, and it thinks while you talk -----

  // The mode lives in the voice bus, so the chat bar, the Proto Voice dock and
  // the hands-off bar on the desktop all agree about what is listening.
  const [voice, setVoice] = useState<VoiceMode>(() => voiceMode());
  useEffect(() => onVoiceMode(setVoice), []);
  const talkOn = voice !== "off";
  const [voiceProvider, setVoiceProvider] = useState("");
  useEffect(() => {
    // Spoken answers want the quickest model in the house: the local one first, then a fast online one.
    if (!talkOn) return;
    let alive = true;
    void api.get<{ router_status?: Record<string, boolean> }>("/api/status").then((result) => {
      if (!alive || !result.ok) return;
      const router = (result.data as { service?: { router_status?: Record<string, boolean> } }).service?.router_status
        ?? result.data.router_status ?? {};
      // Big Kahuna first: on a voice turn it picks the fastest good member itself (Request S22).
      const order = ["identity0", "ollama", "groq", "nvidia", "gemini"];
      setVoiceProvider(order.find((name) => router[`${name}_available`]) ?? "");
    });
    return () => { alive = false; };
  }, [talkOn]);

  const talk = useActiveTalk({ enabled: talkOn, turn: runningTurn });

  // What the one microphone heard (VoiceListener, mounted in App) arrives here.
  useEffect(() => {
    const onVoiceSend = (event: Event) => {
      const detail = (event as CustomEvent<{ text?: string; sessionId?: string }>).detail ?? {};
      const text = (detail.text || "").trim();
      if (text) void doSendRef.current(text, [], undefined, detail.sessionId);
    };
    window.addEventListener("nyx:voice-send", onVoiceSend);
    return () => window.removeEventListener("nyx:voice-send", onVoiceSend);
  }, []);

  // --- diagrams (Request R14): the overlay Nyx opens from chat or from voice ---------

  const [diagram, setDiagram] = useState<Diagram | null>(null);

  const openDiagramById = useCallback(async (id: string) => {
    const result = await api.get<{ diagram: Diagram }>(`/api/diagram/${id}`);
    if (result.ok) setDiagram(result.data.diagram);
  }, []);

  /** `/diagram what` and `/showimage what`. Nyx's own `show_diagram` tool opens the same overlay through an event. */
  const drawDiagram = useCallback(async (request: string, picture = false) => {
    const what = request.trim();
    if (!what) { pushToast("Say what to draw, for example /diagram how you work.", "info"); return; }
    pushToast(picture ? `Finding a picture of ${what.slice(0, 40)}…` : `Drawing ${what.slice(0, 40)}…`, "info");
    const result = await api.post<{ diagram: Diagram }>("/api/diagram", { request: what, with_picture: picture }, 180_000);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setDiagram(result.data.diagram);
  }, []);

  useEffect(() => onWorkspaceEvent((event) => {
    const opened = (event as { type: string; diagram?: { id?: string } }).diagram;
    if (event.type === "diagram.open" && opened?.id) void openDiagramById(opened.id);
  }), [openDiagramById]);

  // --- attachments ----------------------------------------------------------------

  const onAttachFiles = useCallback((files: File[]) => {
    for (const file of files) {
      const localId = uid("att");
      const isImage = file.type.startsWith("image/");
      const previewUrl = isImage ? URL.createObjectURL(file) : undefined;
      setPending((current) => [
        ...current,
        { localId, name: file.name, size: file.size, mime: file.type || "application/octet-stream", status: "uploading", previewUrl },
      ]);
      void (async () => {
        // The checks run on the engine before a byte is kept; a refusal comes
        // back as the reason, and a file kept with a warning says why.
        const result = await uploadChecked(file);
        if (!result.ok) pushToast(`${file.name}: ${result.error}`, "warn");
        else if (result.caution) pushToast(`${file.name} — ${result.caution}`, "info");
        setPending((current) =>
          current.map((a) => {
            if (a.localId !== localId) return a;
            if (!result.ok || !result.record) return { ...a, status: "error", error: result.error };
            const record: UploadRecord = result.record as UploadRecord;
            return { ...a, status: "ready", uploadId: record.id };
          }),
        );
      })();
    }
  }, []);

  // Files dragged anywhere over Nyx come here while the chat is the open thing.
  useFileTarget("chat", (files) => onAttachFiles(files), { label: "the chat" });

  const removeAttachment = useCallback((localId: string) => {
    setPending((current) => {
      const target = current.find((a) => a.localId === localId);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return current.filter((a) => a.localId !== localId);
    });
  }, []);

  // --- sending ---------------------------------------------------------------------

  const doSend = useCallback(
    async (text: string, attachmentIds: string[], modeOverride?: string, voiceSession?: string) => {
      const body = text.trim();
      const userMessage: ChatMessageView = {
        id: nextId(),
        role: "user",
        content: body || "(attachment)",
        attachments: pending
          .filter((a) => a.status === "ready" && a.uploadId)
          .map<AttachmentRef>((a) => ({
            id: a.uploadId as string,
            name: a.name,
            mime: a.mime,
            kind: a.mime.startsWith("image/") ? "image" : "document",
            size: a.size,
          })),
        createdAt: Date.now(),
      };
      setMessages((current) => {
        const next = [...current, userMessage];
        persist(activeChatId, next);
        return next;
      });
      setDraft("");
      for (const attachment of pending) removeAttachment(attachment.localId);
      onSent?.(body);
      await send({ message: body || "Please look at the attached file(s).", chatId: activeChatId, attachmentIds,
                   provider: talkOn ? voiceProvider || provider : provider, voice: talkOn,
                   voiceSession, mode: modeOverride ?? chatMode });
    },
    [activeChatId, pending, persist, removeAttachment, send, onSent, provider, talkOn, voiceProvider, chatMode],
  );

  const doSendRef = useRef(doSend);
  doSendRef.current = doSend;

  const onSend = useCallback(() => {
    if (busy) return;
    const ids = pending.filter((a) => a.status === "ready" && a.uploadId).map((a) => a.uploadId as string);
    if (!draft.trim() && ids.length === 0) return;
    void doSend(draft, ids);
  }, [busy, draft, pending, doSend]);

  // --- who answers -------------------------------------------------------------------

  // The dropdown is the default provider for real: the engine is told, so a
  // switch made here and a switch made by asking ("switch to nvidia") are the
  // same thing. When the engine can't use it, say why and keep the old choice.
  const pickProvider = useCallback(
    async (next: string) => {
      const previous = provider;
      onProvider(next);
      if (!next) {
        pushToast("Auto: Nyx picks the model for each message.", "info");
        return;
      }
      const result = await api.post<{ preferred?: string }>("/api/models/switch", { model: next });
      if (!result.ok) {
        onProvider(previous);
        pushToast(result.error, "warn");
        return;
      }
      pushToast(`Switched — ${next} answers from your next message.`, "ok");
    },
    [provider, onProvider],
  );

  // What a turn changed about who answers, and chats it made: applied once per turn.
  const appliedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const turn = runningTurn;
    if (!turn?.turnId) return;
    const once = (key: string, apply: () => void) => {
      const id = `${turn.turnId}:${key}`;
      if (appliedRef.current.has(id)) return;
      appliedRef.current.add(id);
      apply();
    };
    if (turn.switchedTo) {
      const target = turn.switchedTo;
      once(`switch:${target}`, () => {
        if (target !== provider) onProvider(target);
        pushToast(`Now using ${target} — the model menu is updated.`, "ok");
      });
    }
    if (turn.fallback) {
      const { wanted, used, reason } = turn.fallback;
      once("fallback", () => {
        // Request H6: this used to move the menu to the stand-in (usually Gemini), so one
        // busy moment on the owner's model quietly made Gemini the model from then on.
        pushToast(`${wanted} couldn't answer this time (${reason}), so ${used} stood in. ${wanted} is still your pick.`, "warn");
      });
    }
    if (turn.openChat && turn.state !== "streaming") {
      const target = turn.openChat;
      once(`open:${target.chatId}`, () => {
        void loadChats().then(() => setActiveChatId(target.chatId));
      });
    }
    // loadChats is declared below; it is stable enough for this once-per-turn effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runningTurn, provider, onProvider]);

  // --- "/" commands (Request G5) --------------------------------------------------------

  const [commands, setCommands] = useState<SlashCommand[]>([]);
  const loadCommands = useCallback(async () => {
    const result = await api.get<{ commands: SlashCommand[] }>("/api/commands");
    if (result.ok) setCommands(result.data.commands);
  }, []);
  useEffect(() => { void loadCommands(); }, [loadCommands]);
  // An agent made in chat (or anywhere) is a /command at once.
  useEffect(() => onWorkspaceEvent((event) => {
    if (event.type === "agents.changed" || event.type === "agent.created" || event.type === "skills.changed") void loadCommands();
  }), [loadCommands]);

  const openSkillCreator = useCallback((text: string) => {
    setDraft("");
    try { sessionStorage.setItem("nyx.skill.draft", text); } catch { /* the creator just opens empty */ }
    window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "store" } }));
  }, []);

  // --- typing while Nyx answers (Request G12) ------------------------------------------

  const [queued, setQueued] = useState<{ id: string; text: string; attachmentIds: string[] }[]>([]);
  const [busyAdvice, setBusyAdvice] = useState<{ mode: BusyMode; reason: string; source?: string } | null>(null);
  useEffect(() => {
    if (!busy || !draft.trim() || draft.startsWith("/")) { setBusyAdvice(null); return; }
    // Co-work means "carry on alongside" — that is the whole point of the mode,
    // so it does not need to be worked out per message.
    if (chatMode === "cowork" || chatMode === "swarm") {
      const name = chatMode === "swarm" ? "Swarm" : "Co-work";
      setBusyAdvice({ mode: "parallel", reason: `${name}: this runs alongside what Nyx is already doing.`, source: "mode" });
      return;
    }
    let alive = true;
    const timer = window.setTimeout(async () => {
      const result = await api.post<{ mode: BusyMode; reason: string; source: string }>("/api/turns/advise", { text: draft, chat_id: activeChatId });
      if (alive && result.ok) setBusyAdvice(result.data);
    }, 600);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [busy, draft, activeChatId, chatMode]);

  // Queued messages go out one at a time, as soon as this chat is free again.
  useEffect(() => {
    if (busy || sending || queued.length === 0) return;
    const [next, ...rest] = queued;
    setQueued(rest);
    void doSendRef.current(next.text, next.attachmentIds);
  }, [busy, sending, queued]);

  /** Send in another chat without leaving this one; resolves once that turn has started. */
  const sendElsewhere = useCallback(
    (chatId: string, title: string, text: string, notify: boolean) =>
      new Promise<void>((resolve) => {
        let started = false;
        void openStream<{ type: string; reply?: string }>("/api/chat/stream", {
          method: "POST",
          body: { message: text, chat_id: chatId, provider: provider || undefined },
          onEvent: (event) => {
            if (!started) { started = true; resolve(); }
            if (event.type === "done" && notify) {
              pushToast(`Answer ready in “${title}”.`, "ok", { label: "Open", onClick: () => setActiveChatId(chatId) });
            }
          },
        }).then(() => { if (!started) resolve(); });
      }),
    [provider],
  );

  const onBusySend = useCallback(
    async (mode: BusyMode) => {
      const text = draft.trim();
      if (!text) return;
      const attachmentIds = pending.filter((a) => a.status === "ready" && a.uploadId).map((a) => a.uploadId as string);
      setDraft("");
      for (const attachment of pending) removeAttachment(attachment.localId);
      if (mode === "queue" || mode === "interrupt") {
        const item = { id: uid("q"), text, attachmentIds };
        setQueued((current) => (mode === "interrupt" ? [item, ...current] : [...current, item]));
        if (mode === "interrupt" && runningTurn?.turnId) {
          void stop(runningTurn.turnId);
          pushToast("Stopping the current answer — your message goes next.", "info");
        } else {
          pushToast("Queued — it sends when this answer finishes.", "info");
        }
        return;
      }
      if (activeChatId === "default") {
        setQueued((current) => [...current, { id: uid("q"), text, attachmentIds }]);
        return;
      }
      const kind = mode === "parallel" ? "fork" : "branch";
      const made = await api.post<{ chat: { id: string; title: string } }>(`/api/chats/${encodeURIComponent(activeChatId)}/${kind}`, {});
      if (!made.ok) { pushToast(made.error, "warn"); return; }
      await loadChats();
      const { id, title } = made.data.chat;
      if (mode === "parallel") {
        void sendElsewhere(id, title, text, true);
        pushToast(`Running alongside in “${title}” — this answer keeps going.`, "ok", { label: "Open", onClick: () => setActiveChatId(id) });
      } else {
        await sendElsewhere(id, title, text, false);
        const previous = activeChatId;
        setActiveChatId(id);
        pushToast(`Branched into “${title}” — the original keeps answering.`, "ok", { label: "Go back", onClick: () => setActiveChatId(previous) });
      }
    },
    [draft, pending, removeAttachment, runningTurn, stop, activeChatId, loadChats, sendElsewhere],
  );

  // --- actions -------------------------------------------------------------------

  const resendBefore = useCallback(
    (messageId: string) => {
      const index = messages.findIndex((m) => m.id === messageId);
      if (index <= 0) return;
      const previousUser = [...messages.slice(0, index)].reverse().find((m) => m.role === "user");
      if (!previousUser) return;
      void doSend(previousUser.content, []);
    },
    [messages, doSend],
  );

  const onAction = useCallback(
    (action: MessageAction) => {
      switch (action.type) {
        case "stop":
          if (runningTurn?.turnId) void stop(runningTurn.turnId);
          break;
        case "approve":
          void api.post(`/api/approvals/${encodeURIComponent(action.approvalId)}`, { approve: action.approve });
          break;
        case "feedback":
          void (async () => {
            const result = await api.post("/api/feedback", {
              turn_id: action.turnId,
              chat_id: activeChatId,
              rating: action.value,
              comment: action.comment ?? "",
            });
            pushToast(
              action.value === 1 ? "Thanks — Nyx learns from good answers." : "Noted — that answer is marked and won't be cached again.",
              action.value === 1 ? "ok" : "info",
            );
            if (!result.ok) pushToast(result.error, "warn");
          })();
          break;
        case "keepSkill":
          void (async () => {
            const result = await api.post(`/api/skills/${encodeURIComponent(action.skillId)}/keep`);
            pushToast(result.ok ? "Skill kept in your library." : result.error, result.ok ? "ok" : "warn");
          })();
          break;
        case "exportSkill":
          void (async () => {
            const result = await api.get<{ filename: string; content: string }>(
              `/api/skills/${encodeURIComponent(action.skillId)}/export?format=claude`,
            );
            if (!result.ok) {
              pushToast(result.error, "warn");
              return;
            }
            const blob = new Blob([result.data.content], { type: "text/markdown" });
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = result.data.filename;
            anchor.click();
            URL.revokeObjectURL(url);
            pushToast("Skill exported as SKILL.md (Claude format).", "ok");
          })();
          break;
        case "speak": {
          const spoken = messages.find((m) => m.id === action.messageId);
          const text = spoken?.content || "";
          if (text && "speechSynthesis" in window) {
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(text.slice(0, 1200));
            utterance.rate = 1.02;
            window.speechSynthesis.speak(utterance);
          }
          break;
        }
        case "copy":
          void (async () => {
            const target = messages.find((m) => m.id === action.messageId);
            if (target) await copyToClipboard(target.content);
          })();
          break;
        case "retry":
          resendBefore(action.messageId);
          break;
        case "branch": {
          const index = messages.findIndex((m) => m.id === action.messageId);
          const upto = messages.slice(0, index + 1).filter((m) => m.role === "user" || m.role === "assistant").length;
          void makeChatRef.current("branch", upto);
          break;
        }
        case "refreshCached":
          resendBefore(action.messageId);
          break;
        case "askAgent":
          setDraft((current) => `${current}${current && !current.endsWith(" ") ? " " : ""}@${action.name} `);
          break;
        case "openAgent":
          setAgentSheet(action.name);
          break;
        default:
          break;
      }
    },
    [activeChatId, messages, resendBefore, runningTurn, stop],
  );

  // --- chat management ---------------------------------------------------------------

  const onNewChat = useCallback(async () => {
    const result = await api.post<{ chat: { id: string; title: string } }>("/api/chats", { title: "" });
    if (!result.ok) {
      pushToast(result.error, "warn");
      return;
    }
    await loadChats();
    setActiveChatId(result.data.chat.id);
  }, [loadChats]);

  const makeChat = useCallback(
    async (kind: ChatMakeKind, upto?: number) => {
      if (kind === "new") {
        await onNewChat();
        return;
      }
      if (activeChatId === "default") {
        pushToast("Send a message first — there is nothing to copy yet.", "info");
        return;
      }
      const result = await api.post<{ chat: { id: string; title: string } }>(
        `/api/chats/${encodeURIComponent(activeChatId)}/${kind}`,
        kind === "branch" && upto !== undefined ? { upto } : {},
      );
      if (!result.ok) {
        pushToast(result.error, "warn");
        return;
      }
      const verb = kind === "duplicate" ? "Duplicated" : kind === "branch" ? "Branched" : "Forked";
      const previous = activeChatId;
      await loadChats();
      setActiveChatId(result.data.chat.id);
      pushToast(`${verb} into “${result.data.chat.title}”.`, "ok", { label: "Go back", onClick: () => setActiveChatId(previous) });
    },
    [activeChatId, loadChats, onNewChat],
  );
  const makeChatRef = useRef(makeChat);
  makeChatRef.current = makeChat;

  /** The rail's ⋯ menu: branch, semi-branch (fork) or duplicate any chat in the list, then open the new one. */
  const makeChatFrom = useCallback(async (sourceId: string, kind: RailMakeKind) => {
    const result = await api.post<{ chat: { id: string; title: string } }>(`/api/chats/${encodeURIComponent(sourceId)}/${kind}`, {});
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    const verb = kind === "duplicate" ? "Duplicated" : kind === "branch" ? "Branched" : "Semi-branched";
    const previous = activeChatId;
    await loadChats();
    setActiveChatId(result.data.chat.id);
    pushToast(`${verb} into “${result.data.chat.title}”.`, "ok", { label: "Go back", onClick: () => setActiveChatId(previous) });
  }, [activeChatId, loadChats]);

  const runCommand = useCallback(
    (command: SlashCommand, args: string) => {
      const needs = (what: string) => {
        setDraft(`/${command.name} `);
        pushToast(`Add ${what} after /${command.name}.`, "info");
      };
      setDraft("");
      if (command.kind === "agent") {
        // "/coder [3] build the login page" — show the boxes; nothing runs until Run.
        setDispatchText(`/${command.name} ${args}`.trim());
        return;
      }
      if (command.kind === "skill") {
        if (!args) { needs(command.args ?? "what to use it on"); return; }
        const text = `/${command.name} ${args}`;
        if (busy) setQueued((current) => [...current, { id: uid("q"), text, attachmentIds: [] }]);
        else void doSend(text, []);
        return;
      }
      if (command.kind !== "client") {
        const template = command.template ?? "{args}";
        if (!args && template.includes("{args}") && command.args && !/optional/.test(command.args)) { needs(command.args); return; }
        const text = template.replace("{args}", args).replace(/\s+:?\s*$/, "").trim();
        if (busy) setQueued((current) => [...current, { id: uid("q"), text, attachmentIds: [] }]);
        else void doSend(text, []);
        return;
      }
      switch (command.action) {
        case "chat.new": void onNewChatRef.current(); break;
        case "chat.duplicate": void makeChat("duplicate"); break;
        case "chat.branch": void makeChat("branch"); break;
        case "chat.fork": void makeChat("fork"); break;
        case "chat.rename":
          if (!args) { needs("the new name"); return; }
          void onRenameChatRef.current(activeChatId, args).then(() => pushToast(`Renamed to “${args}”.`, "ok"));
          break;
        case "model.switch":
          if (!args) { needs("a provider, like nvidia"); return; }
          void pickProvider(args.toLowerCase().trim());
          break;
        case "model.auto": void pickProvider(""); break;
        case "turn.stop":
          if (runningTurn?.turnId) void stop(runningTurn.turnId);
          else pushToast("Nothing is running.", "info");
          break;
        case "agent.open":
          if (!args) { setDockCollapsed(false); pushToast("Pick an agent in the Team list, or type /agent Coder.", "info"); }
          else setAgentSheet(args);
          break;
        case "tab.open": window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: args } })); break;
        case "context.compact": window.dispatchEvent(new CustomEvent("nyx:context-compact", { detail: { focus: args } })); break;
        case "skill.create": openSkillCreator(args); break;
        case "diagram.open": void drawDiagram(args); break;
        case "diagram.picture": void drawDiagram(args, true); break;
        case "help": setDraft("/"); break;
        default: pushToast(`/${command.name} is not available here.`, "warn");
      }
    },
    [busy, doSend, makeChat, activeChatId, pickProvider, runningTurn, stop, openSkillCreator, drawDiagram],
  );

  /** The diagram overlay, and what happens when its picture is sent back into the message box. */
  const diagramOverlay = diagram ? (
    <DiagramOverlay
      diagram={diagram}
      onClose={() => setDiagram(null)}
      onChanged={setDiagram}
      onInsert={(uploadId, title) => {
        setPending((current) => [...current, { localId: uid("att"), name: `${title.slice(0, 40) || "diagram"}.png`, size: 0,
                                               mime: "image/png", status: "ready", uploadId }]);
        setDraft((text) => text || `About this diagram (${title}): `);
        setDiagram(null);
      }}
    />
  ) : null;

  const createCommand = useCallback(
    async (suggestion: CommandSuggestion, args: string) => {
      const result = await api.post<{ command: SlashCommand }>("/api/commands", suggestion);
      if (!result.ok) { pushToast(result.error, "warn"); return; }
      await loadCommands();
      pushToast(`Made /${result.data.command.name} — it's in the menu from now on.`, "ok");
      runCommand(result.data.command, args);
    },
    [loadCommands, runCommand],
  );

  const slash = useMemo<SlashHandlers>(
    () => ({ commands, run: runCommand, create: (s, a) => void createCommand(s, a), openSkillCreator }),
    [commands, runCommand, createCommand, openSkillCreator],
  );

  const onNewChatRef = useRef<() => Promise<void>>(async () => {});
  const onRenameChatRef = useRef<(id: string, title: string) => Promise<void>>(async () => {});

  const onRenameChat = useCallback(
    async (chatId: string, title: string) => {
      const result = await api.patch(`/api/chats/${encodeURIComponent(chatId)}`, { title });
      if (!result.ok) {
        pushToast(result.error, "warn");
        return;
      }
      await loadChats();
    },
    [loadChats],
  );

  onNewChatRef.current = onNewChat;
  onRenameChatRef.current = onRenameChat;

  const restoreChat = useCallback(
    async (chatId: string) => {
      const result = await api.post(`/api/chat-trash/${encodeURIComponent(chatId)}/restore`, {});
      if (!result.ok) {
        pushToast(result.error, "warn");
        return;
      }
      await loadChats();
      setActiveChatId(chatId);
    },
    [loadChats],
  );

  const onDeleteChat = useCallback(
    async (chatId: string) => {
      const title = chats.find((c) => c.id === chatId)?.title || "that chat";
      const result = await api.del(`/api/chats/${encodeURIComponent(chatId)}`);
      if (!result.ok) {
        pushToast(result.error, "warn");
        return;
      }
      transcripts.delete(chatId);
      await loadChats();
      if (chatId === activeChatId) setActiveChatId("default");
      // A deleted chat waits 30 days in Recently deleted, so Undo really brings it back.
      pushToast(`Deleted “${title}”.`, "ok", { label: "Undo", onClick: () => void restoreChat(chatId) });
    },
    [activeChatId, chats, loadChats, restoreChat],
  );

  // --- render ---------------------------------------------------------------------

  // Whose limits to show: the dropdown's pick, else whoever answered last, else the engine default.
  const [engineDefault, setEngineDefault] = useState("");
  useEffect(() => {
    if (provider) return;
    void api.get<{ provider: string }>("/api/models/active").then((r) => { if (r.ok) setEngineDefault(r.data.provider); });
  }, [provider, runningTurn?.turnId]);
  const lastAnswered = [...messages].reverse().find((m) => m.role === "assistant" && m.provider && !m.provider.startsWith("cache"))?.provider ?? "";
  const usageProvider = provider || runningTurn?.provider || lastAnswered || engineDefault;
  const usageKey = runningTurn && runningTurn.state !== "streaming" ? runningTurn.turnId : undefined;

  const subtitle = busy
    ? runningTurn?.status || "Working…"
    : provider === AUTO_PROVIDER
      ? "Auto mode — speed and provider chosen per turn"
      : `Sending to ${provider}`;

  const emptyState = {
    suggestions: [
      "What can you do on this computer?",
      "Search the web for the latest AI news and summarise it",
      "Study my Documents folder and tell me what you learned",
    ],
    onSuggestion: (text: string) => {
      setDraft(text);
      void doSend(text, []);
    },
  };

  if (variant === "home") {
    const title = chats.find((c) => c.id === activeChatId)?.title || "New chat";
    return (
      <div className="chat-home">
        <ChatRail
          chats={chats}
          activeId={activeChatId}
          runningByChat={runningByChat}
          onSelect={setActiveChatId}
          onNew={() => void onNewChat()}
          onRename={(id, name) => void onRenameChat(id, name)}
          onDelete={(id) => void onDeleteChat(id)}
          onMake={(id, kind) => void makeChatFrom(id, kind)}
          onRestored={() => void loadChats()}
          brain={brain}
          onOpenBrain={onOpenBrain}
        />
        <section className="chat-home__main" aria-label={`Chat: ${title}`}>
          <header className="chat-home__head">
            <h2 className="chat-home__title" title={title}>{title}</h2>
            <ChatActions onMake={(kind) => void makeChat(kind)} />
            <span className="chat-home__spacer" />
            {activeTalkSupported() && <VoiceSwitch mode={voice} onMode={setVoice} />}
            <ProviderPicker value={provider} onChange={(next) => void pickProvider(next)} compact />
          </header>
          <div className="chat-home__meta">
            <span className="nyx-chat__status" aria-live="polite">{subtitle}</span>
            <UsageBar provider={usageProvider} refreshKey={usageKey} />
            <ContextBar chatId={activeChatId} provider={usageProvider} refreshKey={`${usageKey ?? ""}:${messages.length}`} />
          </div>
          <div className="chat-home__team">
            <AgentDock
              agents={agents}
              collapsed={dockCollapsed}
              onToggle={() => setDockCollapsed((v) => !v)}
              onAskAgent={(name) => onAction({ type: "askAgent", name })}
              onOpenAgent={(name) => onAction({ type: "openAgent", name })}
              onOpenDetails={() => setTeamDetails(true)}
            />
          </div>
          {chatAgents[activeChatId] && (
            <div className="chat-owner" role="note">
              <span>This chat belongs to <b>{chatAgents[activeChatId]}</b> — they answer here, not the Manager.</span>
              <button className="chat-inline" onClick={() => void handBack()}>Hand back to the Manager</button>
            </div>
          )}
          <div className="chat-home__column">
            <MessageList messages={visibleMessages} onAction={onAction} emptyState={emptyState} />
          </div>
          <div className="chat-home__dock">
            <ActiveTalkBar state={talk} onOff={() => setVoiceMode("off")} />
            {queued.length > 0 && (
              <div className="queued-list" aria-live="polite">
                <span className="queued-list__label">Queued</span>
                {queued.map((q) => (
                  <span key={q.id} className="chip queued-list__item" title={q.text}>
                    {q.text.slice(0, 60)}{q.text.length > 60 ? "…" : ""}
                    <button aria-label="Remove from queue" onClick={() => setQueued((c) => c.filter((x) => x.id !== q.id))}>✕</button>
                  </span>
                ))}
              </div>
            )}
            {dispatches.length > 0 && (
              <div className="dispatch-tray" aria-label="Agents working in this chat">
                {dispatches.map((d) => (
                  <DispatchCard key={d.dispatch_id} initial={d} roster={roster} compact
                    onClose={() => setDispatches((current) => current.filter((x) => x.dispatch_id !== d.dispatch_id))} />
                ))}
              </div>
            )}
            {dispatchText !== null && (
              <DispatchSheet text={dispatchText} chatId={activeChatId === "default" ? "" : activeChatId} onClose={() => setDispatchText(null)}
                onStarted={(d) => setDispatches((current) => [d, ...current.filter((x) => x.dispatch_id !== d.dispatch_id)])} />
            )}
            <Composer
              value={draft}
              onChange={setDraft}
              onSend={onSend}
              onStop={() => runningTurn?.turnId && void stop(runningTurn.turnId)}
              busy={busy}
              attachments={pending}
              onAttachFiles={onAttachFiles}
              onRemoveAttachment={removeAttachment}
              agents={agents}
              placeholder="Ask Nyx anything…  (type / for commands)"
              slash={slash}
              onBusySend={(mode) => void onBusySend(mode)}
              busyAdvice={busyAdvice}
            />
            <div className="chat-bottom-row">
              <ModeSlider chatId={activeChatId} mode={chatMode} onChange={setChatMode} busy={busy} />
            </div>
          </div>
        </section>
        {teamDetails && !agentSheet && <AgentDetails onClose={() => setTeamDetails(false)} onEdit={(name) => setAgentSheet(name)} />}
        {agentSheet && <AgentProperties name={agentSheet} onClose={() => setAgentSheet(null)} onRenamed={setAgentSheet} />}
        {diagramOverlay}
        <Toasts items={toasts} onDismiss={dismissToast} />
      </div>
    );
  }

  if (variant === "sheet") {
    return (
      <div className="nyx-chat">
        <div className="nyx-chat__bar">
          <ChatSwitcher
            chats={chats}
            activeId={activeChatId}
            runningByChat={runningByChat}
            onSelect={setActiveChatId}
            onRename={(id, title) => void onRenameChat(id, title)}
            onDelete={(id) => void onDeleteChat(id)}
            onRestored={() => void loadChats()}
          />
          <button className="btn btn-secondary" onClick={() => void onNewChat()} aria-label="New chat" title="New chat">＋</button>
          <ChatActions onMake={(kind) => void makeChat(kind)} />
          {activeTalkSupported() && <VoiceSwitch mode={voice} onMode={setVoice} />}
          <ProviderPicker value={provider} onChange={(next) => void pickProvider(next)} compact />
        </div>
        <div className="nyx-chat__status" aria-live="polite">{subtitle}</div>
        <UsageBar provider={usageProvider} refreshKey={usageKey} />
        <ContextBar chatId={activeChatId} provider={usageProvider} refreshKey={`${usageKey ?? ""}:${messages.length}`} />
        <AgentDock
          agents={agents}
          collapsed={dockCollapsed}
          onToggle={() => setDockCollapsed((v) => !v)}
          onAskAgent={(name) => onAction({ type: "askAgent", name })}
          onOpenAgent={(name) => onAction({ type: "openAgent", name })}
          onOpenDetails={() => setTeamDetails(true)}
        />
        {chatAgents[activeChatId] && (
          <div className="chat-owner" role="note">
            <span>This chat belongs to <b>{chatAgents[activeChatId]}</b> — they answer here, not the Manager.</span>
            <button className="chat-inline" onClick={() => void handBack()}>Hand back to the Manager</button>
          </div>
        )}
        <MessageList messages={visibleMessages} onAction={onAction} emptyState={emptyState} />
        <ActiveTalkBar state={talk} onOff={() => setVoiceMode("off")} />
        {queued.length > 0 && (
          <div className="queued-list" aria-live="polite">
            <span className="queued-list__label">Queued</span>
            {queued.map((q) => (
              <span key={q.id} className="chip queued-list__item" title={q.text}>
                {q.text.slice(0, 60)}{q.text.length > 60 ? "…" : ""}
                <button aria-label="Remove from queue" onClick={() => setQueued((c) => c.filter((x) => x.id !== q.id))}>✕</button>
              </span>
            ))}
          </div>
        )}
        {dispatches.length > 0 && (
          <div className="dispatch-tray" aria-label="Agents working in this chat">
            {dispatches.map((d) => (
              <DispatchCard key={d.dispatch_id} initial={d} roster={roster} compact
                onClose={() => setDispatches((current) => current.filter((x) => x.dispatch_id !== d.dispatch_id))} />
            ))}
          </div>
        )}
        {dispatchText !== null && (
          <DispatchSheet text={dispatchText} chatId={activeChatId === "default" ? "" : activeChatId} onClose={() => setDispatchText(null)}
            onStarted={(d) => setDispatches((current) => [d, ...current.filter((x) => x.dispatch_id !== d.dispatch_id)])} />
        )}
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={onSend}
          onStop={() => runningTurn?.turnId && void stop(runningTurn.turnId)}
          busy={busy}
          attachments={pending}
          onAttachFiles={onAttachFiles}
          onRemoveAttachment={removeAttachment}
          agents={agents}
          placeholder="Ask Nyx anything…  (type / for commands)"
          slash={slash}
          onBusySend={(mode) => void onBusySend(mode)}
          busyAdvice={busyAdvice}
        />
        {/* One row under the composer: how this chat works on the left.
            fc578b's <ChatToolbar /> (skills · agents · connectors) goes on the right. */}
        <div className="chat-bottom-row">
          <ModeSlider chatId={activeChatId} mode={chatMode} onChange={setChatMode} busy={busy} />
        </div>
        {teamDetails && !agentSheet && <AgentDetails onClose={() => setTeamDetails(false)} onEdit={(name) => setAgentSheet(name)} />}
        {agentSheet && <AgentProperties name={agentSheet} onClose={() => setAgentSheet(null)} onRenamed={setAgentSheet} />}
        {diagramOverlay}
        <Toasts items={toasts} onDismiss={dismissToast} />
      </div>
    );
  }

  return (
    <PanelShell title="Chat" subtitle={subtitle} actions={<ChatActions onMake={(kind) => void makeChat(kind)} />}>
      <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, gap: 10 }}>
        <ChatSidebar
          chats={chats}
          activeId={activeChatId}
          onSelect={setActiveChatId}
          onNew={() => void onNewChat()}
          onRename={(id, title) => void onRenameChat(id, title)}
          onDelete={(id) => void onDeleteChat(id)}
        />

        <AgentDock
          agents={agents}
          collapsed={dockCollapsed}
          onToggle={() => setDockCollapsed((v) => !v)}
          onAskAgent={(name) => onAction({ type: "askAgent", name })}
          onOpenAgent={(name) => onAction({ type: "openAgent", name })}
          onOpenDetails={() => setTeamDetails(true)}
        />

        {chatAgents[activeChatId] && (
          <div className="chat-owner" role="note">
            <span>This chat belongs to <b>{chatAgents[activeChatId]}</b> — they answer here, not the Manager.</span>
            <button className="chat-inline" onClick={() => void handBack()}>Hand back to the Manager</button>
          </div>
        )}
        <MessageList messages={visibleMessages} onAction={onAction} emptyState={emptyState} />
        <ActiveTalkBar state={talk} onOff={() => setVoiceMode("off")} />

        {queued.length > 0 && (
          <div className="queued-list" aria-live="polite">
            <span className="queued-list__label">Queued</span>
            {queued.map((q) => (
              <span key={q.id} className="chip queued-list__item" title={q.text}>
                {q.text.slice(0, 60)}{q.text.length > 60 ? "…" : ""}
                <button aria-label="Remove from queue" onClick={() => setQueued((c) => c.filter((x) => x.id !== q.id))}>✕</button>
              </span>
            ))}
          </div>
        )}
        {dispatches.length > 0 && (
          <div className="dispatch-tray" aria-label="Agents working in this chat">
            {dispatches.map((d) => (
              <DispatchCard key={d.dispatch_id} initial={d} roster={roster} compact
                onClose={() => setDispatches((current) => current.filter((x) => x.dispatch_id !== d.dispatch_id))} />
            ))}
          </div>
        )}
        {dispatchText !== null && (
          <DispatchSheet text={dispatchText} chatId={activeChatId === "default" ? "" : activeChatId} onClose={() => setDispatchText(null)}
            onStarted={(d) => setDispatches((current) => [d, ...current.filter((x) => x.dispatch_id !== d.dispatch_id)])} />
        )}
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={onSend}
          onStop={() => runningTurn?.turnId && void stop(runningTurn.turnId)}
          busy={busy}
          attachments={pending}
          onAttachFiles={onAttachFiles}
          onRemoveAttachment={removeAttachment}
          agents={agents}
          slash={slash}
          onBusySend={(mode) => void onBusySend(mode)}
          busyAdvice={busyAdvice}
        />
        {/* One row under the composer: how this chat works on the left.
            fc578b's <ChatToolbar /> (skills · agents · connectors) goes on the right. */}
        <div className="chat-bottom-row">
          <ModeSlider chatId={activeChatId} mode={chatMode} onChange={setChatMode} busy={busy} />
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <ProviderPicker value={provider} onChange={(next) => void pickProvider(next)} compact />
          {activeTalkSupported() && <VoiceSwitch mode={voice} onMode={setVoice} />}
        </div>
        <UsageBar provider={usageProvider} refreshKey={usageKey} />
        <ContextBar chatId={activeChatId} provider={usageProvider} refreshKey={`${usageKey ?? ""}:${messages.length}`} />

        {teamDetails && !agentSheet && <AgentDetails onClose={() => setTeamDetails(false)} onEdit={(name) => setAgentSheet(name)} />}
        {agentSheet && <AgentProperties name={agentSheet} onClose={() => setAgentSheet(null)} onRenamed={setAgentSheet} />}
        {diagramOverlay}
        <Toasts items={toasts} onDismiss={dismissToast} />
      </div>
    </PanelShell>
  );
}
