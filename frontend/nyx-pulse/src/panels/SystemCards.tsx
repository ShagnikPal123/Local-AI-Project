/** "This PC" and "Right now" — the machine's real specs and live readings.
 *
 * The owner reported that the web "cannot read and display the correct PC specs
 * and details, and data". Specs come from `/api/system/specs` (CIM/WMI, cached
 * server-side; null means unknown, never guessed) and live readings from
 * `/api/system/live` (one measured window; NVIDIA telemetry via nvidia-smi).
 * Polls only while the page is visible. Styling is left to the design pass.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { StatRow } from "../components/Panel";

interface Specs {
  os: { name: string | null; build: string | null; hostname: string | null; uptime_seconds: number | null };
  device: { manufacturer: string | null; model: string | null; bios: string | null };
  cpu: { name: string | null; cores: number | null; threads: number | null };
  memory: { total_gb: number | null; speed_mhz: number | null; modules: { capacity_gb: number | null; manufacturer: string | null }[] };
  gpus: { name: string | null; vram_gb: number | null; driver: string | null }[];
  disks: { model: string | null; size_gb: number | null; media: string | null }[];
  volumes: { mount: string; total_gb: number | null; free_gb: number | null; percent: number | null }[];
  displays: { width: number | null; height: number | null; refresh_hz: number | null; primary: boolean }[];
  network: { name: string; ipv4: string | null; speed_mbps: number | null; up: boolean }[];
  battery: { present: boolean; percent: number | null; plugged: boolean | null };
}

interface Live {
  cpu: { percent: number | null; per_core: number[] };
  memory: { used_gb: number | null; total_gb: number | null; percent: number | null };
  gpus: { name: string; util_percent: number | null; vram_used_mb: number | null; vram_total_mb: number | null; temp_c: number | null; power_w: number | null }[];
  disk_io: { read_bps: number | null; write_bps: number | null };
  net_io: { sent_bps: number | null; recv_bps: number | null };
  battery: { present: boolean; percent: number | null; plugged: boolean | null };
  top_processes: { pid: number; name: string; cpu_percent: number | null; memory_mb: number | null }[];
}

const unknown = "unknown";

function rate(bps: number | null): string {
  if (bps == null) return unknown;
  if (bps >= 1024 * 1024) return `${(bps / 1024 / 1024).toFixed(1)} MB/s`;
  if (bps >= 1024) return `${Math.round(bps / 1024)} KB/s`;
  return `${Math.round(bps)} B/s`;
}

function shortName(name: string): string {
  const bare = name.replace(/\.exe$/i, "");
  return bare.length > 22 ? `${bare.slice(0, 21)}…` : bare;
}

function tone(percent: number | null | undefined): "ok" | "warn" | "danger" | undefined {
  if (percent == null) return undefined;
  return percent >= 90 ? "danger" : percent >= 75 ? "warn" : undefined;
}

function Bar({ value, title }: { value: number; title?: string }) {
  return (
    <span className="sys-bar" title={title} aria-hidden="true">
      <span className="sys-bar__fill" style={{ height: `${Math.max(2, Math.min(100, value))}%` }} />
    </span>
  );
}

export function SystemCards() {
  const [specs, setSpecs] = useState<Specs | null>(null);
  const [live, setLive] = useState<Live | null>(null);

  useEffect(() => {
    let alive = true;
    void api.get<Specs>("/api/system/specs").then((r) => { if (alive && r.ok) setSpecs(r.data); });
    let busy = false;
    const poll = async () => {
      if (busy || document.hidden) return;
      busy = true;
      const r = await api.get<Live>("/api/system/live");
      busy = false;
      if (alive && r.ok) setLive(r.data);
    };
    void poll();
    const timer = setInterval(() => void poll(), 3000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const refresh = async () => {
    const r = await api.get<Specs>("/api/system/specs?refresh=true");
    if (r.ok) setSpecs(r.data);
  };

  const upNet = specs?.network.filter((n) => n.up && n.ipv4 && !n.ipv4.startsWith("127.")) ?? [];
  const display = specs?.displays.find((d) => d.primary) ?? specs?.displays[0];

  return (
    <>
      <div className="card">
        <div className="label" style={{ marginBottom: 8, display: "flex", justifyContent: "space-between" }}>
          <span>This PC</span>
          <button className="btn btn-secondary btn-sm" type="button" onClick={() => void refresh()}>Re-read</button>
        </div>
        {!specs ? <div className="sys-muted">Reading hardware…</div> : (
          <>
            <StatRow label="Device" value={[specs.device.manufacturer, specs.device.model].filter(Boolean).join(" ") || unknown} />
            <StatRow label="Processor" value={specs.cpu.name ?? unknown} />
            <StatRow label="Cores / threads" value={`${specs.cpu.cores ?? "?"} / ${specs.cpu.threads ?? "?"}`} />
            <StatRow label="Memory" value={specs.memory.total_gb != null
              ? `${Math.round(specs.memory.total_gb)} GB${specs.memory.speed_mhz ? ` · ${specs.memory.speed_mhz} MHz` : ""}${specs.memory.modules.length ? ` · ${specs.memory.modules.length} modules` : ""}`
              : unknown} />
            {specs.gpus.map((g, i) => (
              <StatRow key={`${g.name}-${i}`} label={i === 0 ? "Graphics" : ""}
                value={`${g.name ?? unknown}${g.vram_gb ? ` · ${g.vram_gb >= 1 ? `${Math.round(g.vram_gb)} GB` : "shared"}` : ""}`} />
            ))}
            {specs.disks.map((d, i) => (
              <StatRow key={`${d.model}-${i}`} label={i === 0 ? "Storage" : ""}
                value={`${d.model ?? unknown}${d.size_gb ? ` · ${Math.round(d.size_gb)} GB` : ""}${d.media ? ` ${d.media}` : ""}`} />
            ))}
            {specs.volumes.map((v) => (
              <StatRow key={v.mount} label={`Drive ${v.mount}`} tone={tone(v.percent)}
                value={v.free_gb != null && v.total_gb != null ? `${Math.round(v.free_gb)} GB free of ${Math.round(v.total_gb)} GB` : unknown} />
            ))}
            {display && <StatRow label="Display" value={`${display.width ?? "?"}×${display.height ?? "?"}${display.refresh_hz ? ` · ${display.refresh_hz} Hz` : ""}`} />}
            <StatRow label="Windows" value={`${specs.os.name ?? unknown}${specs.os.build ? ` (${specs.os.build})` : ""}`} />
            {upNet.map((n) => (
              <StatRow key={n.name} label={n.name} value={`${n.ipv4}${n.speed_mbps ? ` · ${n.speed_mbps} Mbps` : ""}`} />
            ))}
          </>
        )}
      </div>

      <div className="card">
        <div className="label" style={{ marginBottom: 8 }}>Right now</div>
        {!live ? <div className="sys-muted">Measuring…</div> : (
          <>
            <StatRow label="CPU" value={live.cpu.percent != null ? `${live.cpu.percent}%` : unknown} tone={tone(live.cpu.percent)} />
            {live.cpu.per_core.length > 0 && (
              <div className="sys-cores" role="img" aria-label={`Per-core load: ${live.cpu.per_core.map((c) => Math.round(c)).join(", ")} percent`}>
                {live.cpu.per_core.map((c, i) => <Bar key={i} value={c} title={`Core ${i + 1}: ${Math.round(c)}%`} />)}
              </div>
            )}
            <StatRow label="Memory" tone={tone(live.memory.percent)}
              value={live.memory.used_gb != null ? `${live.memory.used_gb.toFixed(1)} / ${live.memory.total_gb?.toFixed(1)} GB (${live.memory.percent}%)` : unknown} />
            {live.gpus.map((g) => (
              <div key={g.name}>
                <StatRow label={g.name.replace(/^NVIDIA GeForce /, "")} tone={tone(g.util_percent)}
                  value={`${g.util_percent ?? "?"}% · ${g.temp_c != null ? `${g.temp_c}°C` : "temp ?"}${g.power_w != null ? ` · ${Math.round(g.power_w)} W` : ""}`} />
                {g.vram_total_mb ? <StatRow label="VRAM" value={`${((g.vram_used_mb ?? 0) / 1024).toFixed(1)} / ${(g.vram_total_mb / 1024).toFixed(1)} GB`} /> : null}
              </div>
            ))}
            <StatRow label="Disk" value={`read ${rate(live.disk_io.read_bps)} · write ${rate(live.disk_io.write_bps)}`} />
            <StatRow label="Network" value={`down ${rate(live.net_io.recv_bps)} · up ${rate(live.net_io.sent_bps)}`} />
            {live.battery.present && (
              <StatRow label="Battery" tone={live.battery.percent != null && live.battery.percent < 20 && !live.battery.plugged ? "warn" : undefined}
                value={`${live.battery.percent ?? "?"}%${live.battery.plugged ? " · plugged in" : ""}`} />
            )}
          </>
        )}
      </div>

      <div className="card">
        <div className="label" style={{ marginBottom: 8 }}>Busiest programs</div>
        {!live ? <div className="sys-muted">Measuring…</div> : live.top_processes.map((p) => (
          <StatRow key={p.pid} label={shortName(p.name) || `pid ${p.pid}`}
            value={`${p.cpu_percent ?? 0}% CPU · ${p.memory_mb != null ? `${Math.round(p.memory_mb)} MB` : "?"}`} />
        ))}
      </div>
    </>
  );
}
