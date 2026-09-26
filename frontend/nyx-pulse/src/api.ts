/** Client for the local FastAPI backend (server.py).
 *
 * Vite proxies /api to http://127.0.0.1:8000 in dev. Every call degrades to a
 * typed error rather than throwing into a render, because the backend is often
 * simply not running yet and a blank screen is a worse answer than a message.
 */

export interface ApiError {
  ok: false;
  error: string;
  /** HTTP status when the server answered; absent for network failures and timeouts. */
  status?: number;
}

export interface ApiOk<T> {
  ok: true;
  data: T;
}

export type ApiResult<T> = ApiOk<T> | ApiError;

const TIMEOUT_MS = 30_000;
const TOKEN_KEY = "nyx.session";

/** Session token, held in memory and mirrored to localStorage.
 *
 * Kept in a module variable so every request picks it up without threading it
 * through props. localStorage is a convenience only — the server treats sessions
 * as in-memory, so a backend restart invalidates whatever is stored here.
 */
let sessionToken: string | null = (() => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
})();

export function getToken(): string | null {
  return sessionToken;
}

export function setToken(token: string | null): void {
  sessionToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private browsing — the session simply will not survive a reload */
  }
}

/** Called when the server rejects our token, so the UI can show the login screen. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

/** The Authorization header for callers that use fetch directly (streams, uploads, blobs). */
export function authHeaders(): Record<string, string> {
  return sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {};
}

/** A direct-fetch caller got a 401: drop the token and let the app re-prompt. */
export function reportUnauthorized(): void {
  setToken(null);
  onUnauthorized?.();
}

async function errorDetail(response: Response): Promise<string> {
  const detail = await response.json().catch(() => null);
  const text = detail?.detail;
  if (typeof text === "string") return text;
  if (Array.isArray(text) && text[0]?.msg) return String(text[0].msg);
  return `${response.status} ${response.statusText}`.trim();
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = TIMEOUT_MS): Promise<ApiResult<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}),
        ...(init?.headers ?? {}),
      },
    });
    if (response.status === 401) {
      // The token is gone or expired — most often the backend restarted, since
      // sessions are deliberately in-memory. Drop it and let the app re-prompt.
      reportUnauthorized();
      return { ok: false, error: "Sign in required", status: 401 };
    }
    if (response.status === 403) {
      const detail = await response.json().catch(() => null);
      return { ok: false, error: detail?.detail ?? "You do not have permission for that.", status: 403 };
    }
    if (!response.ok) {
      return { ok: false, error: await errorDetail(response), status: response.status };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return { ok: false, error: "Request timed out" };
    }
    // The overwhelmingly common case: the Python server is not running.
    return { ok: false, error: "Cannot reach the local backend" };
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  get: <T,>(path: string, timeoutMs?: number) => request<T>(path, {}, timeoutMs),
  post: <T,>(path: string, body?: unknown, timeoutMs?: number) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }, timeoutMs),
  // PATCH is how a tab is edited field-by-field (`PATCH /api/tabs/{id}`), which
  // is what lets the tab creator hold the user to the name they typed even
  // though the design step returns a name of the model's own choosing.
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) }),
  del: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
};

// --- uploads and authenticated files -------------------------------------------

export interface UploadRecord {
  id: string;
  name: string;
  mime: string;
  size: number;
  kind: string;
  width?: number;
  height?: number;
}

/** Send one file as a raw body (`POST /api/uploads`). No timeout: large files take time. */
export async function uploadFile(file: File, signal?: AbortSignal): Promise<ApiResult<UploadRecord>> {
  try {
    const response = await fetch("/api/uploads", {
      method: "POST",
      body: file,
      signal,
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name || "upload"),
        ...authHeaders(),
      },
    });
    if (response.status === 401) {
      reportUnauthorized();
      return { ok: false, error: "Sign in required", status: 401 };
    }
    if (!response.ok) return { ok: false, error: await errorDetail(response), status: response.status };
    const data = (await response.json()) as { upload?: UploadRecord } & Partial<UploadRecord>;
    const record = data.upload ?? (data.id ? (data as UploadRecord) : null);
    return record ? { ok: true, data: record } : { ok: false, error: "The upload returned no id." };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return { ok: false, error: "Upload cancelled" };
    return { ok: false, error: "Cannot reach the local backend" };
  }
}

const blobUrls = new Map<string, Promise<string | null>>();

/** A URL an <img> can load for an authenticated path.
 *
 * Image tags cannot send a bearer header, so once a token exists the file is
 * fetched with it and handed over as an object URL (cached per path).
 */
export function authedUrl(path: string): Promise<string | null> {
  if (!sessionToken || path.startsWith("data:") || path.startsWith("blob:")) return Promise.resolve(path);
  let pending = blobUrls.get(path);
  if (!pending) {
    pending = fetch(path, { headers: authHeaders() })
      .then(async (r) => (r.ok ? URL.createObjectURL(await r.blob()) : null))
      .catch(() => null);
    blobUrls.set(path, pending);
  }
  return pending;
}

// --- shapes returned by server.py ---------------------------------------------

export interface HealthResponse {
  status?: string;
  /** True once an owner account exists, meaning a login is required. */
  claimed?: boolean;
  capabilities?: string[];
  [key: string]: unknown;
}

export interface AccountUser {
  email: string;
  role: "owner" | "admin" | "beta" | "user";
  created_at: number;
  invited_by: string;
  auth_methods: string[];
}

export interface LoginResponse {
  token: string;
  user: AccountUser | null;
}

export interface InviteResponse {
  token: string;
  role: string;
  email: string;
  expires_at: number;
  link: string;
}

export interface HardwareHealth {
  gpu_temp_c?: number;
  vram_used_mb?: number;
  vram_total_mb?: number;
  gpu_utilization?: number;
  status_summary?: string;
  throttle_recommended?: boolean;
  throttled?: boolean;
  disk_free_gb?: number;
}

export interface RouterStatus {
  device_tier?: string;
  online?: boolean;
  ollama_available?: boolean;
  gemini_available?: boolean;
  openai_available?: boolean;
  nvidia_available?: boolean;
  qwen_available?: boolean;
  groq_available?: boolean;
  claude_available?: boolean;
  free_only?: boolean;
  preferred_online_provider?: string;
  hardware_health?: HardwareHealth;
  device_profile?: Record<string, unknown>;
}

export interface StatusResponse {
  router_status?: RouterStatus;
  tools_enabled?: boolean;
  available_tools?: number;
  [key: string]: unknown;
}

export interface ChatResponse {
  // Must match server.py ChatResponse. The field is `reply`, not `response`:
  // ChatPanel read `response`, got undefined, and rendered an empty bubble on
  // an HTTP 200 with no error anywhere to notice.
  reply: string;
  provider: string;
  metadata?: Record<string, unknown>;
  chat_id?: string;
  thought_id?: string | null;
}

export const auth = {
  login: (email: string, password: string) =>
    api.post<LoginResponse>("/api/auth/login", { email, password }),
  logout: () => api.post<{ ok: boolean }>("/api/auth/logout"),
  me: () => api.get<{ claimed: boolean; user: AccountUser | null }>("/api/auth/me"),
  join: (invite: string, email: string, password: string) =>
    api.post<{ user: AccountUser }>("/api/auth/join", { invite, email, password }),
};

export const admin = {
  users: () => api.get<{ users: AccountUser[] }>("/api/admin/users"),
  invites: () => api.get<{ invites: unknown[] }>("/api/admin/invites"),
  createInvite: (role: string, email: string, baseUrl: string) =>
    api.post<InviteResponse>("/api/admin/invites", { role, email, base_url: baseUrl }),
};

export const endpoints = {
  health: () => api.get<HealthResponse>("/api/health"),
  status: () => api.get<StatusResponse>("/api/status"),
  chat: (message: string, provider?: string) =>
    api.post<ChatResponse>("/api/chat", provider ? { message, provider } : { message }),
  models: () => api.get<ModelsResponse>("/api/models"),
  personalities: () => api.get<unknown>("/api/personalities"),
  memory: () => api.get<unknown>("/api/memory"),
  chats: () => api.get<ChatsResponse>("/api/chats"),
};

// --- conversation history ------------------------------------------------------

/** One turn as the UI holds it. `error` is a client-side pseudo-role. */
export interface ChatMessage {
  role: "user" | "assistant" | "error";
  content: string;
  provider?: string;
  elapsedMs?: number;
}

/** `/api/chats` has had two shapes. The old one lists chat ids only; a newer
 *  backend returns the conversations themselves. Accept either. */
export interface ChatsResponse {
  chats?: unknown;
  count?: number;
  [key: string]: unknown;
}

const ROLES = new Set(["user", "assistant"]);

function turnsFrom(value: unknown): ChatMessage[] | null {
  // System turns are prompt scaffolding (memory, speech patterns, personality)
  // and are not part of what the user said — showing them would be a leak.
  if (!Array.isArray(value)) return null;
  const turns: ChatMessage[] = [];
  for (const raw of value) {
    if (!raw || typeof raw !== "object") continue;
    const entry = raw as Record<string, unknown>;
    const role = String(entry.role ?? "");
    if (!ROLES.has(role)) continue;
    const content = String(entry.content ?? entry.text ?? "");
    if (!content.trim()) continue;
    turns.push({
      role: role as "user" | "assistant",
      content,
      provider: typeof entry.provider === "string" ? entry.provider : undefined,
    });
  }
  return turns;
}

function findConversation(container: unknown, chatId: string): ChatMessage[] | null {
  if (Array.isArray(container)) {
    // Old shape: a plain list of ids, which carries no transcript at all.
    if (container.every((c) => typeof c === "string")) return null;
    const entries = container.filter((c) => c && typeof c === "object") as Record<string, unknown>[];
    const match =
      entries.find((c) => [c.id, c.chat_id, c.name].some((v) => v === chatId)) ?? entries[0];
    if (!match) return null;
    return turnsFrom(match.messages ?? match.history ?? match.turns ?? match.conversation);
  }
  if (container && typeof container === "object") {
    const map = container as Record<string, unknown>;
    const one = map[chatId];
    if (one === undefined) return null;
    if (Array.isArray(one)) return turnsFrom(one);
    if (one && typeof one === "object") {
      const record = one as Record<string, unknown>;
      return turnsFrom(record.messages ?? record.history ?? record.turns);
    }
  }
  return null;
}

/** Server-side transcript for a chat, or null when the backend does not expose one.
 *
 * `null` is a real answer, not a failure: the shipped `/api/chats` returns chat
 * ids only (history lives in each ChatService in memory, with no route to read
 * it). The caller falls back to its local mirror in that case rather than
 * wiping a conversation the user can still see.
 */
export async function loadChatHistory(chatId = "default"): Promise<ChatMessage[] | null> {
  const result = await endpoints.chats();
  if (!result.ok) return null;
  const data = result.data as Record<string, unknown>;
  return (
    findConversation(data.chats, chatId) ??
    findConversation(data.conversations, chatId) ??
    turnsFrom(data.messages)
  );
}

// --- agents --------------------------------------------------------------------

export interface AgentSpecInput {
  name: string;
  goal: string;
  role: "worker" | "master";
}

export const agents = {
  list: <T,>() => api.get<T>("/api/agents"),
  create: <T,>(spec: AgentSpecInput) => api.post<T>("/api/agents", { agents: [spec] }),
  remove: <T,>(agentId: string) => api.del<T>(`/api/agents/${encodeURIComponent(agentId)}`),
};

// --- providers -----------------------------------------------------------------

/** A provider as the (new) `/api/providers` route describes it.
 *
 * `last4` is the only part of a key that ever crosses the wire — never render
 * anything but the mask built from it.
 */
export interface ProviderInfo {
  name: string;
  configured: boolean;
  last4?: string;
  model?: string;
  chat_url?: string;
  preferred?: boolean;
  builtin?: boolean;
  /** Human label, e.g. "NVIDIA NIM". */
  label?: string;
  /** Free-tier providers: key costs nothing. */
  free?: boolean;
  /** Where to get a key, e.g. https://build.nvidia.com/models */
  signup_url?: string;
}

/** A free provider the app knows how to configure, offered in the Models panel. */
export interface ProviderPreset {
  name: string;
  label: string;
  model?: string;
  signup_url?: string;
  notes?: string;
}

export interface ModelsResponse {
  local?: unknown;
  local_active?: string;
  online?: { name: string; configured: boolean }[];
  preferred_online?: string;
}

/** How much of the provider surface this backend actually has.
 *
 * "full"    — /api/providers exists: list, add, test, delete.
 * "reduced" — only /api/models: the built-in providers can be listed and chosen,
 *             but nothing can be added from the UI.
 * "offline" — neither answered.
 */
export type ProviderMode = "full" | "reduced" | "offline";

export interface ProviderSnapshot {
  mode: ProviderMode;
  providers: ProviderInfo[];
  preferred?: string;
  /** Free-only mode is on: paid providers stay out of routing. */
  freeOnly?: boolean;
  /** Free providers worth adding, with their signup links. */
  presets?: ProviderPreset[];
  /** Why the UI is in a reduced state, in words fit to show a user. */
  note?: string;
}

function providersFromModels(data: ModelsResponse): ProviderInfo[] {
  return (data.online ?? []).map((p) => ({
    name: p.name,
    configured: Boolean(p.configured),
    preferred: p.name === data.preferred_online,
    builtin: true,
  }));
}

export const providers = {
  /** Read the provider list, degrading to `/api/models` if the route is absent. */
  async list(): Promise<ProviderSnapshot> {
    const full = await api.get<{
      providers?: ProviderInfo[]; preferred?: string; free_only?: boolean; presets?: ProviderPreset[];
    }>("/api/providers");
    if (full.ok && Array.isArray(full.data?.providers)) {
      return {
        mode: "full",
        providers: full.data.providers,
        preferred: full.data.preferred,
        freeOnly: full.data.free_only,
        presets: full.data.presets ?? [],
      };
    }
    const models = await endpoints.models();
    if (models.ok) {
      return {
        mode: "reduced",
        providers: providersFromModels(models.data),
        preferred: models.data.preferred_online,
        note:
          "This backend does not have the provider API yet, so providers can be chosen " +
          "but not added from here. Keys for the built-in providers go in .env.local.",
      };
    }
    return { mode: "offline", providers: [], note: models.error };
  },
  /** Store a key for a built-in provider (or a previously added custom one). */
  setKey: (name: string, apiKey: string) =>
    api.post<{ provider: string; last4: string; applied_live: boolean; masked: string }>(
      `/api/providers/${encodeURIComponent(name)}/key`,
      { api_key: apiKey },
    ),
  /** Forget the stored key(s) for a provider; the provider stays listed, keyless. */
  removeKey: (name: string) =>
    api.del<{ provider: string; removed: boolean }>(`/api/providers/${encodeURIComponent(name)}/key`),
  create: (body: { name: string; api_key: string; chat_url?: string; model?: string }) =>
    api.post<{ provider?: ProviderInfo }>("/api/providers", body),
  test: (name: string) =>
    api.post<{ ok?: boolean; detail?: string; error?: string; message?: string }>(
      `/api/providers/${encodeURIComponent(name)}/test`,
    ),
  remove: (name: string) => api.del<unknown>(`/api/providers/${encodeURIComponent(name)}`),
};
