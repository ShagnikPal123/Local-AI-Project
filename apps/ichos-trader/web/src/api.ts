// The trader's web API (docs/API.md). One typed helper per route; errors carry the server's sentence.

export type Role = "owner" | "viewer";
export type Me = { user: { name: string; email: string; role: Role } | null; auth_mode: string; providers: string[]; signed_in: boolean };

export type Market = {
  symbol: string; name: string; asset_class: string; price: number; change_pct: number | null; score: number;
  signal: string; confidence: number; liquidity: number; spread_bps: number; depth_usd: number; flow: number;
  tradability: number; open: boolean; sparkline: number[]; reasons?: string[]; dollar_volume?: number;
};
export type Position = { symbol: string; asset_class: string; qty: number; avg_price: number; price: number; value: number; pl: number; pl_pct: number; bot: string };
export type Trade = { at: number; symbol: string; side: string; qty: number; price: number; value: number; fee: number; bot: string; reason: string; money: string; realized?: number | null };
export type Bot = { id: string; name: string; role: string; front: boolean; status: string; doing: string; style: string; classes: string[]; pot: number; share: number; pl_pct: number; trades: number; hired_at: number };
export type Note = { at: number; bot: string; role: string; level: string; symbol: string; text: string };
export type Prediction = { symbol: string; horizon_h: number; expected_pct: number; low_pct: number; high_pct: number; confidence: number; made_at: number; graded: boolean; right: boolean | null; actual_pct?: number };
export type Speed = { last_cycle_ms: number | null; p50_ms: number | null; p95_ms: number | null; decision_ms: number | null; grade: string; words: string; stages: Record<string, number> };
export type Theme = { accent: string; mode: "dark" | "light" | "system"; sync: string };

export type Dashboard = {
  state: "off" | "learning" | "trading" | "paused" | "shutdown"; state_words: string; stopped_reason: string;
  money_kind: "practice" | "real"; market_source: "simulated" | "live";
  money: { currency: string; equity: number; cash: number; start: number; pl: number; pl_pct: number; today_pl: number; today_pl_pct: number; predicted_pl_pct: number; predicted_band_pct: [number, number]; predicted_horizon_h: number };
  win_rate: { closed: number; wins: number; rate: number | null };
  equity_curve: { t: number; equity: number }[]; scanned: number; markets: Market[]; positions: Position[]; trades: Trade[];
  bots: Bot[]; bots_running: number; thinking: Note[];
  plan: { next_cycle_at?: number; steps?: string[]; focus?: string[] };
  predictions: Prediction[]; prediction_record: { graded: number; right: number; rate: number | null };
  research: { at: number; symbol: string; summary: string; source: string }[];
  speed: Speed; learning: { done: boolean; studied: number; total: number; words: string; best: { strategy: string; title: string; regime: string; edge_pct: number }[] };
  hires: { at: number; name: string; why: string }[]; last_error: string; theme: Theme; updated_at: number;
};

export type Settings = Record<string, unknown> & {
  auto: boolean; learn_first: boolean; risk: number; skeptic: number; max_positions: number; max_position_pct: number;
  stop_loss_pct: number; take_profit_pct: number; pace_seconds: number; scan_limit: number; max_bots: number; start_cash: number;
  markets: Record<string, boolean>; shutdown: Record<string, number>; pins: Record<string, number>; theme: Theme;
  claude: { enabled: boolean };
};
export type SettingsView = { settings: Settings; effective: Settings; chosen: Record<string, { value: number; why: string }>; limits: Record<string, [number, number]>; auto_keys: string[] };

export type Connector = {
  id: string; kind: string; title: string; recommended: boolean; wired: boolean; money: string; why: string;
  fields: { key: string; label: string; secret: boolean }[]; connected: boolean; status: string;
  masked: Record<string, { from: string; last4?: string }>; note?: string;
};
export type SpeedTest = { grade: string; words: string; stages: Record<string, number>; decision_ms: number; cycle_ms: number; markets: number };

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const reply = await fetch(path, {
    method,
    credentials: "same-origin",
    // The trader refuses changes without this header, so other websites cannot press the buttons.
    headers: { "Content-Type": "application/json", "x-ichos-trader": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await reply.json().catch(() => ({}));
  if (!reply.ok) throw new Error((data as { detail?: string }).detail || `The trader answered ${reply.status}.`);
  return data as T;
}

export const api = {
  me: () => call<Me>("/api/me"),
  passcode: (passcode: string) => call<{ ok: boolean }>("/api/auth/passcode", "POST", { passcode }),
  logout: () => call<{ ok: boolean }>("/api/auth/logout", "POST", {}),
  dashboard: () => call<Dashboard>("/api/dashboard"),
  control: (what: "start" | "stop" | "cycle" | "flatten") => call<{ state: string }>(`/api/control/${what}`, "POST", {}),
  settings: () => call<SettingsView>("/api/settings"),
  saveSettings: (changes: Record<string, unknown>) => call<SettingsView>("/api/settings", "PUT", changes),
  speedtest: () => call<SpeedTest>("/api/speedtest", "POST", {}),
  resetPaper: (cash: number) => call<unknown>("/api/paper/reset", "POST", { cash }),
  connectors: () => call<Connector[]>("/api/connectors"),
  connect: (id: string, values: Record<string, string>) => call<Connector>(`/api/connectors/${id}`, "POST", values),
  disconnect: (id: string) => call<{ ok: boolean }>(`/api/connectors/${id}`, "DELETE"),
  ask: (question: string) => call<{ answer: string; model: string }>("/api/claude/ask", "POST", { question }),
};

export const money = (n: number, currency = "USD") =>
  new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: Math.abs(n) >= 1000 ? 0 : 2 }).format(n);
export const pct = (n: number | null | undefined, digits = 1) =>
  n === null || n === undefined ? "–" : `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
export const ago = (t: number) => {
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 60 ? `${Math.round(s)}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
};
export const price = (n: number) => (n >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 }) : n >= 1 ? n.toFixed(2) : n.toPrecision(3));
