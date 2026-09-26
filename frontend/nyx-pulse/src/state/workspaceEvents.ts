/** One live connection to the workspace event stream.
 *
 * `/api/events/stream` carries everything the whole shell reacts to: theme
 * changes, tab changes, agent/skill updates, toasts, and the throttled
 * `turn.state` summaries that keep chats that run in other windows visible.
 * It is a module-level singleton because the store it feeds is module-level —
 * and because two connections would each hold a server-side subscription.
 *
 * Reconnects with a capped backoff; a stream that ends cleanly (server
 * restart, sleep/wake) is just re-opened. The auth path reuses `openStream`,
 * which reports 401 through the normal unauthorized handler.
 */

import { openStream } from "../stream";
import { reportUnauthorized } from "../api";
import { handleWorkspaceEvent } from "./turnStore";
import { handleNotifyEvent } from "./toastStore";
import type { WorkspaceEvent } from "../components/chat/types";

type Listener = (event: WorkspaceEvent) => void;

const listeners = new Set<Listener>();
let running = false;
let attempts = 0;

export function onWorkspaceEvent(listener: Listener): () => void {
  listeners.add(listener);
  start();
  return () => listeners.delete(listener);
}

function dispatch(event: WorkspaceEvent): void {
  handleWorkspaceEvent(event);
  handleNotifyEvent(event);
  listeners.forEach((listener) => listener(event));
}

function start(): void {
  if (running) return;
  running = true;
  void loop();
}

async function loop(): Promise<void> {
  while (running) {
    const result = await openStream<WorkspaceEvent>("/api/events/stream?channels=ui,activity", {
      method: "GET",
      onOpen: () => {
        attempts = 0;
      },
      onEvent: (event) => dispatch(event),
    });
    if (result.status === 401) {
      reportUnauthorized();
      running = false;
      return;
    }
    if (!running) return;
    attempts = Math.min(attempts + 1, 6);
    await new Promise((resolve) => window.setTimeout(resolve, 800 * 2 ** (attempts - 1)));
  }
}
