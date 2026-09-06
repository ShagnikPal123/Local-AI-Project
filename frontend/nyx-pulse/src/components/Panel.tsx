/** Shared panel primitives.
 *
 * Every tab needs loading, empty, and error states — the backend is frequently
 * not running, and a blank screen tells the user nothing. These make the correct
 * behaviour the easy one.
 */

import type { ReactNode } from "react";

export function PanelShell({ title, subtitle, actions, children }: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "14px 18px",
          flex: "none",
          boxShadow: "inset 0 -1px 0 var(--color-divider)",
        }}
      >
        <div>
          <div style={{ fontFamily: "var(--font-heading)", fontSize: 15, fontWeight: 500 }}>{title}</div>
          {subtitle && (
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginTop: 2 }}>{subtitle}</div>
          )}
        </div>
        {actions && <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>{actions}</div>}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 18 }}>{children}</div>
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <div style={{ color: "var(--color-neutral-500)", fontSize: 13, animation: "nyxpulse 1.4s ease-in-out infinite" }}>
      {what}…
    </div>
  );
}

export function EmptyState({ message, hint }: { message: string; hint?: string }) {
  return (
    <div style={{ color: "var(--color-neutral-500)", fontSize: 13, lineHeight: 1.6 }}>
      <div>{message}</div>
      {hint && <div style={{ marginTop: 6, color: "var(--color-neutral-600)" }}>{hint}</div>}
    </div>
  );
}

export function ErrorState({ error }: { error: string }) {
  const offline = error.toLowerCase().includes("backend") || error.toLowerCase().includes("timed out");
  return (
    <div className="card" style={{ borderLeft: "3px solid var(--color-warn)" }}>
      <div style={{ fontSize: 13, marginBottom: offline ? 8 : 0 }}>{error}</div>
      {offline && (
        <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
          Start the backend from the project root:
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              background: "var(--color-nav)",
              padding: "6px 8px",
              borderRadius: 6,
              marginTop: 6,
            }}
          >
            .venv\Scripts\python.exe -m uvicorn server:app --port 8000
          </div>
        </div>
      )}
    </div>
  );
}

export function StatRow({ label, value, tone }: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "danger";
}) {
  const color =
    tone === "ok" ? "var(--color-ok)"
    : tone === "warn" ? "var(--color-warn)"
    : tone === "danger" ? "var(--color-danger)"
    : "var(--color-text)";
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 16, padding: "7px 0", fontSize: 13 }}>
      <span style={{ color: "var(--color-neutral-500)" }}>{label}</span>
      <span style={{ color, fontFamily: "var(--font-mono)", fontSize: 12 }}>{value}</span>
    </div>
  );
}
