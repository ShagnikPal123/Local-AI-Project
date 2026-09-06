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
  chat: (message: string) => api.post<ChatResponse>("/api/chat", { message }),
  models: () => api.get<unknown>("/api/models"),
  personalities: () => api.get<unknown>("/api/personalities"),
  memory: () => api.get<unknown>("/api/memory"),
  chats: () => api.get<unknown>("/api/chats"),
};
