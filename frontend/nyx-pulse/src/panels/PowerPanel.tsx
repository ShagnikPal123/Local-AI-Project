/** Power tab (ROADMAP EE7).
 *
 * Direct control over how much of the machine the AI may use. Each mode shows
 * what it actually means *on this machine*, not a generic description — "High"
 * on a 24-core desktop and "High" on a netbook are different promises.
 *
 * The hardware safety floor overrides any selection, so when a choice is capped
 * the panel says so rather than silently giving less than was asked for.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";

interface PowerMode {
  id: string;
  label: string;
  workers: number | null;
  sustainable: boolean;
  note: string;
  recommended: boolean;
}

interface Ceiling {
  mode: string;
  max_workers: number;
  max_agents: number;
  allow_local_models: boolean;
  capped_reason: string;
}

interface PowerResponse {
  current: string;
  hardware_budget: number;
  device_tier: string;
  modes: PowerMode[];
  ceiling: Ceiling;
}

export function PowerPanel() {
  const [power, setPower] = useState<PowerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    void api.get<PowerResponse>("/api/power").then((r) => {
      if (!alive) return;
      if (r.ok) setPower(r.data);
      else setError(r.error);
    });
    return () => { alive = false; };
  }, []);

  async function choose(mode: string) {
    if (saving) return;
    setSaving(true);
    const result = await api.post<PowerResponse>("/api/power", { mode });
    setSaving(false);
    if (result.ok) { setPower(result.data); setError(null); }
    else setError(result.error);
  }

  if (error && !power) return <PanelShell title="Power"><ErrorState error={error} /></PanelShell>;
  if (!power) return <PanelShell title="Power"><Loading what="Reading power settings" /></PanelShell>;

  const ceiling = power.ceiling;

  return (
    <PanelShell
      title="Power"
      subtitle={`Device tier ${power.device_tier} · your hardware supports up to ${power.hardware_budget}`}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {error && <ErrorState error={error} />}

        {/* A ceiling, not a headcount. Presenting "3 agents" as a live number
            invited the reading that three are running; nothing is running until
            work needs it. What the user actually controls is the upper bound,
            and Nyx spends under it as the task requires. */}
        <div className="card" style={{ borderLeft: "3px solid var(--color-accent)" }}>
          <div className="label" style={{ marginBottom: 8 }}>Your limit</div>
          <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginBottom: 12, lineHeight: 1.6 }}>
            Nyx decides how much of this to use for any given task and stays under it.
            Raising the limit permits more parallel work; it does not force any.
          </div>
          <div style={{ display: "flex", gap: 22, flexWrap: "wrap", fontSize: 13 }}>
            <div>
              <div style={{ fontSize: 20, fontWeight: 600, color: "var(--color-accent)" }}>
                up to {ceiling.max_agents}
              </div>
              <div style={{ fontSize: 11, color: "var(--color-neutral-500)" }}>
                helpers at once
              </div>
            </div>
            <div>
              <div style={{
                fontSize: 20, fontWeight: 600,
                color: ceiling.allow_local_models ? "var(--color-ok)" : "var(--color-warn)",
              }}>
                {ceiling.allow_local_models ? "yes" : "no"}
              </div>
              <div style={{ fontSize: 11, color: "var(--color-neutral-500)" }}>local models</div>
            </div>
          </div>
          {ceiling.capped_reason && (
            <div style={{
              marginTop: 12, fontSize: 12, color: "var(--color-warn)", lineHeight: 1.6,
              paddingTop: 10, boxShadow: "inset 0 1px 0 var(--color-divider)",
            }}>
              {ceiling.capped_reason}
            </div>
          )}
        </div>

        <div className="card">
          <div className="label" style={{ marginBottom: 4 }}>Mode</div>
          <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginBottom: 12, lineHeight: 1.6 }}>
            Auto reads this machine. Auto Task also reads what you are asking, spending less on
            a quick question and more on real work.
          </div>
          {power.modes.map((mode) => {
            const active = power.current === mode.id;
            return (
              <button
                key={mode.id}
                onClick={() => void choose(mode.id)}
                style={{
                  display: "block", width: "100%", textAlign: "left", padding: "10px 12px",
                  marginBottom: 8, borderRadius: "var(--radius)",
                  background: active ? "var(--color-accent-900)" : "var(--color-nav)",
                  boxShadow: active ? "inset 0 0 0 1px var(--color-accent-700)" : "none",
                  opacity: mode.sustainable ? 1 : 0.75,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                  <span style={{ fontSize: 13, fontWeight: active ? 600 : 400 }}>{mode.label}</span>
                  {mode.recommended && (
                    <span style={{
                      fontSize: 10, letterSpacing: ".06em", textTransform: "uppercase",
                      color: "var(--color-accent)",
                    }}>
                      recommended
                    </span>
                  )}
                  {!mode.sustainable && (
                    <span style={{ fontSize: 10, textTransform: "uppercase", color: "var(--color-warn)" }}>
                      not advised here
                    </span>
                  )}
                  {mode.workers !== null && (
                    <span style={{
                      marginLeft: "auto", fontSize: 11, fontFamily: "var(--font-mono)",
                      color: "var(--color-neutral-500)",
                    }}>
                      {mode.workers} workers
                    </span>
                  )}
                </div>
                {mode.note && (
                  <div style={{
                    fontSize: 12, lineHeight: 1.55,
                    color: mode.sustainable ? "var(--color-neutral-500)" : "var(--color-warn)",
                  }}>
                    {mode.note}
                  </div>
                )}
              </button>
            );
          })}
        </div>

        <div className="card" style={{ borderLeft: "3px solid var(--color-accent-700)" }}>
          <div className="label" style={{ marginBottom: 6 }}>Still to build</div>
          <div style={{ fontSize: 12, color: "var(--color-neutral-400)", lineHeight: 1.65 }}>
            Explicit RAM and GPU power ceilings (EE4, EE6), and live usage plotted against the
            limit. Today the mode caps worker and agent counts — model size and inference
            concurrency do not obey it yet (EE8).
          </div>
        </div>
      </div>
    </PanelShell>
  );
}
