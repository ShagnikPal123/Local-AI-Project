/** Shared panel primitives.
 *
 * Every tab needs loading, empty, and error states — the backend is frequently
 * not running, and a blank screen tells the user nothing. These make the correct
 * behaviour the easy one.
 */

import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import { requestEngineStart } from "../engine";
import { IchosOrb } from "./orbs/IchosOrb";
import { orbStateFor } from "./orbs/orbState";

/** Inside a merged tab (HubPanel) the hub already shows the title, so a page drops its own. */
export const HubContext = createContext(false);

/** The page skeleton every tab paints first (docs/DESIGN.md §1.3): a real heading, one line of purpose, actions
 * on the right, then the body. Inside a merged tab only the purpose line and the actions remain. */
export function PanelShell({ title, subtitle, actions, children }: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const inHub = useContext(HubContext);
  return (
    <div className="page-shell">
      {(!inHub || subtitle || actions) && (
        <header className={`page-shell__head${inHub ? " is-slim" : ""}`}>
          <div className="page-shell__titles">
            {!inHub && <h1 className="page-shell__title">{title}</h1>}
            {subtitle && <p className="page-shell__purpose">{subtitle}</p>}
          </div>
          {actions && <div className="page-shell__actions">{actions}</div>}
        </header>
      )}
      <div className="page-shell__body">{children}</div>
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <div className="orb-loading" role="status">
      <IchosOrb state={orbStateFor(what, "breathing")} size={20} decorative />
      <span>{what}…</span>
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
  const [asked, setAsked] = useState(false);

  // Nobody should have to copy a command into a terminal to use Nyx — that was
  // the owner's explicit complaint. The button follows the nyx:// link setup
  // registers; the full-screen Turn on screen takes over as soon as the page's
  // health check confirms the engine is off, and gets out of the way when it is on.
  function turnOn() {
    requestEngineStart("start");
    setAsked(true);
  }

  return (
    <div className="card" style={{ borderLeft: "3px solid var(--color-warn)" }}>
      <div style={{ fontSize: 13, marginBottom: offline ? 10 : 0 }}>{error}</div>
      {offline && (
        <>
          <button className="btn btn-primary" onClick={turnOn}>Turn on Nyx</button>
          <div style={{ fontSize: 12, color: "var(--color-neutral-600)", marginTop: 8, lineHeight: 1.6 }}>
            {asked
              ? "Starting… this page reconnects by itself. If your browser asks to open Nyx, choose Open — or double-click Nyx Ichos on your desktop."
              : "This reconnects by itself once the engine is up — no refresh needed."}
          </div>
        </>
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
