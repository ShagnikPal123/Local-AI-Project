/** Keys & Models, Request H8: several keys per provider, alerts about a failing key, and models you add.
 *
 * Status is always a word and a symbol, never colour alone: ✓ Working, ▲ Failed, $ Needs payment,
 * ○ Not tried yet. A key comes back from the server only as its last four characters.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { pushToast } from "../state/toastStore";
import { onWorkspaceEvent } from "../state/workspaceEvents";

export interface PoolKey {
  fingerprint: string; last4: string; source: "env" | "stored" | "live"; in_use: boolean;
  state: "working" | "failed" | "untested"; kind: string; fails: number; last_error: string;
}
interface Pool { provider: string; key_name: string; keys: PoolKey[]; needs_payment: string | null }
interface Alert {
  provider: string; key_name: string; fingerprint: string; last4: string; source: string; kind: string;
  fails: number; since: number; last_error: string; others_working: number;
}

const KIND_TEXT: Record<string, string> = { auth: "the key was refused", payment: "the API asked for payment", quota: "its limit was reached" };

function stateLabel(key: PoolKey): string {
  if (key.state === "working") return "✓ Working";
  if (key.state === "untested") return "○ Not tried yet";
  if (key.kind === "quota") return "⏳ Limit reached — retrying";
  return key.kind === "payment" ? "$ Needs payment" : `▲ Failed ${key.fails}×`;
}

/** The question H8 asks for: after a key has kept failing, may Nyx drop only that one? */
export function KeyAlerts() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [retryEvery, setRetryEvery] = useState(5);
  const load = useCallback(async () => {
    const result = await api.get<{ alerts: Alert[]; retry_every: number }>("/api/keys/alerts");
    if (result.ok) { setAlerts(result.data.alerts); setRetryEvery(result.data.retry_every); }
  }, []);
  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 60_000);
    const off = onWorkspaceEvent((event) => { if (event.type === "keys.changed") void load(); });
    return () => { window.clearInterval(id); off(); };
  }, [load]);

  async function answer(alert: Alert, action: "drop" | "keep") {
    const result = await api.post<{ alerts: Alert[] }>(`/api/keys/alerts/${alert.key_name}/${alert.fingerprint}`, { action });
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setAlerts(result.data.alerts);
    pushToast(action === "drop" ? `Removed the ${alert.provider} key ending ${alert.last4}. The others stay.` : `Nyx keeps retrying that key every ${retryEvery} requests.`, "ok");
  }

  if (alerts.length === 0) return null;
  return (
    <section className="key-alerts" aria-label="Keys that keep failing">
      {alerts.map((alert) => (
        <div key={alert.fingerprint} className="key-alert" role="alert">
          <span className="key-alert__icon" aria-hidden="true">▲</span>
          <div className="key-alert__text">
            <b>Your {alert.provider} key ending {alert.last4 || "…"} keeps failing</b>
            <span>
              It failed {alert.fails} times since {new Date(alert.since * 1000).toLocaleString([], { hour: "numeric", minute: "2-digit", month: "short", day: "numeric" })} — {KIND_TEXT[alert.kind] ?? "it stopped working"}
              {alert.last_error ? ` (“${alert.last_error.slice(0, 120)}”)` : ""}.{" "}
              {alert.others_working > 0 ? `${alert.others_working} other ${alert.provider} key${alert.others_working > 1 ? "s are" : " is"} working.` : `No other ${alert.provider} key is working.`}
            </span>
          </div>
          <div className="key-alert__actions">
            <button className="btn btn-secondary" onClick={() => void answer(alert, "keep")}>Keep Retrying</button>
            {alert.source === "env" ? (
              <span className="keys-notes">This key is in .env.local — remove it there.</span>
            ) : (
              <button className="btn btn-primary" onClick={() => void answer(alert, "drop")}>Remove Only This Key</button>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}

/** Inside a provider card: every key it has, and "Add Another Key". */
export function KeyPool({ provider, onChanged }: { provider: string; onChanged?: () => void }) {
  const [pool, setPool] = useState<Pool | null>(null);
  const [adding, setAdding] = useState(false);
  const [value, setValue] = useState("");
  const load = useCallback(async () => {
    const result = await api.get<Pool>(`/api/keys/${encodeURIComponent(provider)}/pool`);
    if (result.ok) setPool(result.data);
  }, [provider]);
  useEffect(() => {
    void load();
    return onWorkspaceEvent((event) => { if (event.type === "keys.changed") void load(); });
  }, [load]);

  async function add() {
    const result = await api.post<Pool>(`/api/keys/${encodeURIComponent(provider)}/pool`, { api_key: value });
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setPool(result.data); setValue(""); setAdding(false); onChanged?.();
    pushToast(`Saved. Nyx switches to it if the key in use stops working.`, "ok");
  }
  async function remove(key: PoolKey) {
    const result = await api.del<Pool>(`/api/keys/${encodeURIComponent(provider)}/pool/${key.fingerprint}`);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setPool(result.data); onChanged?.();
  }

  if (!pool || pool.keys.length === 0) return null;
  return (
    <div className="key-pool">
      {pool.needs_payment && <p className="keys-message is-error">$ The {provider} API said every key needs payment: {pool.needs_payment}</p>}
      <ul className="key-pool__list" aria-label={`${provider} keys`}>
        {pool.keys.map((key) => (
          <li key={key.fingerprint} className={`key-pool__row is-${key.state}`}>
            <code>•••• {key.last4 || "????"}</code>
            <span className="key-pool__state" title={key.last_error || undefined}>{stateLabel(key)}</span>
            {key.in_use && <span className="keys-badge">In use</span>}
            {key.source === "env" ? <span className="keys-notes">.env.local</span> : pool.keys.length > 1 && (
              <button className="chat-inline" onClick={() => void remove(key)} aria-label={`Remove key ending ${key.last4}`}>Remove</button>
            )}
          </li>
        ))}
      </ul>
      {adding ? (
        <form className="key-pool__add" onSubmit={(e) => { e.preventDefault(); if (value.trim()) void add(); }}>
          <input type="password" autoComplete="off" spellCheck={false} value={value} autoFocus placeholder="Paste another key"
            aria-label={`Another ${provider} key`} onChange={(e) => setValue(e.target.value)} />
          <button className="btn btn-primary" disabled={!value.trim()}>Add</button>
          <button type="button" className="btn btn-secondary" onClick={() => { setAdding(false); setValue(""); }}>Cancel</button>
        </form>
      ) : (
        <button className="chat-inline" onClick={() => setAdding(true)}>Add Another Key</button>
      )}
    </div>
  );
}

interface Company { id: string; label: string; url: string; example: string; signup: string }
interface CustomModel { name: string; label: string; model: string; chat_url: string; notes: string; is_free: boolean; keys: PoolKey[]; needs_payment: string | null }

const USE_LABELS: Record<string, string> = {
  chat: "General chat", coding: "Coding", vision: "Images & screenshots", fast: "Fast replies",
  research: "Research", writing: "Writing", other: "Something else",
};

/** "Add a model": name, company, model, key, and what it is for. */
export function CustomModelsSection() {
  const [models, setModels] = useState<CustomModel[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [uses, setUses] = useState<string[]>([]);
  const [form, setForm] = useState({ name: "", company: "openrouter", model: "", api_key: "", use: "chat", use_note: "", chat_url: "", free: true });
  const [busy, setBusy] = useState(false);
  const [tested, setTested] = useState<Record<string, string>>({});
  const [check, setCheck] = useState<{ ok: boolean; url: string; local: boolean; models: string[]; detail: string } | null>(null);
  const [checking, setChecking] = useState(false);

  const load = useCallback(async () => {
    const result = await api.get<{ models: CustomModel[]; companies: Company[]; uses: string[] }>("/api/custom-models");
    if (!result.ok) return;
    setModels(result.data.models); setCompanies(result.data.companies); setUses(result.data.uses);
  }, []);
  useEffect(() => { void load(); }, [load]);
  // The model finder at the bottom of this tab hands a provider up here; the owner still types the key.
  const box = useRef<HTMLFormElement>(null);
  useEffect(() => {
    const onPrefill = () => {
      try {
        const raw = sessionStorage.getItem("nyx.custommodel.prefill");
        if (!raw) return;
        sessionStorage.removeItem("nyx.custommodel.prefill");
        const found = JSON.parse(raw) as Partial<typeof form> & { company?: string };
        setForm((current) => ({ ...current, ...found, api_key: "" }));
        box.current?.scrollIntoView({ block: "center", behavior: "smooth" });
        box.current?.querySelector<HTMLInputElement>("input[type=password]")?.focus();
      } catch { /* nothing to prefill */ }
    };
    window.addEventListener("nyx:prefill-model", onPrefill);
    return () => window.removeEventListener("nyx:prefill-model", onPrefill);
  }, []);

  const company = companies.find((c) => c.id === form.company);
  const urlRequired = form.company === "other";
  const looksLocal = /^(https?:\/\/)?(localhost|127\.|192\.168\.|10\.|\[::1\])/i.test(form.chat_url.trim());

  /** Try the address first: Nyx completes a base URL, lists the models it offers and sends one token. */
  async function checkUrl() {
    setChecking(true);
    const result = await api.post<{ ok: boolean; url: string; local: boolean; models: string[]; detail: string; model?: string }>(
      "/api/custom-models/check", { company: form.company, chat_url: form.chat_url, model: form.model, api_key: form.api_key }, 45_000);
    setChecking(false);
    if (!result.ok) { setCheck({ ok: false, url: form.chat_url, local: false, models: [], detail: result.error }); return; }
    setCheck(result.data);
    if (!form.model && result.data.model) setForm((f) => ({ ...f, model: result.data.model ?? f.model }));
  }

  async function add() {
    setBusy(true);
    const result = await api.post<{ model: CustomModel }>("/api/custom-models", form);
    setBusy(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast(`${form.name} added — it's in the chat's model menu now.`, "ok");
    setForm({ ...form, name: "", model: "", api_key: "", use_note: "", chat_url: "" });
    setCheck(null);
    void load();
  }
  async function test(name: string) {
    setTested((t) => ({ ...t, [name]: "Testing…" }));
    const result = await api.post<{ ok?: boolean; detail?: string }>(`/api/providers/${encodeURIComponent(name)}/test`, undefined, 60_000);
    setTested((t) => ({ ...t, [name]: result.ok ? `${result.data.ok ? "✓" : "▲"} ${result.data.detail ?? ""}` : `▲ ${result.error}` }));
  }
  async function remove(name: string) {
    const result = await api.del(`/api/custom-models/${encodeURIComponent(name)}`);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    void load();
  }

  return (
    <section className="keys-section">
      <h2 className="keys-heading">Add a model</h2>
      <p className="keys-notes">
        Any company with an OpenAI-compatible API. Nyx only treats it as paid when its API says a key needs payment.
      </p>
      <form ref={box} className="card keys-provider custom-model-form" onSubmit={(e) => { e.preventDefault(); if (!busy) void add(); }}>
        <div className="keys-role__grid">
          <label className="keys-field"><span>Name</span>
            <input value={form.name} placeholder="e.g. Llama on OpenRouter" onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label className="keys-field"><span>Company</span>
            <select value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })}>
              {companies.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select></label>
          <label className="keys-field"><span>Model ID</span>
            <input value={form.model} list="custom-model-ids" placeholder={company?.example || "model-name"} spellCheck={false} onChange={(e) => setForm({ ...form, model: e.target.value })} />
            <datalist id="custom-model-ids">{(check?.models ?? []).map((m) => <option key={m} value={m} />)}</datalist></label>
          <label className="keys-field"><span>API key {looksLocal && <em>not needed for a local server</em>}</span>
            <input type="password" autoComplete="off" spellCheck={false} value={form.api_key} placeholder={looksLocal ? "Leave empty for LM Studio / Ollama" : "Paste the key"} onChange={(e) => setForm({ ...form, api_key: e.target.value })} /></label>
          <label className="keys-field"><span>Special use</span>
            <select value={form.use} onChange={(e) => setForm({ ...form, use: e.target.value })}>
              {uses.map((u) => <option key={u} value={u}>{USE_LABELS[u] ?? u}</option>)}
            </select></label>
          <label className="keys-field"><span>Notes for Nyx <em>optional</em></span>
            <input value={form.use_note} placeholder="e.g. best at long emails" onChange={(e) => setForm({ ...form, use_note: e.target.value })} /></label>
          <div className="keys-field custom-model-form__url">
            <label htmlFor="custom-model-url"><span>Chat completions URL {!urlRequired && <em>optional — replaces {company?.label ?? "the company"}'s address</em>}</span></label>
            <div className="custom-model-form__urlrow">
              <input id="custom-model-url" value={form.chat_url} spellCheck={false}
                placeholder={company?.url || "https://api.example.com/v1  ·  or  http://localhost:1234/v1"}
                onChange={(e) => { setForm({ ...form, chat_url: e.target.value }); setCheck(null); }} />
              <button type="button" className="btn btn-secondary" onClick={() => void checkUrl()} disabled={checking || (urlRequired && !form.chat_url.trim())}>
                {checking ? "Checking…" : "Check"}
              </button>
            </div>
            <span className="keys-notes">The base address is enough (…/v1) — Nyx adds /chat/completions. Servers on this computer (LM Studio, Ollama, llama.cpp) work without a key.</span>
            {check && (
              <p className={`keys-message${check.ok ? "" : " is-error"}`} aria-live="polite">
                {check.ok ? check.detail : `▲ ${check.detail || "No answer from that address."}`}
                {check.url && !check.ok && <> · <code>{check.url}</code></>}
                {check.models.length > 0 && ` · ${check.models.length} models listed — pick one in Model ID`}
              </p>
            )}
          </div>
        </div>
        <label className="custom-model-form__free">
          <input type="checkbox" checked={form.free} onChange={(e) => setForm({ ...form, free: e.target.checked })} />
          <span>Free key — Nyx may use it automatically. Uncheck if it bills you, so Nyx uses it only when you pick it.</span>
        </label>
        <div className="keys-actions">
          <button className="btn btn-primary" disabled={busy || !form.name.trim() || !form.model.trim() || (urlRequired && !form.chat_url.trim())}>{busy ? "Adding…" : "Add Model"}</button>
          {company?.signup && <a className="btn btn-secondary" href={company.signup} target="_blank" rel="noopener noreferrer">Get a {company.label} key ↗</a>}
        </div>
      </form>
      {models.length > 0 && (
        <div className="keys-grid">
          {models.map((m) => (
            <div key={m.name} className="card keys-provider">
              <div className="keys-provider__head">
                <strong>{m.label}</strong>
                {m.is_free && <span className="keys-badge">Free</span>}
              </div>
              <p className="keys-notes"><code>{m.model}</code> · {m.notes}</p>
              <KeyPool provider={m.name} onChanged={() => void load()} />
              <div className="keys-actions">
                <button className="btn btn-secondary" onClick={() => void test(m.name)}>Test</button>
                <button className="btn btn-secondary" onClick={() => void remove(m.name)}>Remove</button>
              </div>
              {tested[m.name] && <p className="keys-message" aria-live="polite">{tested[m.name]}</p>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
