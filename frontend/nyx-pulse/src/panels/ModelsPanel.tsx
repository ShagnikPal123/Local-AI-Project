/** Models tab (ROADMAP AA14, X3, X4, BB5).
 *
 * Auto is the default and stays the recommendation: the router already picks a
 * provider from live device specs and hardware health. Everything else here is
 * an expert override, presented as such.
 *
 * The quality tiers are derived from the device profile rather than chosen by
 * the user, and a weak machine gets an explicit warning naming what will hurt.
 * Silently letting a low-spec laptop select a model that swaps it to death is
 * the failure mode this panel exists to prevent.
 */

import { useEffect, useState } from "react";
import { api, endpoints, type StatusResponse } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";
import { ProviderManager } from "../components/ProviderPicker";

interface ModelsResponse {
  local: unknown;
  local_active?: string;
  online?: { name: string; configured: boolean }[];
  preferred_online?: string;
}

type Tier = "tiny" | "small" | "medium" | "large" | "unknown";

interface TierAdvice {
  label: string;
  quality: string;
  tone: "ok" | "warn" | "danger";
  note: string;
}

/** Map a detected device tier to what it can honestly run. */
function adviceFor(tier: Tier, ramGb: number, vramGb: number): TierAdvice {
  if (tier === "large") {
    return {
      label: "High",
      quality: "Large local models, or any online provider",
      tone: "ok",
      note: "This machine can run local inference comfortably alongside normal work.",
    };
  }
  if (tier === "medium") {
    return {
      label: "Balanced",
      quality: "Mid-size local models, online for heavy reasoning",
      tone: "ok",
      note: "Local inference works, but expect the fans under sustained load.",
    };
  }
  if (tier === "small") {
    return {
      label: "Light",
      quality: "Small local models only, online preferred",
      tone: "warn",
      note:
        `With ${ramGb ? `${ramGb.toFixed(0)} GB RAM` : "limited RAM"}` +
        `${vramGb ? ` and ${vramGb.toFixed(0)} GB VRAM` : ""}, a large local model will swap ` +
        "and make the whole machine unresponsive. Stay on online providers for anything big.",
    };
  }
  if (tier === "tiny") {
    return {
      label: "Minimal",
      quality: "Online providers only",
      tone: "danger",
      note:
        "This machine is below the bar for local inference. Running a local model here can " +
        "exhaust memory and hang the system. Auto will keep you on online providers — " +
        "please do not override that.",
    };
  }
  return {
    label: "Unknown",
    quality: "Treated as low-spec until detected",
    tone: "warn",
    note:
      "Device capability could not be detected, so Auto is deliberately conservative. " +
      "That is the safe default, not a bug.",
  };
}

export function ModelsPanel() {
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void Promise.all([api.get<ModelsResponse>("/api/models"), endpoints.status()]).then(
      ([m, s]) => {
        if (!alive) return;
        if (m.ok) setModels(m.data);
        else setError(m.error);
        if (s.ok) setStatus(s.data);
      },
    );
    return () => {
      alive = false;
    };
  }, []);

  if (error) return <PanelShell title="Models"><ErrorState error={error} /></PanelShell>;
  if (!models) return <PanelShell title="Models"><Loading what="Reading models" /></PanelShell>;

  // `/api/status` nests the router under `service` (as DashboardPanel already reads it); from the top
  // level this tab said "tier: unknown — could not be detected" on a machine the Dashboard read fine.
  const service = ((status as { service?: StatusResponse } | null)?.service ?? status) as StatusResponse | null;
  const router = service?.router_status ?? {};
  const profile = (router.device_profile ?? {}) as Record<string, number>;
  const tier = (router.device_tier ?? "unknown") as Tier;
  const advice = adviceFor(tier, Number(profile.ram_gb ?? 0), Number(profile.vram_gb ?? 0));

  const localModels = Array.isArray(models.local) ? (models.local as unknown[]) : [];
  const toneColor =
    advice.tone === "ok" ? "var(--color-ok)"
    : advice.tone === "warn" ? "var(--color-warn)"
    : "var(--color-danger)";

  return (
    <PanelShell title="Models" subtitle="Auto picks the best model for this machine">
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="card" style={{ borderLeft: "3px solid var(--color-accent)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <span style={{
              fontSize: 12, fontWeight: 600, letterSpacing: ".08em", textTransform: "uppercase",
              color: "var(--color-accent)", background: "var(--color-accent-900)",
              padding: "3px 8px", borderRadius: 4,
            }}>
              Auto · active
            </span>
            <span style={{ fontSize: 13 }}>Recommended</span>
          </div>
          <div style={{ fontSize: 13, color: "var(--color-neutral-400)", lineHeight: 1.6 }}>
            The router selects a provider per turn from live device specs, hardware health, and
            the complexity of what you asked. Simple questions take a fast path automatically.
          </div>
        </div>

        <div className="card" style={{ borderLeft: `3px solid ${toneColor}` }}>
          <div className="label" style={{ marginBottom: 8 }}>
            Quality tier for this machine
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
            <span style={{ fontSize: 20, fontWeight: 600, color: toneColor }}>{advice.label}</span>
            <span style={{ fontSize: 12, color: "var(--color-neutral-500)", fontFamily: "var(--font-mono)" }}>
              tier: {tier}
            </span>
          </div>
          <div style={{ fontSize: 13, marginBottom: 8 }}>{advice.quality}</div>
          <div style={{
            fontSize: 12, color: advice.tone === "ok" ? "var(--color-neutral-500)" : toneColor,
            lineHeight: 1.6,
          }}>
            {advice.note}
          </div>
        </div>

        <div className="card">
          <div className="label" style={{ marginBottom: 10 }}>
            Local models {localModels.length > 0 && `(${localModels.length})`}
          </div>
          {localModels.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
              No local models found. Ollama is either not installed or not running — Auto will
              use online providers instead. Nothing is broken.
            </div>
          ) : (
            localModels.map((m, i) => {
              const name = typeof m === "string" ? m : String((m as Record<string, unknown>).name ?? m);
              const active = name === models.local_active;
              return (
                <div key={i} style={{
                  display: "flex", justifyContent: "space-between", padding: "6px 0",
                  fontSize: 13, fontFamily: "var(--font-mono)",
                }}>
                  <span>{name}</span>
                  {active && <span style={{ color: "var(--color-accent)", fontSize: 12 }}>active</span>}
                </div>
              );
            })
          )}
        </div>

        {/* Online providers, with add/test/remove where the backend supports it.
            The component degrades to a read-only list built from /api/models
            when the provider API is not present. */}
        <ProviderManager />

        {router.free_only && (
          <div className="card">
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
              Free-only mode is on, so paid providers are excluded from routing even when a key
              is configured. Set <code>FREE_ONLY=false</code> in <code>.env.local</code> to allow them.
            </div>
          </div>
        )}
      </div>
    </PanelShell>
  );
}
