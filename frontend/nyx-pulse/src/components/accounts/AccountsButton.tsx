/** Accounts: separate spaces on this PC ("user1", "NIS", …), next to Log Out (owner, 2026-09-26).
 *
 * Each account keeps its own chats, memory, notes, Second Brain, uploads, research and offices in its own
 * folder; keys, sign-in, settings, models, tabs, skills and trading are shared. A password is optional and
 * only guards switching into, changing or removing the account inside Nyx. The purpose is handed to Nyx so
 * it knows what the account is for (local_accounts.py).
 *
 * Switching restarts the engine, because every store opens its file once. While it restarts this shows its
 * own "Opening …" screen above the engine-off screen, then reloads into the new account.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { waitForEngine } from "../../engine";
import "./accounts.css";

export interface Account {
  id: string;
  name: string;
  purpose: string;
  color: string;
  locked: boolean;
  created_at: number;
  main: boolean;
  running: boolean;
  opens_next: boolean;
  folder: string;
}

interface Listing {
  accounts: Account[];
  running: string;
  opens_next: string;
  switch_pending: boolean;
  shared: string;
  can_restart: boolean;
}

interface SwitchResult {
  account: Account;
  restart_needed: boolean;
  restarting: boolean;
  message?: string;
}

type Form =
  | { kind: "none" }
  | { kind: "new" }
  | { kind: "switch"; id: string }
  | { kind: "edit"; id: string }
  | { kind: "remove"; id: string };

function PersonGlyph({ size = 14 }: { size?: number }) {
  return (
    <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
      <circle cx="10" cy="7" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.7" />
      <path d="M3.8 16.5c1.2-3 3.5-4.4 6.2-4.4s5 1.4 6.2 4.4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function LockGlyph() {
  return (
    <svg viewBox="0 0 20 20" width="12" height="12" aria-hidden="true">
      <rect x="4.5" y="9" width="11" height="8" rx="2" fill="none" stroke="currentColor" strokeWidth="1.7" />
      <path d="M7 9V6.8a3 3 0 0 1 6 0V9" fill="none" stroke="currentColor" strokeWidth="1.7" />
    </svg>
  );
}

export function AccountsButton() {
  const [listing, setListing] = useState<Listing | null>(null);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState<Account | null>(null);
  const openerRef = useRef<HTMLButtonElement>(null);

  const load = useCallback(async () => {
    const result = await api.get<Listing>("/api/accounts");
    if (result.ok) setListing(result.data);
    return result.ok ? result.data : null;
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (!listing) return null; // not the owner (the route says 401/403), or an engine without accounts: no button
  const running = listing.accounts.find((a) => a.running) ?? listing.accounts[0];

  return (
    <>
      <button ref={openerRef} className="acct-btn" aria-haspopup="dialog" onClick={() => { void load(); setOpen(true); }}
        title={`Accounts — you are in ${running.name}${listing.switch_pending ? " (a switch is waiting for a restart)" : ""}`}>
        <span className="acct-btn__dot" style={{ background: running.color, boxShadow: `0 0 8px ${running.color}` }} aria-hidden="true" />
        <PersonGlyph />
        <span className="acct-btn__name">{running.name}</span>
        <span className="sr-only">, Accounts</span>
      </button>
      {open && (
        <AccountsSheet
          listing={listing}
          reload={load}
          onClose={() => { setOpen(false); openerRef.current?.focus(); }}
          onSwitching={(account) => { setOpen(false); setSwitching(account); }}
        />
      )}
      {switching && <SwitchingScreen account={switching} />}
    </>
  );
}

function AccountsSheet({ listing, reload, onClose, onSwitching }: {
  listing: Listing;
  reload: () => Promise<Listing | null>;
  onClose: () => void;
  onSwitching: (account: Account) => void;
}) {
  const [form, setForm] = useState<Form>({ kind: "none" });
  const [notice, setNotice] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialogRef.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); onClose(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const next = listing.accounts.find((a) => a.opens_next);
  const done = async (message: string) => {
    setForm({ kind: "none" });
    setNotice(message);
    await reload();
  };

  async function restartNow() {
    const result = await api.post("/api/engine/restart", {});
    if (result.ok && next) onSwitching(next);
    else setNotice(result.ok ? "" : result.error);
  }

  return (
    <div className="acct-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={dialogRef} className="acct-sheet" role="dialog" aria-modal="true" aria-labelledby="acct-title" aria-describedby="acct-lede">
        <header className="acct-sheet__head">
          <div>
            <h2 id="acct-title">Accounts</h2>
            <p id="acct-lede">Separate spaces on this PC. Each keeps its own chats, memory, notes and files.</p>
          </div>
          <button className="acct-close" onClick={onClose} aria-label="Close Accounts" data-autofocus>✕</button>
        </header>

        {listing.switch_pending && next && (
          <div className="acct-banner" role="status">
            <span>Nyx opens <b>{next.name}</b> the next time it starts.</span>
            {listing.can_restart && <button className="btn btn-primary btn-small" onClick={() => void restartNow()}>Restart Now</button>}
          </div>
        )}
        {notice && <p className="acct-notice" role="status">{notice}</p>}

        <ul className="acct-list" aria-label="Accounts on this PC">
          {listing.accounts.map((account) => (
            <li key={account.id} className={`acct-row ${account.running ? "is-running" : ""}`}>
              <div className="acct-row__main">
                <span className="acct-row__dot" style={{ background: account.color }} aria-hidden="true" />
                <div className="acct-row__text">
                  <div className="acct-row__name">
                    {account.name}
                    {account.locked && <span className="acct-row__lock" title="Has a password"><LockGlyph /><span className="sr-only">has a password</span></span>}
                    {account.running && <span className="acct-chip">Current</span>}
                    {!account.running && account.opens_next && <span className="acct-chip acct-chip--next">Opens next</span>}
                  </div>
                  <p className="acct-row__purpose">{account.purpose || (account.main ? "Everything from before accounts existed." : "No purpose written yet.")}</p>
                </div>
                <div className="acct-row__actions">
                  {!account.running && (
                    <button className="btn btn-primary btn-small" onClick={() => setForm({ kind: "switch", id: account.id })}>Switch</button>
                  )}
                  <button className="btn btn-secondary btn-small" onClick={() => setForm({ kind: "edit", id: account.id })}>Edit</button>
                  {!account.main && !account.running && (
                    <button className="btn btn-secondary btn-small acct-danger" onClick={() => setForm({ kind: "remove", id: account.id })}>Remove</button>
                  )}
                </div>
              </div>
              {form.kind === "switch" && form.id === account.id && (
                <SwitchForm account={account} onCancel={() => setForm({ kind: "none" })}
                  onDone={(result) => {
                    if (result.restarting) onSwitching(result.account);
                    else void done(result.message ?? `${result.account.name} is open.`);
                  }} />
              )}
              {form.kind === "edit" && form.id === account.id && (
                <EditForm account={account} onCancel={() => setForm({ kind: "none" })} onDone={(name) => void done(`Saved ${name}.`)} />
              )}
              {form.kind === "remove" && form.id === account.id && (
                <RemoveForm account={account} onCancel={() => setForm({ kind: "none" })}
                  onDone={(keptAt) => void done(`Removed ${account.name}. Its files were kept${keptAt ? ` in ${keptAt}` : ""}.`)} />
              )}
            </li>
          ))}
        </ul>

        {form.kind === "new" ? (
          <NewForm onCancel={() => setForm({ kind: "none" })}
            onDone={(account) => { void done(`Created ${account.name}. Switch to it when you're ready.`); }} />
        ) : (
          <button className="btn btn-secondary acct-new" onClick={() => setForm({ kind: "new" })}>+ New Account</button>
        )}

        <footer className="acct-foot">
          <p>{listing.shared}</p>
          <p>A password stops anyone opening, changing or removing that account in Nyx. The files on this PC aren’t encrypted.</p>
        </footer>
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="acct-field">
      <span className="acct-field__label">{label}</span>
      {children}
      {hint && <span className="acct-field__hint">{hint}</span>}
    </label>
  );
}

function NewForm({ onCancel, onDone }: { onCancel: () => void; onDone: (account: Account) => void }) {
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password && password !== again) { setError("The two passwords don't match."); return; }
    setBusy(true);
    setError("");
    const result = await api.post<{ account: Account }>("/api/accounts", { name, purpose, password });
    setBusy(false);
    if (result.ok) onDone(result.data.account);
    else setError(result.error);
  }

  return (
    <form className="acct-form" onSubmit={(e) => void submit(e)} aria-label="New account">
      <h3>New account</h3>
      <Field label="Name">
        <input autoFocus required maxLength={40} value={name} onChange={(e) => setName(e.target.value)} placeholder="user1, NIS, School…" />
      </Field>
      <Field label="Purpose" hint="Nyx reads this so it knows why this account is special.">
        <textarea rows={3} maxLength={600} value={purpose} onChange={(e) => setPurpose(e.target.value)}
          placeholder="e.g. NIS schoolwork — IB Physics and Chemistry. Keep answers exam-focused." />
      </Field>
      <div className="acct-form__pair">
        <Field label="Password (optional)" hint="At least 6 characters, or leave empty.">
          <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Password again">
          <input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} disabled={!password} />
        </Field>
      </div>
      {error && <p className="acct-error" role="alert">{error}</p>}
      <div className="acct-form__actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>{busy ? "Creating…" : "Create Account"}</button>
      </div>
    </form>
  );
}

function SwitchForm({ account, onCancel, onDone }: { account: Account; onCancel: () => void; onDone: (result: SwitchResult) => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError("");
    const result = await api.post<SwitchResult>(`/api/accounts/${encodeURIComponent(account.id)}/switch`, { password });
    setBusy(false);
    if (result.ok) onDone(result.data);
    else setError(result.error);
  }

  return (
    <form className="acct-inline" onSubmit={(e) => void submit(e)} aria-label={`Switch to ${account.name}`}>
      <p>Nyx restarts and opens <b>{account.name}</b>. Your current chats stay where they are.</p>
      {account.locked && (
        <Field label={`${account.name}'s password`}>
          <input type="password" autoFocus autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
      )}
      {error && <p className="acct-error" role="alert">{error}</p>}
      <div className="acct-form__actions">
        <button type="button" className="btn btn-secondary btn-small" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn btn-primary btn-small" disabled={busy || (account.locked && !password)} autoFocus={!account.locked}>
          {busy ? "Switching…" : account.locked ? "Unlock & Switch" : `Switch to ${account.name}`}
        </button>
      </div>
    </form>
  );
}

function EditForm({ account, onCancel, onDone }: { account: Account; onCancel: () => void; onDone: (name: string) => void }) {
  const [name, setName] = useState(account.name);
  const [purpose, setPurpose] = useState(account.purpose);
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [removePassword, setRemovePassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const result = await api.patch<{ account: Account }>(`/api/accounts/${encodeURIComponent(account.id)}`, {
      password, name, purpose, new_password: newPassword || null, remove_password: removePassword,
    });
    setBusy(false);
    if (result.ok) onDone(result.data.account.name);
    else setError(result.error);
  }

  return (
    <form className="acct-inline" onSubmit={(e) => void submit(e)} aria-label={`Edit ${account.name}`}>
      <Field label="Name">
        <input autoFocus required maxLength={40} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Purpose" hint="Nyx reads this so it knows why this account is special.">
        <textarea rows={3} maxLength={600} value={purpose} onChange={(e) => setPurpose(e.target.value)} />
      </Field>
      <Field label={account.locked ? "New password (leave empty to keep it)" : "Add a password (optional)"}>
        <input type="password" autoComplete="new-password" value={newPassword} disabled={removePassword}
          onChange={(e) => setNewPassword(e.target.value)} />
      </Field>
      {account.locked && (
        <>
          <label className="acct-check">
            <input type="checkbox" checked={removePassword} onChange={(e) => { setRemovePassword(e.target.checked); if (e.target.checked) setNewPassword(""); }} />
            Remove the password
          </label>
          <Field label="Current password" hint="Needed to change a locked account.">
            <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
        </>
      )}
      {error && <p className="acct-error" role="alert">{error}</p>}
      <div className="acct-form__actions">
        <button type="button" className="btn btn-secondary btn-small" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn btn-primary btn-small" disabled={busy || !name.trim()}>{busy ? "Saving…" : "Save Changes"}</button>
      </div>
    </form>
  );
}

function RemoveForm({ account, onCancel, onDone }: { account: Account; onCancel: () => void; onDone: (keptAt: string) => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const result = await api.post<{ kept_at: string }>(`/api/accounts/${encodeURIComponent(account.id)}/remove`, { password });
    setBusy(false);
    if (result.ok) onDone(result.data.kept_at);
    else setError(result.error);
  }

  return (
    <form className="acct-inline acct-inline--danger" onSubmit={(e) => void submit(e)} aria-label={`Remove ${account.name}`}>
      <p>Remove <b>{account.name}</b> from the list? Its chats, notes and files aren’t deleted — they’re moved to a
        “removed” folder you can open later.</p>
      {account.locked && (
        <Field label={`${account.name}'s password`}>
          <input type="password" autoFocus autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
      )}
      {error && <p className="acct-error" role="alert">{error}</p>}
      <div className="acct-form__actions">
        <button type="button" className="btn btn-secondary btn-small" onClick={onCancel} autoFocus={!account.locked}>Cancel</button>
        <button type="submit" className="btn btn-small acct-remove" disabled={busy || (account.locked && !password)}>{busy ? "Removing…" : "Remove Account"}</button>
      </div>
    </form>
  );
}

/** Above the engine-off screen while the engine restarts into the new account. */
function SwitchingScreen({ account }: { account: Account }) {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    let stop = false;
    const slowTimer = window.setTimeout(() => setSlow(true), 25_000);
    void (async () => {
      // Give the old engine a moment to let go, then wait for the new one and reload into it.
      await new Promise((resolve) => window.setTimeout(resolve, 2500));
      const up = await waitForEngine(120_000, undefined, () => stop);
      if (up && !stop) window.location.reload();
    })();
    return () => { stop = true; window.clearTimeout(slowTimer); };
  }, []);

  return (
    <div className="acct-switching" role="status" aria-live="polite">
      <span className="acct-switching__dot" style={{ background: account.color, boxShadow: `0 0 18px ${account.color}` }} aria-hidden="true" />
      <h2>Opening {account.name}…</h2>
      <p>Nyx is restarting in this account. This takes a few seconds.</p>
      {slow && <p className="acct-switching__slow">Still waiting. If it doesn’t come back, open Nyx from its desktop icon — it will open {account.name}.</p>}
    </div>
  );
}
