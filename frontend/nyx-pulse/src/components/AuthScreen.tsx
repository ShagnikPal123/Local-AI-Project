/** Sign-in and invite redemption (ROADMAP AA1, AA5, BB).
 *
 * Shown when the backend reports `claimed: true` and we have no valid session,
 * or whenever the URL carries `?invite=…`.
 */

import { useState, type FormEvent } from "react";
import { auth, setToken, type AccountUser } from "../api";
import { NyxAvatar } from "./NyxAvatar";

const MIN_PASSWORD = 12;

function Field({ label, ...props }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label style={{ display: "block", marginBottom: 12 }}>
      <div className="label" style={{ marginBottom: 5 }}>{label}</div>
      <input
        {...props}
        style={{
          width: "100%",
          padding: "9px 11px",
          background: "var(--color-nav)",
          color: "var(--color-text)",
          border: "none",
          borderRadius: "var(--radius)",
          boxShadow: "inset 0 0 0 1px var(--color-divider)",
          font: "inherit",
          fontSize: 14,
        }}
      />
    </label>
  );
}

function Shell({ title, subtitle, children }: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{
      height: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      background: "var(--color-bg)", padding: 20,
    }}>
      <div className="card" style={{ width: "100%", maxWidth: 380, padding: 26 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
          <NyxAvatar size={34} />
          <div>
            <div style={{ fontFamily: "var(--font-heading)", fontSize: 16, fontWeight: 500 }}>{title}</div>
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginTop: 2 }}>{subtitle}</div>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

function Problem({ message }: { message: string }) {
  return (
    <div style={{
      fontSize: 12, color: "var(--color-danger)", marginBottom: 12,
      padding: "8px 10px", borderRadius: 6, background: "rgba(224,122,122,0.08)",
    }}>
      {message}
    </div>
  );
}

export function LoginScreen({ onSignedIn }: { onSignedIn: (user: AccountUser | null) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const result = await auth.login(email.trim(), password);
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setToken(result.data.token);
    onSignedIn(result.data.user);
  }

  return (
    <Shell title="Nyx Ichos" subtitle="Sign in to continue">
      <form onSubmit={submit}>
        {error && <Problem message={error} />}
        <Field
          label="Email" type="email" autoComplete="username" required autoFocus
          value={email} onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Password" type="password" autoComplete="current-password" required
          value={password} onChange={(e) => setPassword(e.target.value)}
        />
        <button
          type="submit" className="btn btn-primary" disabled={busy}
          style={{ width: "100%", justifyContent: "center", padding: "10px", marginTop: 4, opacity: busy ? 0.6 : 1 }}
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <div style={{ marginTop: 16, fontSize: 12, color: "var(--color-neutral-600)", lineHeight: 1.6 }}>
        No account yet? Claim the owner account from the project folder:
        <div style={{
          fontFamily: "var(--font-mono)", fontSize: 12, background: "var(--color-nav)",
          padding: "6px 8px", borderRadius: 6, marginTop: 6,
        }}>
          python admin_setup.py claim you@example.com
        </div>
      </div>
    </Shell>
  );
}

export function JoinScreen({ invite, onJoined }: {
  invite: string;
  onJoined: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError("Those passwords do not match.");
      return;
    }
    if (password.length < MIN_PASSWORD) {
      setError(`Password must be at least ${MIN_PASSWORD} characters.`);
      return;
    }
    setBusy(true);
    setError("");
    const result = await auth.join(invite, email.trim(), password);
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setDone(true);
  }

  if (done) {
    return (
      <Shell title="You are in" subtitle="Account created">
        <div style={{ fontSize: 13, color: "var(--color-neutral-400)", lineHeight: 1.7, marginBottom: 16 }}>
          Your beta account is ready. Sign in with the details you just chose.
        </div>
        <button className="btn btn-primary" onClick={onJoined}
          style={{ width: "100%", justifyContent: "center", padding: 10 }}>
          Go to sign in
        </button>
      </Shell>
    );
  }

  return (
    <Shell title="Join the beta" subtitle="You have been invited to test Nyx Ichos">
      <form onSubmit={submit}>
        {error && <Problem message={error} />}
        <Field
          label="Email" type="email" autoComplete="username" required autoFocus
          value={email} onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label={`Choose a password (min ${MIN_PASSWORD} characters)`}
          type="password" autoComplete="new-password" required
          value={password} onChange={(e) => setPassword(e.target.value)}
        />
        <Field
          label="Confirm password" type="password" autoComplete="new-password" required
          value={confirm} onChange={(e) => setConfirm(e.target.value)}
        />
        <button
          type="submit" className="btn btn-primary" disabled={busy}
          style={{ width: "100%", justifyContent: "center", padding: 10, marginTop: 4, opacity: busy ? 0.6 : 1 }}
        >
          {busy ? "Creating account…" : "Create account"}
        </button>
      </form>
      <div style={{ marginTop: 14, fontSize: 12, color: "var(--color-neutral-600)", lineHeight: 1.6 }}>
        This invite works once. Your password is stored only as a salted hash.
      </div>
    </Shell>
  );
}
