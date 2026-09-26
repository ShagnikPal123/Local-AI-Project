/** The chat data layer: sending, streaming, reattaching, stopping.
 *
 * One hook per ChatPanel mount, over the module-level turn store. The rules:
 *
 * - **Send** opens `POST /api/chat/stream` and reduces every event into the
 *   store. The turn lives on the server (a worker thread), so closing this
 *   connection never kills it — Stop is an explicit action.
 * - **Reattach**: on mount, and whenever the active chat changes, the hook
 *   asks `GET /api/chats/{id}/turn` whether a turn is already running in that
 *   chat (started here before a reload, or in another window) and, if so,
 *   follows `GET /api/turns/{id}/stream` from the beginning — the server
 *   replays compacted events, so the view catches up in one burst.
 * - **Transcript**: history comes from the server (`/api/chats/{id}/messages`)
 *   when it exists; a null result means the backend does not expose one and
 *   the caller keeps its local mirror.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { openStream } from "../stream";
import { useStore } from "../state/store";
import {
  adoptRemoteTurn,
  applyTurnEvent,
  beginLocalTurn,
  pruneTurns,
  replaceLocalTurn,
  turnById,
  turnsStore,
} from "../state/turnStore";
import type { AssistantTurn, SourceLink, TurnEvent } from "../components/chat/types";

export interface SendOptions {
  message: string;
  chatId: string;
  attachmentIds?: string[];
  /** The provider picked in the dropdown; empty lets the router decide. */
  provider?: string;
  /** Hands-free voice: the answer is read aloud, so it comes back short and spoken (Request R11). */
  voice?: boolean;
  /** The listening session, so an answer drafted while the owner spoke can be used (N90). */
  voiceSession?: string;
  /** The slider under the composer: normal | cowork | plan | plan_go (chat_modes.py). */
  mode?: string;
}

export interface UseTurnsResult {
  /** The turn running in `chatId` right now (live view), if any. */
  runningTurn: AssistantTurn | undefined;
  /** True while this panel's own send is still streaming (a new send would be ignored). */
  sending: boolean;
  send: (options: SendOptions) => Promise<void>;
  stop: (turnId: string) => Promise<void>;
  /** Server transcript for the chat, or null when the backend has none. */
  transcript: { role: "user" | "assistant"; content: string; sources?: SourceLink[] }[] | null;
  loadingTranscript: boolean;
}

const PRUNE_MS = 30_000;

function isTerminalType(type: string): boolean {
  return type === "done" || type === "error" || type === "stopped";
}

export function useTurns(chatId: string): UseTurnsResult {
  // Subscribe to the store so every reduced event re-renders this panel.
  useStore(turnsStore, (s) => Object.keys(s.turns).length + Object.keys(s.runningByChat).length);

  // Keyed by chat: after a switch, the previous chat's transcript must never be
  // handed out as the new chat's — the panel seeded a brand-new chat with it, so
  // "New chat" looked like it duplicated the current one (Request G15).
  const [loaded, setLoaded] = useState<{ chatId: string; messages: { role: "user" | "assistant"; content: string; sources?: SourceLink[] }[] | null }>({ chatId: "", messages: null });
  const [loadingFor, setLoadingFor] = useState<string | null>(null);
  const transcript = loaded.chatId === chatId ? loaded.messages : null;
  const loadingTranscript = loadingFor === chatId || loaded.chatId !== chatId;
  const [localTurnId, setLocalTurnId] = useState<string | null>(null);
  // The last turn this panel sent. Cleared-on-finish ids raced the "done" render, and a turn
  // whose finish was never folded disappeared, bubble and all (Request H9).
  const [lastTurnId, setLastTurnId] = useState<string | null>(null);

  // The turn this panel is attached to: the local one it sent, or the remote
  // one it adopted for this chat.
  const runningByChat = useStore(turnsStore, (s) =>
    chatId ? s.runningByChat[chatId] : undefined,
  );
  const remoteTurnId = runningByChat ?? null;
  // A turn this panel sent stays with its own chat: after switching to another
  // chat (a branch made mid-answer) the old turn must not show up in the new one.
  const localChat = useStore(turnsStore, (s) => (localTurnId ? s.turns[localTurnId]?.chatId : undefined));
  const ownLocal = localTurnId && (!localChat || localChat === chatId) ? localTurnId : null;
  const lastChat = useStore(turnsStore, (s) => (lastTurnId ? s.turns[lastTurnId]?.chatId : undefined));
  const lastForChat = lastTurnId && lastChat === chatId ? lastTurnId : null;
  const turnId = ownLocal ?? remoteTurnId ?? lastForChat;
  const runningTurn = useStore(turnsStore, (s) => (turnId ? s.turns[turnId] : undefined));

  // Periodic pruning so a long session does not accumulate turns forever.
  useEffect(() => {
    const id = window.setInterval(pruneTurns, PRUNE_MS);
    return () => window.clearInterval(id);
  }, []);

  const followExisting = useCallback(async (existingId: string, ownerChat: string) => {
    adoptRemoteTurn({ turn_id: existingId, chat_id: ownerChat });
    const result = await openStream<TurnEvent>(
      `/api/turns/${encodeURIComponent(existingId)}/stream?since=0`,
      {
        method: "GET",
        onEvent: (event) => applyTurnEvent(existingId, event),
      },
    );
    if (!result.ok && !result.aborted) {
      // The turn may have finished between the check and the stream; the
      // summary route still gives us its final shape.
      const summary = await api.get<{ turn: Record<string, unknown> | null }>(
        `/api/turns/${encodeURIComponent(existingId)}`,
      );
      if (summary.ok && summary.data.turn) {
        applyTurnEvent(existingId, {
          type: "done",
          turn_id: existingId,
          reply: String(summary.data.turn.reply_preview ?? ""),
        });
      }
    }
  }, []);

  // On mount and whenever the chat changes: is a turn already running here?
  useEffect(() => {
    if (!chatId) return;
    let alive = true;
    void (async () => {
      const result = await api.get<{ turn: Record<string, unknown> | null }>(
        `/api/chats/${encodeURIComponent(chatId)}/turn`,
      );
      if (!alive || !result.ok) return;
      const remoteId = result.data.turn?.turn_id;
      if (typeof remoteId === "string" && remoteId && !turnById(remoteId)?.turnId) {
        await followExisting(remoteId, chatId);
      }
    })();
    return () => {
      alive = false;
    };
  }, [chatId, followExisting]);

  // Server transcript, once per chat.
  useEffect(() => {
    if (!chatId) return;
    let alive = true;
    setLoadingFor(chatId);
    void (async () => {
      const result = await api.get<{ messages: { role: string; content: string; sources?: SourceLink[] }[] }>(
        `/api/chats/${encodeURIComponent(chatId)}/messages`,
      );
      if (!alive) return;
      setLoadingFor(null);
      if (result.ok && Array.isArray(result.data.messages)) {
        const messages = result.data.messages
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({ role: m.role as "user" | "assistant", content: String(m.content ?? ""), sources: Array.isArray(m.sources) ? m.sources : undefined }));
        setLoaded({ chatId, messages: messages.length > 0 ? messages : null });
      } else {
        setLoaded({ chatId, messages: null });
      }
    })();
    return () => {
      alive = false;
    };
  }, [chatId]);

  const send = useCallback(
    async ({ message, chatId: targetChat, attachmentIds, provider, voice, voiceSession, mode }: SendOptions) => {
      if (localTurnId) return; // one turn at a time per panel
      const placeholder = beginLocalTurn(`local-${Date.now().toString(36)}`, targetChat, Date.now());
      setLocalTurnId(placeholder.turnId);

      // The real turn id arrives with turn.start; from then on events are
      // reduced under it, and the placeholder is dropped.
      let effectiveId = placeholder.turnId;
      const result = await openStream<TurnEvent>("/api/chat/stream", {
        method: "POST",
        body: {
          message,
          chat_id: targetChat || undefined,
          attachments: attachmentIds ?? [],
          provider: provider || undefined,
          voice: voice || undefined,
          voice_session: voiceSession || undefined,
          mode: mode || undefined,
        },
        onEvent: (event) => {
          const realId = typeof event.turn_id === "string" ? event.turn_id : "";
          if (realId && realId !== effectiveId) {
            replaceLocalTurn(effectiveId, realId);
            effectiveId = realId;
            setLocalTurnId(realId);
            setLastTurnId(realId);
          }
          applyTurnEvent(effectiveId, event);
        },
      });
      // A transport failure without events leaves the turn streaming forever
      // unless the failure is folded in as an event.
      if (!result.ok && !result.aborted) {
        applyTurnEvent(effectiveId, {
          type: "error",
          message: result.error ?? "The connection dropped.",
        });
      }
      setLocalTurnId(null);
      pruneTurns();
    },
    [localTurnId],
  );

  const stop = useCallback(async (turnIdToStop: string) => {
    await api.post("/api/chat/stop", { turn_id: turnIdToStop });
  }, []);

  return { runningTurn, send, stop, transcript, loadingTranscript, sending: localTurnId !== null };
}
