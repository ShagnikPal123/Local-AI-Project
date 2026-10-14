/** Connect Gmail with Google's own sign-in — no app password (Request H7).
 *
 * Three steps, each shown only when it is the next one: make a free OAuth client in Google Cloud,
 * paste its ID and secret, then Sign In with Google. The client secret is sent once and never shown.
 *
 * Connectors (Update 1, U24) reuses this same card for every Google app: `products` asks Google only for those apps'
 * permissions, and "connected" then means the addresses that granted them. Without props it is the Gmail card.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { copyToClipboard } from "../components/chat/hooks";
import { onWorkspaceEvent } from "../state/workspaceEvents";

interface RedirectHelp { client_type: string; needs_registration: boolean; message: string; steps?: string[]; redirect_uri: string }
interface Status {
  client_configured: boolean; connected: string[]; redirect_uri: string; products?: Record<string, string[]>;
  client_type?: string; redirect_help?: RedirectHelp;
  all_products?: string[]; enable_all_url?: string;
}

interface Props {
  /** Google apps to ask permission for, e.g. ["sheets"]. Empty: Gmail, as Keys & Models always did. */
  products?: string[];
  title?: string;
  /** The Google Cloud page where this app's API is switched on (step 1). */
  enableUrl?: string;
  apiName?: string;
}

export function GoogleSignIn({ products, title, enableUrl, apiName }: Props = {}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [clientJson, setClientJson] = useState("");
  const [copied, setCopied] = useState(false);
  const [hint, setHint] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [editingClient, setEditingClient] = useState(false);

  const load = useCallback(async () => {
    const result = await api.get<Status>("/api/google/oauth/status");
    if (result.ok) setStatus(result.data);
  }, []);
  useEffect(() => {
    void load();
    return onWorkspaceEvent((event) => { if (event.type === "email.accounts.changed") { setWaiting(false); void load(); } });
  }, [load]);
  useEffect(() => {
    if (!waiting) return;
    const id = window.setInterval(() => void load(), 3000);
    const stop = window.setTimeout(() => setWaiting(false), 10 * 60_000);
    return () => { window.clearInterval(id); window.clearTimeout(stop); };
  }, [waiting, load]);

  async function saveClient() {
    // The downloaded JSON says whether this is a Desktop or Web client, so it is preferred over typing the two values.
    const body = clientJson.trim() ? { client_json: clientJson } : { client_id: clientId, client_secret: clientSecret };
    const result = await api.post<{ client_type: string }>("/api/google/oauth/client", body);
    if (!result.ok) { setMessage({ ok: false, text: result.error }); return; }
    setClientId(""); setClientSecret(""); setClientJson(""); setEditingClient(false);
    setMessage({ ok: true, text: result.data.client_type === "web"
      ? "Saved, but this is a Web application client: add the redirect address below in Google Cloud before signing in."
      : "Saved. Now sign in with Google." });
    void load();
  }

  async function copyRedirect(uri: string) {
    setCopied(await copyToClipboard(uri));
    window.setTimeout(() => setCopied(false), 2000);
  }

  async function signIn(everything = false) {
    // One Google screen for every app: the server already merges scopes, so this only names them all.
    const asked = everything ? status?.all_products ?? [] : products ?? [];
    const result = await api.post<{ auth_url: string }>("/api/google/oauth/start", { login_hint: hint, products: asked });
    if (!result.ok) { setMessage({ ok: false, text: result.error }); return; }
    window.open(result.data.auth_url, "_blank", "noopener");
    setWaiting(true);
    setMessage({ ok: true, text: "Finish in the Google tab that opened. This updates by itself when you're done." });
  }

  if (!status) return null;
  const needsClient = !status.client_configured || editingClient;
  const wanted = products ?? [];
  const otherApp = wanted.length > 0 && !wanted.includes("gmail");
  const connected = wanted.length
    ? Object.entries(status.products ?? {}).filter(([, granted]) => wanted.every((p) => granted.includes(p))).map(([address]) => address)
    : status.connected;

  return (
    <div className="card keys-provider google-signin">
      <div className="keys-provider__head">
        <strong>{title ?? "Gmail with Google sign-in"}</strong>
        <span className="keys-badge">No app password</span>
        {connected.length > 0 && <span className="keys-status is-ok">✓ {connected.join(", ")}</span>}
      </div>
      <p className="keys-notes">
        {otherApp ? "" : "Use this when Google won't give you an app password. "}You approve Nyx on Google's own page; Nyx never sees your Google password.
      </p>

      {needsClient ? (
        <>
          <ol className="google-signin__steps">
            <li>Open <a href={enableUrl ?? "https://console.cloud.google.com/apis/library/gmail.googleapis.com"} target="_blank" rel="noopener noreferrer">Google Cloud → {apiName ?? "Gmail API"} ↗</a> and click <b>Enable</b> (make a project if asked — it's free).</li>
            <li>In <a href="https://console.cloud.google.com/auth/audience" target="_blank" rel="noopener noreferrer">Google Auth Platform → Audience ↗</a>, choose <b>External</b>, keep it in <b>Testing</b>, and add your Gmail address under <b>Test users</b>.</li>
            <li>In <a href="https://console.cloud.google.com/auth/clients" target="_blank" rel="noopener noreferrer">Clients ↗</a>, create a client of type <b>Desktop app</b> (not Web application), then choose <b>Download JSON</b> and paste the file's contents below. Or copy its Client ID and Client secret into the two boxes.</li>
          </ol>
          <form className="keys-form" onSubmit={(e) => { e.preventDefault(); void saveClient(); }}>
            <label className="keys-field"><span>Client JSON <em>recommended</em></span>
              <textarea value={clientJson} rows={3} spellCheck={false} autoComplete="off" placeholder='{"installed":{"client_id":"…"}}' onChange={(e) => setClientJson(e.target.value)} /></label>
            <label className="keys-field"><span>Client ID <em>or paste these two instead</em></span>
              <input value={clientId} spellCheck={false} autoComplete="off" placeholder="1234-abc.apps.googleusercontent.com" onChange={(e) => setClientId(e.target.value)} /></label>
            <label className="keys-field"><span>Client secret</span>
              <input type="password" value={clientSecret} spellCheck={false} autoComplete="off" placeholder="GOCSPX-…" onChange={(e) => setClientSecret(e.target.value)} /></label>
            <div className="keys-actions">
              <button className="btn btn-primary" disabled={!clientJson.trim() && (!clientId.trim() || !clientSecret.trim())}>Save Client</button>
              {status.client_configured && <button type="button" className="btn btn-secondary" onClick={() => setEditingClient(false)}>Cancel</button>}
            </div>
          </form>
        </>
      ) : (
        <div className="keys-form">
          {otherApp && enableUrl && (
            <p className="keys-notes">First turn on the <a href={enableUrl} target="_blank" rel="noopener noreferrer">{apiName ?? "API"} ↗</a> in the same Google Cloud project. Google then asks only for this app's permission.</p>
          )}
          <label className="keys-field"><span>{otherApp ? "Google account" : "Gmail address"} <em>optional</em></span>
            <input value={hint} placeholder="you@gmail.com" onChange={(e) => setHint(e.target.value)} /></label>
          <div className="keys-actions">
            <button className="btn btn-primary google-signin__button" onClick={() => void signIn()} disabled={waiting}>
              {waiting ? "Waiting for Google…" : connected.length ? "Sign In Another Account" : "Sign In with Google"}
            </button>
            {(status.all_products?.length ?? 0) > 1 && (
              <button type="button" className="btn btn-secondary" onClick={() => void signIn(true)} disabled={waiting}>
                Connect All Google Apps
              </button>
            )}
            <button type="button" className="btn btn-secondary" onClick={() => setEditingClient(true)}>Change Client</button>
          </div>
          {status.redirect_help?.needs_registration && (
            <div className="keys-notes google-signin__redirect" role="note">
              <p>{status.redirect_help.message}</p>
              <p>Redirect address: <code>{status.redirect_help.redirect_uri}</code>{" "}
                <button type="button" className="btn btn-secondary" onClick={() => void copyRedirect(status.redirect_help!.redirect_uri)}>{copied ? "Copied" : "Copy"}</button></p>
              <ul>{(status.redirect_help.steps ?? []).map((step) => <li key={step}>{step}</li>)}</ul>
            </div>
          )}
          {status.enable_all_url && (
            <p className="keys-notes">
              <b>Connect All Google Apps</b> asks for Gmail, Calendar, Drive, Docs, Sheets, Slides and Tasks in one Google screen.
              Turn their APIs on first in one go: <a href={status.enable_all_url} target="_blank" rel="noopener noreferrer">Enable all Google APIs ↗</a>.
            </p>
          )}
          <p className="keys-notes">Google may say the app isn't verified — that's your own test app. Choose <b>Continue</b>.</p>
        </div>
      )}
      {message && <p className={`keys-message ${message.ok ? "is-ok" : "is-error"}`} aria-live="polite">{message.text}</p>}
    </div>
  );
}
