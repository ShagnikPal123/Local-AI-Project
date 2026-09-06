import { useEffect, useState } from "react";
import { endpoints, type StatusResponse } from "../api";
import { ErrorState, Loading, PanelShell, StatRow } from "../components/Panel";

/** Live device and routing health.
 *
 * The hardware readings here come from the safety monitor. It reports
 * "no_gpu_telemetry" when it genuinely cannot see the GPU, which must be shown
 * as unknown rather than as a healthy zero — a monitor that cannot see the
 * hardware is not the same as a cool, idle machine.
 */
export function DashboardPanel() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const result = await endpoints.status();
      if (!alive) return;
      if (result.ok) {
        setStatus(result.data);
        setError(null);
      } else {
        setError(result.error);
      }
    };
    void load();
    const timer = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  if (error && !status) return <PanelShell title="Dashboard"><ErrorState error={error} /></PanelShell>;
  if (!status) return <PanelShell title="Dashboard"><Loading what="Reading device status" /></PanelShell>;

  const router = status.router_status ?? {};
  const hw = router.hardware_health ?? {};
  const blind = (hw.status_summary ?? "").includes("no_gpu_telemetry");

  const temp = hw.gpu_temp_c ?? 0;
  const tempTone = temp >= 82 ? "danger" : temp >= 75 ? "warn" : "ok";

  return (
    <PanelShell title="Dashboard" subtitle="Live device, routing, and safety status">
      <div style={{ display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
        <div className="card">
          <div className="label" style={{ marginBottom: 8 }}>Hardware safety</div>
          {blind ? (
            <div style={{ fontSize: 12, color: "var(--color-warn)", lineHeight: 1.6 }}>
              No GPU telemetry available. Running on conservative defaults.
            </div>
          ) : (
            <>
              <StatRow label="GPU temperature" value={`${temp}°C`} tone={tempTone} />
              <StatRow
                label="VRAM"
                value={`${Math.round(hw.vram_used_mb ?? 0)} / ${Math.round(hw.vram_total_mb ?? 0)} MB`}
              />
              <StatRow label="GPU utilisation" value={`${hw.gpu_utilization ?? 0}%`} />
              <StatRow
                label="Throttle advised"
                value={hw.throttle_recommended ? "yes" : "no"}
                tone={hw.throttle_recommended ? "warn" : "ok"}
              />
            </>
          )}
          <div style={{ marginTop: 8, fontSize: 11, color: "var(--color-neutral-600)", fontFamily: "var(--font-mono)" }}>
            {hw.status_summary ?? "unknown"}
          </div>
        </div>

        <div className="card">
          <div className="label" style={{ marginBottom: 8 }}>Routing</div>
          <StatRow label="Device tier" value={String(router.device_tier ?? "unknown")} />
          <StatRow label="Online" value={router.online ? "yes" : "no"} tone={router.online ? "ok" : "warn"} />
          <StatRow label="Preferred provider" value={String(router.preferred_online_provider ?? "—")} />
          <StatRow label="Free-only mode" value={router.free_only ? "on" : "off"} />
        </div>

        <div className="card">
          <div className="label" style={{ marginBottom: 8 }}>Providers</div>
          <StatRow label="Ollama (local)" value={router.ollama_available ? "ready" : "offline"}
            tone={router.ollama_available ? "ok" : undefined} />
          <StatRow label="Gemini" value={router.gemini_available ? "ready" : "no key"}
            tone={router.gemini_available ? "ok" : undefined} />
          <StatRow label="OpenAI" value={router.openai_available ? "ready" : "no key"}
            tone={router.openai_available ? "ok" : undefined} />
          <StatRow label="Tools" value={`${status.available_tools ?? 0} registered`} />
        </div>
      </div>
    </PanelShell>
  );
}
