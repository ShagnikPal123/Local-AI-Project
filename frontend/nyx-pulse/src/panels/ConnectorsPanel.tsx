/** Connectors tab (ROADMAP BB7, V1, V6).
 *
 * This is the machine-control surface, so it leads with risk rather than hiding
 * it behind a toggle. Each connector shows what it can reach, whether it can
 * write, and whether it needs network — grouped so the dangerous ones are not
 * buried in an alphabetical list next to a calculator.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";

interface Connector {
  name: string;
  description: string;
  permissions: string[];
  is_offline: boolean;
  requires_auth: boolean;
  is_write: boolean;
  risk_level: "low" | "medium" | "high" | string;
  available: boolean;
}

interface ConnectorsResponse {
  connectors?: Connector[];
  health?: Record<string, unknown>;
}

const RISK_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

function riskColor(risk: string): string {
  if (risk === "high") return "var(--color-danger)";
  if (risk === "medium") return "var(--color-warn)";
  return "var(--color-ok)";
}

function Pill({ text, color }: { text: string; color?: string }) {
  return (
    <span style={{
      fontSize: 11, letterSpacing: ".04em", textTransform: "uppercase",
      padding: "2px 6px", borderRadius: 4,
      color: color ?? "var(--color-neutral-500)",
      background: "var(--color-nav)",
      whiteSpace: "nowrap",
    }}>
      {text}
    </span>
  );
}

function ConnectorRow({ c }: { c: Connector }) {
  return (
    <div style={{
      padding: "11px 0",
      boxShadow: "inset 0 -1px 0 var(--color-divider)",
      opacity: c.available ? 1 : 0.55,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontFamily: "var(--font-mono)" }}>{c.name}</span>
        <Pill text={c.risk_level} color={riskColor(c.risk_level)} />
        {c.is_write && <Pill text="can write" color="var(--color-warn)" />}
        {!c.is_offline && <Pill text="network" />}
        {c.requires_auth && <Pill text="needs key" />}
        {!c.available && <Pill text="unavailable" />}
      </div>
      <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.55, marginBottom: 5 }}>
        {c.description}
      </div>
      <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
        {c.permissions.map((p) => (
          <span key={p} style={{
            fontSize: 11, fontFamily: "var(--font-mono)",
            color: p === "execute" || p === "system" || p === "write"
              ? "var(--color-warn)" : "var(--color-neutral-600)",
          }}>
            {p}
          </span>
        ))}
      </div>
    </div>
  );
}

export function ConnectorsPanel() {
  const [data, setData] = useState<ConnectorsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void api.get<ConnectorsResponse>("/api/connectors").then((r) => {
      if (!alive) return;
      if (r.ok) setData(r.data);
      else setError(r.error);
    });
    return () => {
      alive = false;
    };
  }, []);

  const grouped = useMemo(() => {
    const list = data?.connectors ?? [];
    return [...list].sort(
      (a, b) =>
        (RISK_ORDER[a.risk_level] ?? 3) - (RISK_ORDER[b.risk_level] ?? 3) ||
        a.name.localeCompare(b.name),
    );
  }, [data]);

  if (error) return <PanelShell title="Connectors"><ErrorState error={error} /></PanelShell>;
  if (!data) return <PanelShell title="Connectors"><Loading what="Reading connectors" /></PanelShell>;

  const writers = grouped.filter((c) => c.is_write);

  return (
    <PanelShell
      title="Connectors"
      subtitle={`${grouped.length} registered · sorted by risk`}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="card" style={{ borderLeft: "3px solid var(--color-warn)" }}>
          <div className="label" style={{ marginBottom: 6 }}>Permission model</div>
          <div style={{ fontSize: 13, color: "var(--color-neutral-400)", lineHeight: 1.65 }}>
            {writers.length} of these can <strong>change something</strong> — write files, launch
            apps, or run commands. Those actions go through a confirmation gate and, once the
            app is claimed, require the <code style={{ fontFamily: "var(--font-mono)" }}>machine_control</code>{" "}
            permission, which only the owner holds.
            <br /><br />
            Per-connector grants you can switch on and off individually are not built yet
            (roadmap V2–V8). Until they are, treat this list as what the agent{" "}
            <em>could</em> reach, not a set of live toggles.
          </div>
        </div>

        <div className="card">
          <div className="label" style={{ marginBottom: 4 }}>Registered connectors</div>
          {grouped.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
              No connectors registered.
            </div>
          ) : (
            grouped.map((c) => <ConnectorRow key={c.name} c={c} />)
          )}
        </div>
      </div>
    </PanelShell>
  );
}
