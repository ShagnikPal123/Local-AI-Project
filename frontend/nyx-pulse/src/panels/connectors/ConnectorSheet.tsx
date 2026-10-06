/** One connector, opened from the grid: what it is, how to connect it, what Nyx can do with it.
 *
 * The connect area follows the connector's kind: a token form (keys go to the engine once and come back only as
 * their last four characters), Google's or Microsoft's own sign-in, a switch for keyless ones, or a pointer to the
 * tools for apps built into Nyx. Test makes one read-only call; nothing in the other app changes.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { GoogleSignIn } from "../GoogleSignIn";
import { MicrosoftSignIn } from "./MicrosoftSignIn";
import { Mark } from "./Mark";
import type { Connector, ConnectorAction, Note } from "./types";

const KIND_LABEL: Record<string, string> = {
  rest: "API", mcp: "MCP server", oauth_google: "Google sign-in", oauth_microsoft: "Microsoft sign-in",
  builtin: "Built into Nyx", website: "Website", webhook: "Webhook", provider: "AI model", model: "AI model",
};

function api_name(connector: Connector): string {
  const product = connector.name.replace(/^Google /, "");
  return connector.google_product === "calendar" ? "Google Calendar API" : `${product} API`;
}

function TokenForm({ connector, onSaved }: { connector: Connector; onSaved: (c: Connector) => void }) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(connector.fields.filter((f) => f.default).map((f) => [f.key, f.default ?? ""])));
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Note>(null);
  const connected = connector.connected;

  async function save() {
    setBusy(true);
    const fields = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim()));
    const result = await api.post<{ connector: Connector }>(`/api/connectors/${connector.id}/connect`, { fields });
    setBusy(false);
    if (!result.ok) { setNote({ ok: false, text: result.error }); return; }
    setValues({});
    setNote({ ok: true, text: connected ? "Updated." : `${connector.name} is connected.` });
    onSaved(result.data.connector);
  }

  if (connector.fields.length === 0) return null;
  return (
    <form className="cx-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
      {connector.fields.map((field) => {
        const saved = connector.saved?.[field.key];
        return (
          <label key={field.key} className="cx-field">
            <span>
              {field.label}{!field.required && <em> optional</em>}
              {saved && <em className="is-ok"> — saved {field.secret ? saved : `(${saved})`}</em>}
              {field.help_url && (
                <a className="cx-field__help" href={field.help_url} target="_blank" rel="noopener noreferrer">Get it ↗</a>
              )}
            </span>
            {field.choices ? (
              <select value={values[field.key] ?? saved ?? field.default ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}>
                {field.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
              </select>
            ) : (
              <input type={field.secret ? "password" : field.kind === "email" ? "email" : "text"} autoComplete="off"
                spellCheck={false} value={values[field.key] ?? ""}
                placeholder={saved ? "Leave empty to keep" : field.placeholder ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))} />
            )}
          </label>
        );
      })}
      <div className="cx-actions">
        <button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : connected ? "Update" : "Connect"}</button>
      </div>
      {note && <p className={`cx-note ${note.ok ? "is-ok" : "is-error"}`} aria-live="polite">{note.text}</p>}
    </form>
  );
}

function MailPasswordForm({ onSaved }: { onSaved: () => void }) {
  const [address, setAddress] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);

  async function add() {
    setBusy(true);
    setNote({ ok: true, text: password ? "Signing in to check the password…" : "Saving…" });
    const result = await api.post<{ account: { address: string } }>("/api/email/accounts",
      { address: address.trim(), ...(password.trim() ? { app_password: password } : {}) });
    setBusy(false);
    if (!result.ok) { setNote({ ok: false, text: result.error }); return; }
    setAddress(""); setPassword("");
    setNote({ ok: true, text: `Added ${result.data.account.address}.` });
    onSaved();
  }

  return (
    <form className="cx-form" onSubmit={(e) => { e.preventDefault(); void add(); }}>
      <label className="cx-field"><span>Address</span>
        <input type="email" autoComplete="off" value={address} placeholder="you@example.com" onChange={(e) => setAddress(e.target.value)} /></label>
      <label className="cx-field"><span>App password
        <a className="cx-field__help" href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer">Gmail ↗</a>
        <a className="cx-field__help" href="https://account.live.com/proofs/AppPassword" target="_blank" rel="noopener noreferrer">Outlook.com ↗</a></span>
        <input type="password" autoComplete="off" value={password} placeholder="16 letters, spaces are fine" onChange={(e) => setPassword(e.target.value)} /></label>
      <div className="cx-actions"><button className="btn btn-secondary" disabled={busy || !address.trim()}>Add Mailbox</button></div>
      {note && <p className={`cx-note ${note.ok ? "is-ok" : "is-error"}`} aria-live="polite">{note.text}</p>}
    </form>
  );
}

function Actions({ actions, tools }: { actions: ConnectorAction[]; tools?: string[] }) {
  if (actions.length === 0 && !tools?.length) return null;
  return (
    <section className="cx-section">
      <h3 className="cx-h3">What Nyx can do with it</h3>
      {tools && tools.length > 0 && (
        <p className="cx-muted">In chat, Nyx uses its own tools for this: {tools.join(", ")}.</p>
      )}
      <ul className="cx-actions-list">
        {actions.map((action) => (
          <li key={action.id}>
            <code>{action.id}</code>
            <span>{action.description}</span>
            {action.write && <span className="cx-pill is-warn">changes things — asks you first</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ConnectorSheet({ connector, onClose, onChanged, onAdd }: {
  connector: Connector;
  onClose: () => void;
  onChanged: () => void;
  onAdd: (text: string) => void;
}) {
  const [current, setCurrent] = useState<Connector>(connector);
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState<"" | "test" | "remove" | "toggle">("");
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => { setCurrent((c) => ({ ...connector, actions: c.id === connector.id && c.actions.some((a) => a.path) ? c.actions : connector.actions })); }, [connector]);
  useEffect(() => {
    let alive = true;
    void api.get<{ connector: Connector }>(`/api/connectors/catalog/${encodeURIComponent(connector.id)}`).then((r) => {
      if (alive && r.ok) setCurrent(r.data.connector);
    });
    return () => { alive = false; };
  }, [connector.id, connector.connected]);
  useEffect(() => {
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function test() {
    setBusy("test");
    setNote({ ok: true, text: "Testing with one read-only call…" });
    const result = await api.post<{ ok: boolean; message: string }>(`/api/connectors/${current.id}/test`, {}, 40_000);
    setBusy("");
    setNote(result.ok ? { ok: result.data.ok, text: result.data.message } : { ok: false, text: result.error });
  }

  async function disconnect(account = "") {
    const signIn = current.kind === "oauth_google" || current.kind === "oauth_microsoft";
    const warn = signIn
      ? `Sign ${account || "this account"} out? Every ${current.kind === "oauth_google" ? "Google" : "Microsoft"} app connected with it stops working in Nyx.`
      : current.kind === "provider" ? `Remove the ${current.name} key from Keys & Models?` : `Disconnect ${current.name}? Its saved key is deleted from this PC.`;
    if (!window.confirm(warn)) return;
    setBusy("remove");
    const result = await api.del<{ removed: boolean }>(`/api/connectors/${current.id}${account ? `?account=${encodeURIComponent(account)}` : ""}`);
    setBusy("");
    setNote(result.ok ? { ok: true, text: "Disconnected." } : { ok: false, text: result.error });
    onChanged();
  }

  async function turnOn() {
    setBusy("toggle");
    const result = await api.post<{ connector: Connector }>(`/api/connectors/${current.id}/connect`, { fields: {} });
    setBusy("");
    if (result.ok) { setCurrent((c) => ({ ...c, ...result.data.connector, actions: c.actions })); setNote({ ok: true, text: "On. Nyx can use it in chat now." }); onChanged(); }
    else setNote({ ok: false, text: result.error });
  }

  const c = current;
  const keyless = c.fields.length === 0 && (c.kind === "rest" || c.kind === "mcp");
  const signIn = c.kind === "oauth_google" || c.kind === "oauth_microsoft";
  const showTest = c.connected && c.kind !== "builtin" && (!signIn || c.accounts.length > 0);
  const showDisconnect = c.connected && !signIn && c.kind !== "builtin";

  return (
    <div className="cx-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={dialog} tabIndex={-1} className="cx-sheet" role="dialog" aria-modal="true" aria-labelledby="cx-sheet-title">
        <header className="cx-sheet__head">
          <Mark connector={c} size="lg" />
          <div className="cx-sheet__title">
            <h2 id="cx-sheet-title">{c.name}</h2>
            <div className="cx-sheet__meta">
              <span className={`cx-pill ${c.connected ? "is-ok" : ""}`}>{c.connected ? `Connected${c.how ? ` · ${c.how}` : ""}` : c.template ? "Starter" : "Not connected"}</span>
              <span className="cx-pill">{KIND_LABEL[c.kind] ?? c.kind}</span>
              {c.writes && <span className="cx-pill is-warn">can make changes</span>}
              {c.paid && <span className="cx-pill">paid</span>}
              {c.origin === "custom" && <span className="cx-pill">yours</span>}
            </div>
          </div>
          <button className="cx-close" onClick={onClose} aria-label="Close">×</button>
        </header>

        <p className="cx-lede">{c.description}</p>
        {c.note && <p className="cx-callout">{c.note}</p>}
        {c.can.length > 0 && (
          <ul className="cx-can">{c.can.map((item) => <li key={item}>{item}</li>)}</ul>
        )}

        <section className="cx-section">
          <h3 className="cx-h3">{c.connected ? "Connection" : "Connect"}</h3>

          {c.template && (
            <div className="cx-actions">
              <p className="cx-muted">Type its name, website, API address or MCP server URL and Nyx finds it or builds the connection.</p>
              <button className="btn btn-primary" onClick={() => onAdd("")}>Add {c.name.replace(/^Any /, "a ")}</button>
            </div>
          )}

          {c.kind === "oauth_google" && (
            <>
              <GoogleSignIn products={[c.google_product ?? "gmail"]} title={`${c.name} with Google sign-in`}
                enableUrl={c.enable_url} apiName={api_name(c)} />
              {c.google_product === "gmail" && (
                <details className="cx-alt">
                  <summary>Or use an app password</summary>
                  <p className="cx-muted">For any mailbox — Gmail, Outlook.com, iCloud — when sign-in isn't possible. Nyx reads and sends with IMAP and SMTP.</p>
                  <MailPasswordForm onSaved={onChanged} />
                </details>
              )}
            </>
          )}

          {c.kind === "oauth_microsoft" && (
            <MicrosoftSignIn product={c.microsoft_product ?? "outlook"} appName={c.name} onChanged={onChanged} />
          )}

          {c.kind === "builtin" && (
            c.id === "email" ? (
              <>
                {c.accounts.length > 0 && <p className="cx-muted">Mailboxes: {c.accounts.join(", ")}.</p>}
                <MailPasswordForm onSaved={onChanged} />
              </>
            ) : (
              <p className="cx-muted">{c.connected ? "Built into Nyx and ready — nothing to sign in to." : c.note ?? "Built into Nyx; not available on this PC right now."}</p>
            )
          )}

          {!c.template && ["rest", "mcp", "webhook", "provider", "model", "website"].includes(c.kind) && (
            keyless ? (
              c.connected ? <p className="cx-muted">On. No key needed.</p> : (
                <div className="cx-actions">
                  <button className="btn btn-primary" disabled={busy === "toggle"} onClick={() => void turnOn()}>Turn On</button>
                  <span className="cx-muted">No key needed.</span>
                </div>
              )
            ) : c.origin === "custom" ? (
              <p className="cx-muted">{c.base_url || c.mcp_url}</p>
            ) : (
              <TokenForm key={c.id} connector={c} onSaved={(next) => { setCurrent((prev) => ({ ...prev, ...next, actions: prev.actions })); onChanged(); }} />
            )
          )}

          {(c.accounts.length > 0 || (c.mail_accounts?.length ?? 0) > 0) && c.kind !== "builtin" && (
            <ul className="cx-accounts">
              {c.accounts.map((account) => (
                <li key={account}><span>{account}</span>
                  <button className="btn btn-secondary" disabled={busy === "remove"} onClick={() => void disconnect(account)}>Sign Out</button></li>
              ))}
              {(c.mail_accounts ?? []).map((account) => (
                <li key={account}><span>{account}</span><span className="cx-muted">app password · manage in Keys & Models</span></li>
              ))}
            </ul>
          )}

          {(showTest || showDisconnect) && (
            <div className="cx-actions">
              {showTest && <button className="btn btn-secondary" disabled={busy !== ""} onClick={() => void test()}>{busy === "test" ? "Testing…" : "Test"}</button>}
              {showDisconnect && (
                <button className="btn btn-secondary" disabled={busy !== ""} onClick={() => void disconnect()}>
                  {keyless ? "Turn Off" : c.origin === "custom" ? "Remove" : "Disconnect"}
                </button>
              )}
            </div>
          )}
          {note && <p className={`cx-note ${note.ok ? "is-ok" : "is-error"}`} aria-live="polite">{note.text}</p>}
        </section>

        <Actions actions={c.actions} tools={c.tools} />

        <footer className="cx-sheet__foot">
          {c.docs_url && <a href={c.docs_url} target="_blank" rel="noopener noreferrer">API documentation ↗</a>}
          <span className="cx-muted">Type <code>&amp;{c.id}</code> in a chat to use it on purpose.</span>
        </footer>
      </div>
    </div>
  );
}
