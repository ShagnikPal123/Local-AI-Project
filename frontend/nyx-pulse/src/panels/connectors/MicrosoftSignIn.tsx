/** Sign in to Microsoft 365 with a code (connectors/microsoft_graph.py).
 *
 * Two steps, each shown only when it is next: paste your own app registration's client ID once, then press
 * Sign in — Nyx shows a short code, you type it at microsoft.com/devicelogin and approve. While a code is
 * waiting, this card asks the engine every few seconds whether Microsoft has finished.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import type { Note } from "./types";

interface Pending { user_code: string; verification_uri: string; expires_in: number; products: string[] }
interface Status {
  client_configured: boolean;
  tenant: string;
  accounts: Record<string, string[]>;
  pending: Pending | null;
  last?: { state: string; detail?: string; account?: string };
}

const STEPS = [
  { text: "Open", link: "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade", label: "Entra → App registrations" },
];

export function MicrosoftSignIn({ product, appName, onChanged }: { product: string; appName: string; onChanged: () => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [clientId, setClientId] = useState("");
  const [tenant, setTenant] = useState("common");
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);
  const changed = useRef(onChanged);
  changed.current = onChanged;

  const load = useCallback(async () => {
    const result = await api.get<Status>("/api/connectors/microsoft/status");
    if (!result.ok) { setNote({ ok: false, text: result.error }); return; }
    setStatus(result.data);
    const last = result.data.last;
    if (last?.state === "connected") { setNote({ ok: true, text: `Signed in as ${last.account}.` }); changed.current(); }
    else if (last && ["expired", "declined", "failed"].includes(last.state)) setNote({ ok: false, text: last.detail ?? "Not signed in." });
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!status?.pending) return;
    const id = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(id);
  }, [status?.pending, load]);

  async function saveClient() {
    setBusy(true);
    const result = await api.post<Status>("/api/connectors/microsoft/client", { client_id: clientId.trim(), tenant: tenant.trim() || "common" });
    setBusy(false);
    if (!result.ok) { setNote({ ok: false, text: result.error }); return; }
    setClientId(""); setEditing(false); setNote({ ok: true, text: "Saved. Now sign in." });
    void load();
  }

  async function start() {
    setBusy(true);
    const result = await api.post<{ pending: Pending }>("/api/connectors/microsoft/start", { products: [product] });
    setBusy(false);
    if (!result.ok) { setNote({ ok: false, text: result.error }); return; }
    setNote(null);
    void load();
  }

  if (!status) return <p className="cx-muted">Checking Microsoft sign-in…</p>;
  const needsClient = !status.client_configured || editing;
  const signedIn = Object.entries(status.accounts).filter(([, apps]) => apps.includes(product)).map(([account]) => account);

  return (
    <div className="cx-signin">
      {needsClient ? (
        <form className="cx-form" onSubmit={(e) => { e.preventDefault(); void saveClient(); }}>
          <ol className="cx-steps">
            <li>{STEPS[0].text} <a href={STEPS[0].link} target="_blank" rel="noopener noreferrer">{STEPS[0].label} ↗</a> and choose <b>New registration</b>. Pick <b>Accounts in any organizational directory and personal Microsoft accounts</b>.</li>
            <li>In <b>Authentication</b>, turn on <b>Allow public client flows</b>.</li>
            <li>Copy the <b>Application (client) ID</b> here. Nyx asks for each app's own permissions when you sign in.</li>
          </ol>
          <label className="cx-field"><span>Application (client) ID</span>
            <input value={clientId} onChange={(e) => setClientId(e.target.value)} spellCheck={false} autoComplete="off"
              placeholder="1b2c3d4e-0000-1111-2222-333344445555" /></label>
          <label className="cx-field"><span>Tenant <em>optional</em></span>
            <input value={tenant} onChange={(e) => setTenant(e.target.value)} spellCheck={false} placeholder="common" /></label>
          <div className="cx-actions">
            <button className="btn btn-primary" disabled={busy || !clientId.trim()}>Save Client ID</button>
            {status.client_configured && <button type="button" className="btn btn-secondary" onClick={() => setEditing(false)}>Cancel</button>}
          </div>
        </form>
      ) : status.pending ? (
        <div className="cx-code" aria-live="polite">
          <span className="cx-muted">Go to</span>
          <a className="cx-code__link" href={status.pending.verification_uri} target="_blank" rel="noopener noreferrer">
            {status.pending.verification_uri.replace(/^https:\/\//, "")} ↗
          </a>
          <span className="cx-muted">and enter</span>
          <button type="button" className="cx-code__value" title="Copy the code"
            onClick={() => void navigator.clipboard?.writeText(status.pending!.user_code)}>
            {status.pending.user_code}
          </button>
          <span className="cx-muted">Waiting for Microsoft… this updates by itself ({Math.ceil(status.pending.expires_in / 60)} min left).</span>
        </div>
      ) : (
        <div className="cx-actions">
          <button className="btn btn-primary" disabled={busy} onClick={() => void start()}>
            {signedIn.length ? "Sign In Another Account" : `Sign In with Microsoft`}
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>Change Client ID</button>
        </div>
      )}
      {!needsClient && !status.pending && signedIn.length === 0 && (
        <p className="cx-muted">Signing in asks Microsoft for {appName}'s permissions only. Nyx never sees your password.</p>
      )}
      {note && <p className={`cx-note ${note.ok ? "is-ok" : "is-error"}`} aria-live="polite">{note.text}</p>}
    </div>
  );
}
