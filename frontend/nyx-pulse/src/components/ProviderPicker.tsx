/** Choosing who answers, and adding one that is not on the list.
 *
 * Two views over the same data. `ProviderPicker` is the dropdown that sits by
 * the composer and decides which provider handles the next turn; `ProviderManager`
 * is the full list in the Models panel, with a key test and a remove control.
 *
 * The provider API is newer than this component, so both degrade rather than
 * break: when `/api/providers` is absent the list is rebuilt from `/api/models`
 * and the add form is replaced by a plain statement of why it is unavailable. A
 * reduced picker that says so beats a full one that lies.
 *
 * A key is never displayed. The server returns `last4` and nothing more, the
 * input is a password field, and the value is dropped from state the moment the
 * request that carries it resolves.
 */

import { useCallback, useEffect, useState } from "react";
import { providers, type ProviderInfo, type ProviderSnapshot } from "../api";

/** Sentinel for "let the router decide", which is the recommended default. */
export const AUTO_PROVIDER = "";

export function maskKey(last4?: string): string {
  return last4 ? `•••• ${last4}` : "";
}

/** Shared loader so the picker and the manager cannot disagree about the list. */
export function useProviders(): {
  snapshot: ProviderSnapshot | null;
  reload: () => Promise<void>;
} {
  const [snapshot, setSnapshot] = useState<ProviderSnapshot | null>(null);

  const reload = useCallback(async () => {
    setSnapshot(await providers.list());
  }, []);

  useEffect(() => {
    let alive = true;
    void providers.list().then((s) => {
      if (alive) setSnapshot(s);
    });
    return () => {
      alive = false;
    };
  }, []);

  return { snapshot, reload };
}

const fieldStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 9px",
  background: "var(--color-nav)",
  color: "var(--color-text)",
  border: "none",
  borderRadius: "var(--radius)",
  boxShadow: "inset 0 0 0 1px var(--color-divider)",
  font: "inherit",
  fontSize: 13,
  marginBottom: 8,
};

/** Name + key (and optional endpoint/model) for a provider the app has not heard of. */
function AddProviderForm({ snapshot, onDone, onCancel }: {
  snapshot: ProviderSnapshot;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [chatUrl, setChatUrl] = useState("");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (snapshot.mode !== "full") {
    return (
      <div className="card" style={{ borderLeft: "3px solid var(--color-warn)", marginTop: 8 }}>
        <div className="label" style={{ marginBottom: 6 }}>Cannot add a provider yet</div>
        <div style={{ fontSize: 12, color: "var(--color-neutral-400)", lineHeight: 1.6 }}>
          {snapshot.note ??
            "The provider API is not available on this backend, so a new provider cannot be " +
            "registered from the interface."}
        </div>
        <button className="btn btn-secondary" onClick={onCancel} style={{ marginTop: 10 }}>
          Close
        </button>
      </div>
    );
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !name.trim() || !apiKey.trim()) return;
    setBusy(true);
    setError("");
    const result = await providers.create({
      name: name.trim(),
      api_key: apiKey,
      ...(chatUrl.trim() ? { chat_url: chatUrl.trim() } : {}),
      ...(model.trim() ? { model: model.trim() } : {}),
    });
    // Drop the key from component state whatever happened — it has either been
    // stored server-side or rejected, and there is no reason to keep it here.
    setApiKey("");
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onDone();
  }

  return (
    <form onSubmit={submit} className="card" style={{ marginTop: 8 }}>
      <div className="label" style={{ marginBottom: 8 }}>Add a provider</div>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name, e.g. mistral"
        style={fieldStyle}
        autoFocus
      />
      <input
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        type="password"
        autoComplete="off"
        placeholder="API key"
        style={fieldStyle}
      />
      <input
        value={chatUrl}
        onChange={(e) => setChatUrl(e.target.value)}
        placeholder="Chat endpoint URL (optional)"
        style={fieldStyle}
      />
      <input
        value={model}
        onChange={(e) => setModel(e.target.value)}
        placeholder="Model id (optional)"
        style={fieldStyle}
      />
      <div style={{ fontSize: 12, color: "var(--color-neutral-600)", lineHeight: 1.5, marginBottom: 9 }}>
        The key is sent once and stored by the backend. It is never sent back — this
        panel only ever sees its last four characters.
      </div>
      {error && (
        <div style={{ fontSize: 12, color: "var(--color-danger)", marginBottom: 8, lineHeight: 1.5 }}>
          {error}
        </div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={busy || !name.trim() || !apiKey.trim()}
          style={{ opacity: busy || !name.trim() || !apiKey.trim() ? 0.5 : 1 }}
        >
          {busy ? "Saving…" : "Save provider"}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

const ADD = "__add__";

/** The dropdown itself: who answers the next message. */
export function ProviderPicker({ value, onChange, compact }: {
  value: string;
  onChange: (provider: string) => void;
  compact?: boolean;
}) {
  const { snapshot, reload } = useProviders();
  const [adding, setAdding] = useState(false);

  const list = snapshot?.providers ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        {!compact && <span className="label">Answered by</span>}
        <select
          value={value}
          onChange={(e) => {
            if (e.target.value === ADD) {
              setAdding(true);
              return;
            }
            onChange(e.target.value);
          }}
          title={
            snapshot?.mode === "reduced"
              ? snapshot.note
              : "Which provider handles the next message"
          }
          style={{
            padding: compact ? "5px 8px" : "7px 9px",
            background: "var(--color-surface)",
            color: "var(--color-text)",
            border: "none",
            borderRadius: "var(--radius)",
            boxShadow: "inset 0 0 0 1px var(--color-divider)",
            font: "inherit",
            fontSize: compact ? 12 : 13,
            maxWidth: 220,
          }}
        >
          <option value={AUTO_PROVIDER}>Auto — router decides</option>
          {list.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
              {/* Ollama takes no key: unconfigured there means the local server is not answering. */}
              {p.configured ? "" : p.name === "ollama" ? " (not running)" : " (no key)"}
              {p.preferred ? " · preferred" : ""}
            </option>
          ))}
          <option value={ADD}>+ Add a provider…</option>
        </select>
        {snapshot === null && (
          <span style={{ fontSize: 12, color: "var(--color-neutral-600)" }}>loading…</span>
        )}
        {snapshot?.mode === "offline" && (
          <span style={{ fontSize: 12, color: "var(--color-warn)" }}>backend unreachable</span>
        )}
      </div>

      {snapshot?.mode === "reduced" && !compact && (
        <div style={{ fontSize: 12, color: "var(--color-neutral-600)", marginTop: 6, lineHeight: 1.5 }}>
          {snapshot.note}
        </div>
      )}

      {adding && snapshot && (
        <AddProviderForm
          snapshot={snapshot}
          onCancel={() => setAdding(false)}
          onDone={async () => {
            setAdding(false);
            await reload();
          }}
        />
      )}
    </div>
  );
}

/** The full list, for the Models panel: status, key mask, test, remove, add.
 *
 * Every provider without a key gets an inline key field, and every free-tier
 * provider (NVIDIA NIM, Groq, Gemini…) gets its signup link — the key itself
 * is one click away, and the field to paste it into is right here. A key is
 * never displayed: the server returns last4 and nothing more.
 */
export function ProviderManager() {
  const { snapshot, reload } = useProviders();
  const [adding, setAdding] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [keyDraft, setKeyDraft] = useState("");
  const [keyFor, setKeyFor] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState(false);

  async function test(name: string) {
    setTesting(name);
    const result = await providers.test(name);
    setTesting(null);
    const text = result.ok
      ? String(result.data?.detail ?? result.data?.message ?? "Key works.")
      : result.error;
    setResults((r) => ({ ...r, [name]: { ok: result.ok && result.data?.ok !== false, text } }));
  }

  async function remove(name: string) {
    const result = await providers.remove(name);
    if (!result.ok) {
      setResults((r) => ({ ...r, [name]: { ok: false, text: result.error } }));
      return;
    }
    await reload();
  }

  async function removeKey(name: string) {
    const result = await providers.removeKey(name);
    if (!result.ok) {
      setResults((r) => ({ ...r, [name]: { ok: false, text: result.error } }));
      return;
    }
    setResults((r) => ({ ...r, [name]: { ok: true, text: "Key removed — add a new one any time." } }));
    await reload();
  }

  if (!snapshot) {
    return (
      <div className="card">
        <div className="label" style={{ marginBottom: 8 }}>Providers</div>
        <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>Reading providers…</div>
      </div>
    );
  }

  const canManage = snapshot.mode === "full";

  async function saveKey(name: string) {
    if (!keyDraft.trim()) return;
    setSavingKey(true);
    const result = await providers.setKey(name, keyDraft.trim());
    setSavingKey(false);
    setKeyDraft("");
    setKeyFor(null);
    if (!result.ok) {
      setResults((r) => ({ ...r, [name]: { ok: false, text: result.error } }));
      return;
    }
    setResults((r) => ({ ...r, [name]: { ok: true, text: `Saved ${result.data.masked} — ready to use now.` } }));
    await reload();
  }

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
        <span className="label">Providers</span>
        <button
          className="btn btn-secondary"
          onClick={() => setAdding((v) => !v)}
          style={{ marginLeft: "auto", fontSize: 12, padding: "4px 10px" }}
        >
          {adding ? "Close" : "+ Add provider"}
        </button>
      </div>

      {snapshot.mode !== "full" && (
        <div style={{ fontSize: 12, color: "var(--color-warn)", lineHeight: 1.6, marginBottom: 10 }}>
          {snapshot.note}
        </div>
      )}

      {snapshot.providers.length === 0 && snapshot.mode !== "offline" && (
        <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
          No providers configured.
        </div>
      )}

      {snapshot.providers.map((p: ProviderInfo) => {
        const result = results[p.name];
        const signingUp = keyFor === p.name;
        // Big Kahuna is Nyx's own brain on this PC: no key, no account, always on.
        const own = p.name === "identity0";
        return (
          <div key={p.name} style={{ padding: "8px 0", boxShadow: "inset 0 -1px 0 var(--color-divider)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13 }}>{p.label || p.name}</span>
              {p.free && (
                <span style={{
                  fontSize: 12, letterSpacing: ".06em", color: "var(--color-ok)",
                  border: "1px solid var(--color-divider)", borderRadius: 4, padding: "1px 5px",
                }}>
                  FREE TIER
                </span>
              )}
              {own && (
                <span style={{
                  fontSize: 12, letterSpacing: ".06em", color: "var(--color-accent)",
                  border: "1px solid var(--color-accent)", borderRadius: 4, padding: "1px 5px",
                }}>
                  MAIN BRAIN · NO KEY
                </span>
              )}
              {p.preferred && (
                <span style={{ fontSize: 12, color: "var(--color-accent)" }}>preferred</span>
              )}
              {p.last4 && (
                <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--color-neutral-600)" }}>
                  {maskKey(p.last4)}
                </span>
              )}
              <span
                style={{
                  marginLeft: "auto",
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                  color: own || p.configured ? "var(--color-ok)" : "var(--color-neutral-600)",
                }}
              >
                {own ? "always on" : p.configured ? "ready" : "no key"}
              </span>
              {canManage && p.signup_url && (
                <a
                  className="btn btn-secondary"
                  href={p.signup_url}
                  target="_blank"
                  rel="noreferrer"
                  title={`Get a key at ${p.signup_url}`}
                  style={{ fontSize: 12, padding: "3px 9px", textDecoration: "none" }}
                >
                  Get a key↗
                </a>
              )}
              {canManage && !own && (
                <button
                  className="btn btn-secondary"
                  onClick={() => { setKeyFor(signingUp ? null : p.name); setKeyDraft(""); }}
                  style={{ fontSize: 12, padding: "3px 9px" }}
                >
                  {signingUp ? "Cancel" : p.configured ? "Replace key" : "Add key"}
                </button>
              )}
              {p.configured && canManage && !own && (
                <>
                  <button
                    className="btn btn-secondary"
                    onClick={() => void test(p.name)}
                    disabled={testing === p.name}
                    style={{ fontSize: 12, padding: "3px 9px" }}
                  >
                    {testing === p.name ? "Testing…" : "Test"}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => void removeKey(p.name)}
                    title="Forget the stored key(s) for this provider"
                    style={{ fontSize: 12, padding: "3px 9px", color: "var(--color-danger)" }}
                  >
                    Remove
                  </button>
                </>
              )}
            </div>
            {signingUp && canManage && (
              <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
                <input
                  type="password"
                  autoComplete="off"
                  value={keyDraft}
                  onChange={(e) => setKeyDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void saveKey(p.name); } }}
                  placeholder={`Paste your ${p.label || p.name} API key`}
                  autoFocus
                  style={{
                    flex: 1, padding: "6px 9px", background: "var(--color-nav)",
                    color: "var(--color-text)", border: "none", borderRadius: "var(--radius)",
                    boxShadow: "inset 0 0 0 1px var(--color-divider)", font: "inherit", fontSize: 13,
                  }}
                />
                <button
                  className="btn btn-primary"
                  onClick={() => void saveKey(p.name)}
                  disabled={savingKey || !keyDraft.trim()}
                  style={{ fontSize: 12, padding: "5px 12px", opacity: savingKey || !keyDraft.trim() ? 0.5 : 1 }}
                >
                  {savingKey ? "Saving…" : "Save key"}
                </button>
              </div>
            )}
            {result && (
              <div
                style={{
                  fontSize: 12,
                  marginTop: 5,
                  lineHeight: 1.5,
                  color: result.ok ? "var(--color-ok)" : "var(--color-danger)",
                }}
              >
                {result.text}
              </div>
            )}
          </div>
        );
      })}

      {canManage && (snapshot.presets?.length ?? 0) > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="label" style={{ marginBottom: 8 }}>Free providers worth adding</div>
          {snapshot.presets!.map((preset) => (
            <div key={preset.name} style={{
              display: "flex", alignItems: "center", gap: 8, padding: "6px 0",
              boxShadow: "inset 0 -1px 0 var(--color-divider)", fontSize: 12,
            }}>
              <div style={{ minWidth: 0 }}>
                <div>{preset.label}</div>
                {preset.notes && (
                  <div style={{ fontSize: 12, color: "var(--color-neutral-600)", lineHeight: 1.5 }}>
                    {preset.notes}
                  </div>
                )}
              </div>
              {preset.signup_url && (
                <a
                  className="btn btn-secondary"
                  href={preset.signup_url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ marginLeft: "auto", fontSize: 12, padding: "3px 9px", textDecoration: "none", flex: "none" }}
                >
                  Get a key↗
                </a>
              )}
            </div>
          ))}
          <div style={{ fontSize: 12, color: "var(--color-neutral-600)", marginTop: 6, lineHeight: 1.5 }}>
            After signing up, paste the key with “Add key” above — it is stored on this machine only.
          </div>
        </div>
      )}

      {adding && (
        <AddProviderForm
          snapshot={snapshot}
          onCancel={() => setAdding(false)}
          onDone={async () => {
            setAdding(false);
            await reload();
          }}
        />
      )}
    </div>
  );
}
