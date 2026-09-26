/** Turning the local engine on and off from the page.
 *
 * A web page cannot start a program — that is a browser security boundary, not
 * a gap to code around. What it can do is follow a `nyx://` link, which Windows
 * hands to the Nyx launcher registered by setup. So "Turn on Nyx" is: follow the
 * link, then watch `/api/health` until the engine answers.
 *
 * The page itself survives the engine being off because a service worker keeps
 * a copy of the app shell (see public/sw.js). Without it, a restored tab showed
 * the browser's "site can't be reached" page and there was nothing to click.
 */

import { api } from "./api";

export interface EngineStatus {
  managed: boolean;
  port: number | null;
  pid: number;
  autostart: boolean;
  link_registered: boolean;
  data_dir: string;
  log: string;
}

/** Ask Windows to start Nyx through the registered nyx:// link. */
export function requestEngineStart(action: "start" | "open" | "restart" = "start"): void {
  // Assigning location to an external scheme hands it to the OS without
  // navigating away. An unregistered scheme is silently ignored, which is why
  // callers watch for the engine and explain what to do if it never answers.
  window.location.href = `nyx://${action}`;
}

/** True when the engine answers right now. */
export async function engineIsUp(timeoutMs = 2500): Promise<boolean> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch("/api/health", { signal: controller.signal, cache: "no-store" });
    if (!response.ok) return false;
    const data = (await response.json()) as { status?: string };
    return data?.status === "ok";
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}

/** Poll until the engine answers or `timeoutMs` passes. Reports elapsed seconds. */
export async function waitForEngine(
  timeoutMs: number,
  onTick?: (elapsedSeconds: number) => void,
  shouldStop?: () => boolean,
): Promise<boolean> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (shouldStop?.()) return false;
    if (await engineIsUp(1500)) return true;
    onTick?.(Math.round((Date.now() - started) / 1000));
    await new Promise((resolve) => window.setTimeout(resolve, 900));
  }
  return false;
}

export const engine = {
  status: () => api.get<EngineStatus>("/api/engine"),
  setAutostart: (enabled: boolean) => api.post<EngineStatus>("/api/engine/autostart", { enabled }),
  restart: () => api.post<{ ok: boolean }>("/api/engine/restart"),
  stop: () => api.post<{ ok: boolean }>("/api/engine/stop"),
};

/** Keep a copy of the app shell so the "Turn on Nyx" screen loads while the engine is off. */
export function registerShellCache(): void {
  if (!("serviceWorker" in navigator)) return;
  // Localhost counts as a secure context, which is what makes this allowed on
  // plain http://localhost:8000. A dev server on another port still works; it
  // just registers its own copy.
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
      /* Private windows and some policies block service workers — the app
         still works, it just cannot show the start screen while offline. */
    });
  });
}
