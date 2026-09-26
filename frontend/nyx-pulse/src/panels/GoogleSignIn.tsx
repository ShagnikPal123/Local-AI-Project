/** Connect Gmail with Google's own sign-in — no app password (Request H7).
 *
 * Three steps, each shown only when it is the next one: make a free OAuth client in Google Cloud,
 * paste its ID and secret, then Sign In with Google. The client secret is sent once and never shown.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { onWorkspaceEvent } from "../state/workspaceEvents";

interface Status { client_configured: boolean; connected: string[]; redirect_uri: string }

export function GoogleSignIn() {
  const [status, setStatus] = useState<Status | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
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
    const result = await api.post("/api/google/oauth/client", { client_id: clientId, client_secret: clientSecret });
    if (!result.ok) { setMessage({ ok: false, text: result.error }); return; }
    setClientId(""); setClientSecret(""); setEditingClient(false);
    setMessage({ ok: true, text: "Saved. Now sign in with Google." });
    void load();
  }

  async function signIn() {
    const result = await api.post<{ auth_url: string }>("/api/google/oauth/start", { login_hint: hint });
    if (!result.ok) { setMessage({ ok: false, text: result.error }); return; }
    window.open(result.data.auth_url, "_blank", "noopener");
    setWaiting(true);
    setMessage({ ok: true, text: "Finish in the Google tab that opened. This updates by itself when you're done." });
  }

  if (!status) return null;
  const needsClient = !status.client_configured || editingClient;

  return (
    <div className="card keys-provider google-signin">
      <div className="keys-provider__head">
        <strong>Gmail with Google sign-in</strong>
        <span className="keys-badge">No app password</span>
        {status.connected.length > 0 && <span className="keys-status is-ok">✓ {status.connected.join(", ")}</span>}
      </div>
      <p className="keys-notes">
        Use this when Google won't give you an app password. You approve Nyx on Google's own page; Nyx never sees your Google password.
      </p>

      {needsClient ? (
        <>
          <ol className="google-signin__steps">
            <li>Open <a href="https://console.cloud.google.com/apis/library/gmail.googleapis.com" target="_blank" rel="noopener noreferrer">Google Cloud → Gmail API ↗</a> and click <b>Enable</b> (make a project if asked — it's free).</li>
            <li>In <a href="https://console.cloud.google.com/auth/audience" target="_blank" rel="noopener noreferrer">Google Auth Platform → Audience ↗</a>, choose <b>External</b>, keep it in <b>Testing</b>, and add your Gmail address under <b>Test users</b>.</li>
            <li>In <a href="https://console.cloud.google.com/auth/clients" target="_blank" rel="noopener noreferrer">Clients ↗</a>, create a client of type <b>Desktop app</b>, then copy its Client ID and Client secret here.</li>
          </ol>
          <form className="keys-form" onSubmit={(e) => { e.preventDefault(); void saveClient(); }}>
            <label className="keys-field"><span>Client ID</span>
              <input value={clientId} spellCheck={false} autoComplete="off" placeholder="1234-abc.apps.googleusercontent.com" onChange={(e) => setClientId(e.target.value)} /></label>
            <label className="keys-field"><span>Client secret</span>
              <input type="password" value={clientSecret} spellCheck={false} autoComplete="off" placeholder="GOCSPX-…" onChange={(e) => setClientSecret(e.target.value)} /></label>
            <div className="keys-actions">
              <button className="btn btn-primary" disabled={!clientId.trim() || !clientSecret.trim()}>Save Client</button>
              {status.client_configured && <button type="button" className="btn btn-secondary" onClick={() => setEditingClient(false)}>Cancel</button>}
            </div>
          </form>
        </>
      ) : (
        <div className="keys-form">
          <label className="keys-field"><span>Gmail address <em>optional</em></span>
            <input value={hint} placeholder="you@gmail.com" onChange={(e) => setHint(e.target.value)} /></label>
          <div className="keys-actions">
            <button className="btn btn-primary google-signin__button" onClick={() => void signIn()} disabled={waiting}>
              {waiting ? "Waiting for Google…" : status.connected.length ? "Sign In Another Account" : "Sign In with Google"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setEditingClient(true)}>Change Client</button>
          </div>
          <p className="keys-notes">Google may say the app isn't verified — that's your own test app. Choose <b>Continue</b>.</p>
        </div>
      )}
      {message && <p className={`keys-message ${message.ok ? "is-ok" : "is-error"}`} aria-live="polite">{message.text}</p>}
    </div>
  );
}
