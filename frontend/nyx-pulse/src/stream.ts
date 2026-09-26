/** Server-Sent Events over fetch.
 *
 * EventSource cannot send a bearer header or a POST body, and both the chat
 * stream (POST) and every authenticated stream (once an install is claimed)
 * need one. So this reads the response body directly and parses the SSE frames:
 * `data:` lines are joined into one JSON payload per blank-line-terminated
 * block; `:` comment lines (the server's keep-alives) are ignored.
 */

import { authHeaders, reportUnauthorized } from "./api";

export interface StreamOptions<T> {
  method?: "GET" | "POST";
  /** JSON body for POST. */
  body?: unknown;
  signal?: AbortSignal;
  /** Called once the server has accepted the request (2xx), before any event. */
  onOpen?: () => void;
  /** One call per `data:` frame. `index` counts events on this connection from 0. */
  onEvent: (event: T, index: number) => void;
}

export interface StreamResult {
  /** True when the connection opened and ended without a transport error. */
  ok: boolean;
  /** HTTP status, or 0 when the server could not be reached. */
  status: number;
  error?: string;
  /** Events delivered on this connection. */
  count: number;
  aborted: boolean;
}

export async function openStream<T = Record<string, unknown>>(
  path: string,
  options: StreamOptions<T>,
): Promise<StreamResult> {
  const { method = "GET", body, signal, onOpen, onEvent } = options;
  let count = 0;
  let status = 0;
  try {
    const response = await fetch(path, {
      method,
      signal,
      cache: "no-store",
      headers: {
        Accept: "text/event-stream",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...authHeaders(),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    status = response.status;
    if (response.status === 401) {
      reportUnauthorized();
      return { ok: false, status, error: "Sign in required", count, aborted: false };
    }
    if (!response.ok || !response.body) {
      const detail = await response.json().catch(() => null);
      const error = typeof detail?.detail === "string" ? detail.detail : `${response.status} ${response.statusText}`;
      return { ok: false, status, error, count, aborted: false };
    }
    onOpen?.();

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Frames end with a blank line; tolerate \r\n from proxies.
      let boundary = FRAME_END.exec(buffer);
      while (boundary) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const event = parseFrame<T>(frame);
        if (event !== undefined) onEvent(event, count++);
        boundary = FRAME_END.exec(buffer);
      }
    }
    const tail = parseFrame<T>(buffer);
    if (tail !== undefined) onEvent(tail, count++);
    return { ok: true, status, count, aborted: false };
  } catch (error) {
    const aborted = (error instanceof DOMException && error.name === "AbortError") || Boolean(signal?.aborted);
    return {
      ok: false,
      status,
      error: aborted ? "Cancelled" : status ? "The connection dropped" : "Cannot reach the local backend",
      count,
      aborted,
    };
  }
}

const FRAME_END = /\r?\n\r?\n/;

function parseFrame<T>(frame: string): T | undefined {
  if (!frame.trim()) return undefined;
  const data: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("data:")) data.push(line.slice(line[5] === " " ? 6 : 5));
  }
  if (data.length === 0) return undefined;
  try {
    return JSON.parse(data.join("\n")) as T;
  } catch {
    return undefined;
  }
}
