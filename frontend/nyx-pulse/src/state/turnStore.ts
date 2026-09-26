/** The turn store: everything happening in every chat, outliving every panel.
 *
 * One module-level map of turnId → AssistantTurn, plus the per-chat "which
 * turn is running" index that the chat list and the reopen-reattach flow need.
 * A tab switch unmounts ChatPanel; turns keep streaming into this store and the
 * panel re-renders from it when it comes back — the same reason App owns the
 * transcript instead of the panel. A full page reload is handled by the
 * reopen-reattach flow in useTurns (server replays events on reattach).
 *
 * The workspace SSE (`/api/events/stream`, channel "ui") publishes throttled
 * `turn.state` summaries for turns in every chat — including ones started in
 * another tab or window. Those summaries carry the fields turn_registry
 * tracks (status, reply_preview, state, tools_running, agents) and are reduced
 * into lightweight AssistantTurn views here, so any window can show that a
 * chat is still working.
 */

import { createStore, useStore } from "./store";
import { isTerminal, newTurn, reduceTurn } from "./turnReducer";
import type {
  AssistantTurn,
  ChatMessageView,
  TurnEvent,
  WorkspaceEvent,
} from "../components/chat/types";

interface TurnStoreState {
  /** turnId → live turn view. */
  turns: Record<string, AssistantTurn>;
  /** chatId → turnId of the turn currently running in that chat. */
  runningByChat: Record<string, string>;
}

const store = createStore<TurnStoreState>({ turns: {}, runningByChat: {} });

/** The raw store object, for `useStore` selectors in hooks. */
export const turnsStore = store;

export function turnById(turnId: string): AssistantTurn | undefined {
  return store.get().turns[turnId];
}

export function runningTurnForChat(chatId: string): AssistantTurn | undefined {
  const turnId = store.get().runningByChat[chatId];
  return turnId ? store.get().turns[turnId] : undefined;
}

export function useTurnForChat(chatId: string): AssistantTurn | undefined {
  return useStore(store, (s) => {
    const turnId = s.runningByChat[chatId];
    return turnId ? s.turns[turnId] : undefined;
  });
}

/** Create (or reset) the local view of a turn we are about to stream. */
export function beginLocalTurn(turnId: string, chatId: string, startedAt: number): AssistantTurn {
  const turn = newTurn(turnId, chatId, startedAt);
  store.set((s) => ({
    turns: { ...s.turns, [turnId]: turn },
    runningByChat: { ...s.runningByChat, [chatId]: turnId },
  }));
  return turn;
}

/** Apply one streamed event. Returns the updated turn, or undefined if unknown. */
export function applyTurnEvent(turnId: string, event: TurnEvent): AssistantTurn | undefined {
  const existing = store.get().turns[turnId];
  const next = reduceTurn(existing, event);
  if (next === existing) return existing;
  store.set((s) => {
    const runningByChat = { ...s.runningByChat };
    if (isTerminal(String(event.type))) {
      // Clear every chat that points at this turn, not only the one named in
      // the event: the panel may have registered it under "default" before the
      // server said which chat it really belongs to. A leftover entry kept a
      // finished turn looking like it was still "Starting", with Stop showing.
      if (next.chatId) delete runningByChat[next.chatId];
      for (const [chat, id] of Object.entries(runningByChat)) {
        if (id === turnId) delete runningByChat[chat];
      }
    }
    return { turns: { ...s.turns, [turnId]: next }, runningByChat };
  });
  return next;
}

/** Swap a send's local placeholder for the server's real turn id.
 *
 * The placeholder exists so the bubble appears the instant Send is pressed;
 * once `turn.start` names the real turn, the placeholder must disappear
 * completely — not linger as a second, never-finishing turn.
 */
export function replaceLocalTurn(localId: string, realId: string): void {
  store.set((s) => {
    const placeholder = s.turns[localId];
    const turns = { ...s.turns };
    delete turns[localId];
    if (!turns[realId] && placeholder) turns[realId] = { ...placeholder, turnId: realId };
    const runningByChat = { ...s.runningByChat };
    for (const [chat, id] of Object.entries(runningByChat)) {
      if (id === localId) runningByChat[chat] = realId;
    }
    return { turns, runningByChat };
  });
}

/** Adopt a running turn discovered on the server (reopen-reattach). */
export function adoptRemoteTurn(summary: Record<string, unknown>): AssistantTurn | undefined {
  const turnId = String(summary.turn_id ?? "");
  if (!turnId) return undefined;
  const chatId = String(summary.chat_id ?? "");
  const existing = store.get().turns[turnId];
  const turn: AssistantTurn = existing ?? {
    ...newTurn(turnId, chatId, Date.now()),
    status: String(summary.status ?? "Working"),
    state: "streaming",
    resumed: true,
    answer: String(summary.reply_preview ?? ""),
  };
  turn.resumed = true;
  if (typeof summary.status === "string" && summary.status) turn.status = summary.status;
  if (typeof summary.reply_preview === "string" && summary.reply_preview && !turn.answer) {
    turn.answer = summary.reply_preview;
  }
  store.set((s) => ({
    turns: { ...s.turns, [turnId]: turn },
    runningByChat: chatId ? { ...s.runningByChat, [chatId]: turnId } : s.runningByChat,
  }));
  return turn;
}

/** Apply a workspace `turn.state` summary (another window's turn, throttled). */
export function applyTurnStateSummary(summary: Record<string, unknown>): void {
  const turnId = String(summary.turn_id ?? "");
  if (!turnId) return;
  if (store.get().turns[turnId]) return; // we are streaming it ourselves
  const chatId = String(summary.chat_id ?? "");
  const state = String(summary.state ?? "streaming");
  const existing = store.get().turns[turnId];
  const turn: AssistantTurn = existing ?? {
    ...newTurn(turnId, chatId, Date.now()),
    resumed: true,
  };
  turn.status = String(summary.status ?? turn.status);
  turn.answer = turn.answer || String(summary.reply_preview ?? "");
  if (state === "done" || state === "error" || state === "stopped") {
    turn.state = state as AssistantTurn["state"];
    turn.status = state === "done" ? "Done" : turn.status;
    store.set((s) => {
      const runningByChat = { ...s.runningByChat };
      if (chatId) delete runningByChat[chatId];
      return { turns: { ...s.turns, [turnId]: turn }, runningByChat };
    });
    return;
  }
  store.set((s) => ({ turns: { ...s.turns, [turnId]: turn } }));
}

/** Fold a live turn into the transcript view: the message list renders this. */
export function turnToMessageView(turn: AssistantTurn): ChatMessageView {
  const failed = turn.state === "error";
  return {
    id: `turn:${turn.turnId}`,
    role: failed ? "error" : "assistant",
    content: turn.answer || (failed ? turn.error || "Something went wrong." : ""),
    turn,
    provider: turn.provider,
    createdAt: turn.startedAt,
  };
}

/** Drop finished turns we no longer need (called occasionally, not on every event). */
export function pruneTurns(keep = 40): void {
  const { turns } = store.get();
  const ids = Object.keys(turns);
  if (ids.length <= keep) return;
  const finished = ids
    .filter((id) => turns[id].state !== "streaming")
    .sort((a, b) => (turns[a].startedAt ?? 0) - (turns[b].startedAt ?? 0));
  const drop = new Set(finished.slice(0, finished.length - (keep - ids.filter((id) => turns[id].state === "streaming").length)));
  if (drop.size === 0) return;
  store.set((s) => {
    const next = { ...s.turns };
    for (const id of drop) delete next[id];
    return { turns: next };
  });
}

/** Workspace events the store cares about, routed from the single SSE connection. */
export function handleWorkspaceEvent(event: WorkspaceEvent): void {
  if (event.type === "turn.state") {
    applyTurnStateSummary(event as unknown as Record<string, unknown>);
  }
}
