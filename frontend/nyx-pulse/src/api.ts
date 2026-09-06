/** Client for the local FastAPI backend (server.py).
 *
 * Vite proxies /api to http://127.0.0.1:8000 in dev. Every call degrades to a
 * typed error rather than throwing into a render, because the backend is often
 * simply not running yet and a blank screen is a worse answer than a message.
 */

export interface ApiError {
  ok: false;
  error: string;
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

async function request<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
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
      setToken(null);
      onUnauthorized?.();
      return { ok: false, error: "Sign in required" };
    }
    if (response.status === 403) {
      const detail = await response.json().catch(() => null);
      return { ok: false, error: detail?.detail ?? "You do not have permission for that." };
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      return {
        ok: false,
        error: detail?.detail ?? `${response.status} ${response.statusText}`,
      };
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
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  // PATCH is how a tab is edited field-by-field (`PATCH /api/tabs/{id}`), which
  // is what lets the tab creator hold the user to the name they typed even
  // though the design step returns a name of the model's own choosing.
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  del: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
};

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
}

export interface RouterStatus {
  device_tier?: string;
  online?: boolean;
  ollama_available?: boolean;
  gemini_available?: boolean;
  openai_available?: boolean;
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
    const full = await api.get<{ providers?: ProviderInfo[]; preferred?: string }>("/api/providers");
    if (full.ok && Array.isArray(full.data?.providers)) {
      return {
        mode: "full",
        providers: full.data.providers,
        preferred: full.data.preferred,
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
  create: (body: { name: string; api_key: string; chat_url?: string; model?: string }) =>
    api.post<{ provider?: ProviderInfo }>("/api/providers", body),
  test: (name: string) =>
    api.post<{ ok?: boolean; detail?: string; error?: string; message?: string }>(
      `/api/providers/${encodeURIComponent(name)}/test`,
    ),
  remove: (name: string) => api.del<unknown>(`/api/providers/${encodeURIComponent(name)}`),
};
