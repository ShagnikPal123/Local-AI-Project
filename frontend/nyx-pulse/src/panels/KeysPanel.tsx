/** Keys & Models — every API key in one place, and which model does which job.
 *
 * The owner asked to add keys "for multiple things" (NVIDIA's free keys from
 * build.nvidia.com, AWS, and the rest) and to pick "an AI model from NVIDIA for
 * image check or an AWS one for reading text", with both him and Nyx saying which
 * model was used. Nyx can make the same assignments from chat
 * (`set_model_purpose`); `model_roles.changed` and `keys.changed` keep this panel
 * in step with it.
 *
 * Functional on purpose: styling is left to the design pass (DESIGN_HANDOFF.md).
 * Keys are sent once and never shown again — the server only returns last4.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { CustomModelsSection, KeyAlerts, KeyPool } from "./KeyPoolSections";
import { LocalModels, ModelFinder } from "./LocalModelsSections";
import { GoogleSignIn } from "./GoogleSignIn";

interface KeyField {
  name: string;
  label: string;
  secret: boolean;
  set: boolean;
  hint: string;
  optional?: boolean;
}

interface ProviderKey {
  provider: string;
  label: string;
  configured: boolean;
  last4: string;
  free: boolean;
  signup_url: string;
  notes: string;
  fields: KeyField[];
  used_by: string[];
  keyless?: boolean;
  always_on?: boolean;
}

interface Role {
  id: string;
  title: string;
  description: string;
  job: "text" | "vision" | "image";
  provider: string;
  model: string;
  label: string;
  assigned_by: string;
  configured: boolean;
  builtin: boolean;
}

interface CatalogModel {
  id: string;
  jobs: string[];
}

type TestState = { ok: boolean; detail: string; busy?: boolean };

function ProviderCard({ item, onSaved }: { item: ProviderKey; onSaved: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<TestState | null>(null);

  async function save() {
    const body = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim()));
    if (Object.keys(body).length === 0) return;
    setBusy(true);
    const result = await api.post(`/api/keys/${item.provider}`, body);
    setBusy(false);
    if (result.ok) {
      setValues({});
      setMessage({ ok: true, detail: "Saved. Nyx uses it from the next request." });
      onSaved();
    } else {
      setMessage({ ok: false, detail: result.error });
    }
  }

  async function test() {
    setMessage({ ok: true, detail: "Testing…", busy: true });
    const result = await api.post<{ ok: boolean; detail: string }>(`/api/keys/${item.provider}/test`);
    setMessage(result.ok ? { ok: result.data.ok, detail: result.data.detail } : { ok: false, detail: result.error });
  }

  async function remove() {
    if (!window.confirm(`Remove the saved ${item.label} key? Keys in .env.local are not changed.`)) return;
    const result = await api.del(`/api/keys/${item.provider}`);
    setMessage(result.ok ? { ok: true, detail: "Removed." } : { ok: false, detail: result.error });
    onSaved();
  }

  const keyless = item.keyless ?? item.fields.length === 0;
  const alwaysOn = item.always_on === true;  // Big Kahuna: Nyx's own brain, no key, runs whenever Nyx runs

  return (
    <div className="card keys-provider" data-configured={item.configured}>
      <div className="keys-provider__head">
        <strong>{item.label}</strong>
        {alwaysOn && <span className="keys-badge">Main brain</span>}
        {item.free && <span className="keys-badge">Free</span>}
        <span className={`keys-status ${item.configured || alwaysOn ? "is-ok" : ""}`}>
          {alwaysOn
            ? "Always on — no key needed"
            : keyless
              ? (item.configured ? "Ready" : "Not running")
              : item.configured ? `Key •••• ${item.last4 || "saved"}` : "No key"}
        </span>
      </div>
      {item.notes && <p className="keys-notes">{item.notes}</p>}
      {item.used_by.length > 0 && <p className="keys-notes">Used for: {item.used_by.join(", ")}</p>}
      {!keyless && item.configured && <KeyPool provider={item.provider} onChanged={onSaved} />}

      {!keyless && (
        <form className="keys-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          {item.fields.map((field) => (
            <label key={field.name} className="keys-field">
              <span>
                {field.label}
                {field.set && <em> — saved{field.hint ? ` (${field.secret ? "…" : ""}${field.hint})` : ""}</em>}
              </span>
              <input
                type={field.secret ? "password" : "text"}
                autoComplete="off"
                spellCheck={false}
                value={values[field.name] ?? ""}
                placeholder={field.set ? "Leave empty to keep" : field.optional ? "Optional" : ""}
                onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
              />
            </label>
          ))}
          <div className="keys-actions">
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
            {item.configured && <button className="btn btn-secondary" type="button" onClick={() => void test()}>Test</button>}
            {item.configured && <button className="btn btn-secondary" type="button" onClick={() => void remove()}>Remove</button>}
            {item.signup_url && (
              <a className="btn btn-secondary" href={item.signup_url} target="_blank" rel="noopener noreferrer">
                {item.free ? "Get a free key" : "Get a key"} ↗
              </a>
            )}
          </div>
        </form>
      )}
      {keyless && (item.configured || alwaysOn) && (
        <div className="keys-actions">
          <button className="btn btn-secondary" type="button" onClick={() => void test()}>
            {alwaysOn ? "Check" : "Test"}
          </button>
        </div>
      )}
      {message && (
        <p className={`keys-message ${message.ok ? "is-ok" : "is-error"}`} aria-live="polite">{message.detail}</p>
      )}
    </div>
  );
}

function RoleRow({ role, providers, onChanged }: { role: Role; providers: ProviderKey[]; onChanged: () => void }) {
  const [provider, setProvider] = useState(role.provider);
  const [model, setModel] = useState(role.model);
  const [label, setLabel] = useState(role.label);
  const [catalog, setCatalog] = useState<CatalogModel[]>([]);
  const [state, setState] = useState<TestState | null>(null);

  useEffect(() => { setProvider(role.provider); setModel(role.model); setLabel(role.label); }, [role]);

  useEffect(() => {
    let alive = true;
    void api.get<{ models: CatalogModel[] }>(`/api/models/catalog?provider=${encodeURIComponent(provider)}&job=${role.job}`)
      .then((result) => { if (alive && result.ok) setCatalog(result.data.models); });
    return () => { alive = false; };
  }, [provider, role.job]);

  const dirty = provider !== role.provider || model !== role.model || label !== role.label;
  const options = providers.filter((p) => role.job === "image" || p.provider !== "pollinations");

  async function save() {
    setState({ ok: true, detail: "Saving…", busy: true });
    const result = await api.put(`/api/model-roles/${role.id}`, {
      provider, model, label: label === role.label && provider !== role.provider ? "" : label,
    });
    setState(result.ok ? { ok: true, detail: "Saved — Nyx will use and name this model." } : { ok: false, detail: result.error });
    if (result.ok) onChanged();
  }

  async function test() {
    setState({ ok: true, detail: "Running a tiny test…", busy: true });
    const result = await api.post<{ ok: boolean; detail: string; label: string; ms?: number }>(`/api/model-roles/${role.id}/test`);
    if (!result.ok) { setState({ ok: false, detail: result.error }); return; }
    const d = result.data;
    setState({ ok: d.ok, detail: `${d.label}${d.ms ? ` · ${(d.ms / 1000).toFixed(1)}s` : ""}: ${d.detail}` });
  }

  async function reset() {
    const result = await api.del(`/api/model-roles/${role.id}`);
    if (result.ok) onChanged();
  }

  return (
    <div className="card keys-role">
      <div className="keys-role__head">
        <strong>{role.title}</strong>
        <span className="keys-badge">{role.job}</span>
        {!role.configured && <span className="keys-status">needs a {role.provider} key</span>}
        {role.assigned_by === "assistant" && <span className="keys-notes">set by Nyx</span>}
      </div>
      {role.description && <p className="keys-notes">{role.description}</p>}
      <div className="keys-role__grid">
        <label className="keys-field">
          <span>Provider</span>
          <select value={provider} onChange={(e) => { setProvider(e.target.value); setModel(""); }}>
            {options.map((p) => (
              <option key={p.provider} value={p.provider}>
                {p.label}{p.configured ? "" : " (no key)"}
              </option>
            ))}
          </select>
        </label>
        <label className="keys-field">
          <span>Model</span>
          <input list={`models-${role.id}`} value={model} placeholder="Default for this provider"
            onChange={(e) => setModel(e.target.value)} spellCheck={false} />
          <datalist id={`models-${role.id}`}>
            {catalog.map((m) => <option key={m.id} value={m.id} />)}
          </datalist>
        </label>
        <label className="keys-field">
          <span>Announce as</span>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. NVIDIA Vision" />
        </label>
      </div>
      <div className="keys-actions">
        <button className="btn btn-primary" disabled={!dirty} onClick={() => void save()}>Save</button>
        <button className="btn btn-secondary" onClick={() => void test()}>Test</button>
        <button className="btn btn-secondary" onClick={() => void reset()}>{role.builtin ? "Reset" : "Delete"}</button>
      </div>
      {state && <p className={`keys-message ${state.ok ? "is-ok" : "is-error"}`} aria-live="polite">{state.detail}</p>}
    </div>
  );
}

function NewRole({ providers, onCreated }: { providers: ProviderKey[]; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [job, setJob] = useState<"text" | "vision" | "image">("text");
  const [provider, setProvider] = useState("gemini");
  const [error, setError] = useState("");

  async function create() {
    if (!name.trim()) return;
    const result = await api.put(`/api/model-roles/${encodeURIComponent(name.trim().toLowerCase().replace(/\s+/g, "_"))}`,
      { provider, job, title: name.trim() });
    if (result.ok) { setName(""); setError(""); onCreated(); } else setError(result.error);
  }

  return (
    <form className="card keys-role" onSubmit={(e) => { e.preventDefault(); void create(); }}>
      <strong>Add a job</strong>
      <p className="keys-notes">For example “Translation” on Gemini, or “Receipts” (vision) on NVIDIA.</p>
      <div className="keys-role__grid">
        <label className="keys-field"><span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Translation" /></label>
        <label className="keys-field"><span>Kind</span>
          <select value={job} onChange={(e) => setJob(e.target.value as typeof job)}>
            <option value="text">Text</option><option value="vision">Looks at images</option><option value="image">Makes images</option>
          </select></label>
        <label className="keys-field"><span>Provider</span>
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            {providers.map((p) => <option key={p.provider} value={p.provider}>{p.label}</option>)}
          </select></label>
      </div>
      <div className="keys-actions"><button className="btn btn-primary" type="submit">Add</button></div>
      {error && <p className="keys-message is-error">{error}</p>}
    </form>
  );
}

interface EmailAccount {
  id: string;
  address: string;
  provider: string;
  configured: boolean;
  send: string;
  read: string;
  app_password_url: string;
}

const SEND_WAYS: Record<string, string> = {
  smtp: "sends directly",
  outlook_app: "sends through Outlook",
  compose: "opens a ready draft",
};

function EmailSection() {
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [outlook, setOutlook] = useState(false);
  const [form, setForm] = useState({ address: "", app_password: "", imap_host: "", smtp_host: "" });
  const [custom, setCustom] = useState(false);
  const [state, setState] = useState<TestState | null>(null);

  const load = useCallback(async () => {
    const result = await api.get<{ accounts: EmailAccount[]; outlook_app_available: boolean }>("/api/email/accounts");
    if (result.ok) { setAccounts(result.data.accounts); setOutlook(result.data.outlook_app_available); }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => onWorkspaceEvent((event) => {
    if (event.type === "email.accounts.changed") void load();
  }), [load]);

  async function add() {
    if (!form.address.trim()) return;
    setState({ ok: true, detail: form.app_password ? "Signing in to check the password…" : "Saving…", busy: true });
    const body = Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim()));
    const result = await api.post<{ account: EmailAccount }>("/api/email/accounts", body);
    if (result.ok) {
      setForm({ address: "", app_password: "", imap_host: "", smtp_host: "" });
      setCustom(false);
      setState({ ok: true, detail: `Added ${result.data.account.address} — Nyx ${SEND_WAYS[result.data.account.send]}.` });
      void load();
    } else {
      setState({ ok: false, detail: result.error });
      if (/IMAP and SMTP/.test(result.error)) setCustom(true);
    }
  }

  async function test(account: EmailAccount) {
    setState({ ok: true, detail: `Checking ${account.address}…`, busy: true });
    const result = await api.post<{ ok: boolean; detail: string }>(`/api/email/test/${account.id}`);
    setState(result.ok ? { ok: result.data.ok, detail: result.data.detail } : { ok: false, detail: result.error });
  }

  async function remove(account: EmailAccount) {
    if (!window.confirm(`Remove ${account.address} from Nyx? Your mailbox is not touched.`)) return;
    const result = await api.del(`/api/email/accounts/${account.id}`);
    if (result.ok) void load(); else setState({ ok: false, detail: result.error });
  }

  return (
    <section className="keys-section">
      <h2 className="keys-heading">Email</h2>
      <p className="keys-notes">
        Add your address and an <em>app password</em> (not your normal password) so Nyx can read, send and reply.
        Without one, Nyx {outlook ? "sends through Outlook on this PC" : "opens a ready-to-send draft for you"}.{" "}
        App passwords: <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer">Gmail</a>,{" "}
        <a href="https://account.live.com/proofs/AppPassword" target="_blank" rel="noopener noreferrer">Outlook.com</a>,{" "}
        <a href="https://account.apple.com/account/manage" target="_blank" rel="noopener noreferrer">iCloud</a>.
      </p>
      <div className="keys-grid">
        <GoogleSignIn />
        {accounts.map((account) => (
          <div key={account.id} className="card keys-provider" data-configured={account.configured}>
            <div className="keys-provider__head">
              <strong>{account.address}</strong>
              <span className="keys-badge">{account.provider}</span>
              <span className={`keys-status ${account.configured ? "is-ok" : ""}`}>
                {account.configured ? "Read + send" : "No app password"}
              </span>
            </div>
            <p className="keys-notes">Nyx {SEND_WAYS[account.send] ?? account.send}{account.read === "imap" ? " and can read this inbox" : ""}.</p>
            <div className="keys-actions">
              {account.configured && <button className="btn btn-secondary" type="button" onClick={() => void test(account)}>Test</button>}
              {!account.configured && account.app_password_url && (
                <a className="btn btn-secondary" href={account.app_password_url} target="_blank" rel="noopener noreferrer">Make an app password ↗</a>
              )}
              <button className="btn btn-secondary" type="button" onClick={() => void remove(account)}>Remove</button>
            </div>
          </div>
        ))}
        <form className="card keys-provider" onSubmit={(e) => { e.preventDefault(); void add(); }}>
          <strong>Add an email account</strong>
          <label className="keys-field"><span>Address</span>
            <input type="email" autoComplete="off" value={form.address} placeholder="you@gmail.com"
              onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))} /></label>
          <label className="keys-field"><span>App password</span>
            <input type="password" autoComplete="off" value={form.app_password} placeholder="16 letters, spaces are fine"
              onChange={(e) => setForm((f) => ({ ...f, app_password: e.target.value }))} /></label>
          {custom && (
            <>
              <label className="keys-field"><span>IMAP server</span>
                <input value={form.imap_host} placeholder="imap.example.com"
                  onChange={(e) => setForm((f) => ({ ...f, imap_host: e.target.value }))} /></label>
              <label className="keys-field"><span>SMTP server</span>
                <input value={form.smtp_host} placeholder="smtp.example.com"
                  onChange={(e) => setForm((f) => ({ ...f, smtp_host: e.target.value }))} /></label>
            </>
          )}
          <div className="keys-actions">
            <button className="btn btn-primary" type="submit" disabled={state?.busy}>Add</button>
            {!custom && <button className="btn btn-secondary" type="button" onClick={() => setCustom(true)}>Other provider</button>}
          </div>
        </form>
      </div>
      {state && <p className={`keys-message ${state.ok ? "is-ok" : "is-error"}`} aria-live="polite">{state.detail}</p>}
    </section>
  );
}

export function KeysPanel() {
  const [providers, setProviders] = useState<ProviderKey[] | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [keys, roleData] = await Promise.all([
      api.get<{ providers: ProviderKey[] }>("/api/keys"),
      api.get<{ roles: Role[] }>("/api/model-roles"),
    ]);
    if (keys.ok) setProviders(keys.data.providers); else setError(keys.error);
    if (roleData.ok) setRoles(roleData.data.roles);
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => onWorkspaceEvent((event) => {
    if (event.type === "model_roles.changed" || event.type === "keys.changed") void load();
  }), [load]);

  const ordered = useMemo(
    () => (providers ?? []).slice().sort((a, b) => Number(b.configured) - Number(a.configured) || Number(b.free) - Number(a.free)),
    [providers],
  );

  if (error && !providers) return <PanelShell title="Keys & Models"><ErrorState error={error} /></PanelShell>;
  if (!providers) return <PanelShell title="Keys & Models"><Loading what="Reading keys" /></PanelShell>;

  return (
    <PanelShell title="Keys & Models" subtitle="Add API keys, then choose which model does each job">
      <KeyAlerts />
      <section className="keys-section">
        <h2 className="keys-heading">Which model does which job</h2>
        <p className="keys-notes">
          Nyx uses exactly these models for these jobs and tells you which one did the work. You can also just ask
          in chat: “use NVIDIA’s Llama Vision for image checks”.
        </p>
        <div className="keys-grid">
          {roles.map((role) => <RoleRow key={role.id} role={role} providers={providers} onChanged={() => void load()} />)}
          <NewRole providers={providers} onCreated={() => void load()} />
        </div>
      </section>
      <section className="keys-section">
        <h2 className="keys-heading">API keys</h2>
        <p className="keys-notes">
          Keys are stored on this computer and never shown again. Free keys: {" "}
          <a href="https://build.nvidia.com/models" target="_blank" rel="noopener noreferrer">NVIDIA (build.nvidia.com)</a>,{" "}
          <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer">Google Gemini</a>,{" "}
          <a href="https://console.groq.com/keys" target="_blank" rel="noopener noreferrer">Groq</a>.
        </p>
        <div className="keys-grid">
          {ordered.map((item) => <ProviderCard key={item.provider} item={item} onSaved={() => void load()} />)}
        </div>
      </section>
      <CustomModelsSection />
      <LocalModels />
      <EmailSection />
      <ModelFinder />
    </PanelShell>
  );
}
