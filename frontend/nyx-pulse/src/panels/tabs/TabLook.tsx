/** The Edit panel's direct controls (Request H16): add any block in one click, and change how the tab
 * looks — a colour, gradient or picture behind it, and how its text boxes are drawn. */

import { useState } from "react";
import { api, uploadFile } from "../../api";
import type { TabBlock, TabSpec } from "../DynamicTab";

export interface TabBackground { kind?: "color" | "gradient" | "image"; value?: string; colors?: string[]; angle?: number; dim?: number; blur?: number }
export interface TabTheme { surface?: "solid" | "glass" | "clear"; font?: "system" | "rounded" | "serif" | "mono"; text?: string; radius?: number }

export const NEW_BLOCKS: { label: string; block: TabBlock }[] = [
  { label: "List", block: { type: "list", title: "List", config: { items: [] } } },
  { label: "Checklist", block: { type: "checklist", title: "To do", config: {} } },
  { label: "Chart", block: { type: "chart", title: "Chart", config: {} } },
  { label: "Tracker", block: { type: "tracker", title: "Tracker", config: { unit: "", kind: "number" } } },
  { label: "Timer", block: { type: "timer", title: "Timer", config: { mode: "pomodoro", minutes: 25 } } },
  { label: "AI Task", block: { type: "ai_task", title: "Nyx task", config: { prompt: "", every_minutes: 0 } } },
  { label: "You vs Nyx", block: { type: "competition", title: "You vs Nyx", config: { game: "tictactoe", difficulty: "hard" } } },
  { label: "Snake", block: { type: "game", title: "Snake", config: { game: "snake" } } },
  { label: "Memory", block: { type: "game", title: "Memory", config: { game: "memory" } } },
  { label: "Connect Four", block: { type: "competition", title: "Connect Four", config: { game: "connect4", difficulty: "hard" } } },
  { label: "Notes", block: { type: "notes", title: "Notes", config: {} } },
];

const PRESETS: { label: string; background: TabBackground; theme: TabTheme }[] = [
  { label: "Midnight", background: { kind: "gradient", colors: ["#05060F", "#1B1340"], angle: 160 }, theme: { surface: "glass", font: "system" } },
  { label: "Arcade", background: { kind: "gradient", colors: ["#0B0033", "#FF00AA", "#00E5FF"], angle: 135 }, theme: { surface: "glass", font: "mono", text: "#F5F5F7" } },
  { label: "Forest", background: { kind: "gradient", colors: ["#07140E", "#1F4D36"], angle: 180 }, theme: { surface: "glass", font: "rounded" } },
  { label: "Paper", background: { kind: "color", value: "#1A1714" }, theme: { surface: "solid", font: "serif", text: "#F2E9DC" } },
  { label: "Plain", background: {}, theme: {} },
];

export function TabLook({ spec, onChanged }: { spec: TabSpec & { background?: TabBackground; theme?: TabTheme }; onChanged: (s: TabSpec) => void }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [link, setLink] = useState("");
  const bg = spec.background ?? {};
  const theme = spec.theme ?? {};

  async function save(changes: Record<string, unknown>, request: string) {
    setBusy(request);
    setError("");
    const result = await api.patch<{ tab: TabSpec }>(`/api/tabs/${spec.id}`, { ...changes, request });
    setBusy("");
    if (!result.ok) { setError(result.error); return; }
    onChanged(result.data.tab);
  }

  async function upload(file: File) {
    setBusy("Uploading picture");
    const result = await uploadFile(file);
    setBusy("");
    if (!result.ok) { setError(result.error); return; }
    await save({ background: { kind: "image", value: `/api/uploads/${result.data.id}`, dim: bg.dim ?? 0.35 } }, "Picture background");
  }

  return (
    <div className="tab-look">
      <div className="label">Add a block</div>
      <div className="tab-look__blocks">
        {NEW_BLOCKS.map((item) => (
          <button key={item.label} className="tab-look__chip" disabled={Boolean(busy) || spec.blocks.length >= 12}
            onClick={() => void save({ blocks: [...spec.blocks, item.block] }, `Added ${item.label}`)}>
            + {item.label}
          </button>
        ))}
      </div>

      <div className="label">Look</div>
      <div className="tab-look__presets">
        {PRESETS.map((preset) => (
          <button key={preset.label} className="tab-look__preset" disabled={Boolean(busy)} onClick={() => void save({ background: preset.background, theme: preset.theme }, `${preset.label} look`)}
            style={{ background: preset.background.kind === "gradient" ? `linear-gradient(${preset.background.angle}deg, ${preset.background.colors!.join(", ")})` : preset.background.value ?? "#15151c" }}>
            <span>{preset.label}</span>
          </button>
        ))}
      </div>

      <label className="tab-look__field">
        <span>Colour</span>
        <input type="color" value={bg.kind === "color" && bg.value ? bg.value : "#101018"} onChange={(e) => void save({ background: { kind: "color", value: e.target.value } }, "Colour background")} />
      </label>
      <div className="tab-look__field">
        <span>Picture</span>
        <label className="btn btn-secondary tab-look__upload">
          Upload…
          <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
        </label>
      </div>
      <form className="tab-look__field" onSubmit={(e) => { e.preventDefault(); if (link.trim()) void save({ background: { kind: "image", value: link.trim(), dim: bg.dim ?? 0.35 } }, "Picture from a link"); }}>
        <input className="tb-input" value={link} onChange={(e) => setLink(e.target.value)} placeholder="or paste an https picture link" aria-label="Picture link" />
      </form>
      {bg.kind === "image" && (
        <label className="tab-look__field">
          <span>Dim {Math.round((bg.dim ?? 0.35) * 100)}%</span>
          <input type="range" min={0} max={0.9} step={0.05} value={bg.dim ?? 0.35}
            onChange={(e) => void save({ background: { ...bg, dim: Number(e.target.value) } }, "Dimmed the picture")} />
        </label>
      )}
      {bg.kind && <button className="chat-inline" onClick={() => void save({ background: {} }, "Removed the background")}>Remove background</button>}

      <div className="label">Text boxes</div>
      <div className="segmented" role="group" aria-label="Text box surface">
        {(["solid", "glass", "clear"] as const).map((s) => (
          <button key={s} type="button" aria-pressed={(theme.surface ?? "solid") === s} onClick={() => void save({ theme: { ...theme, surface: s } }, `${s} text boxes`)}>
            {s[0].toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>
      <label className="tab-look__field">
        <span>Font</span>
        <select value={theme.font ?? "system"} onChange={(e) => void save({ theme: { ...theme, font: e.target.value } }, `${e.target.value} font`)}>
          <option value="system">System</option><option value="rounded">Rounded</option><option value="serif">Serif</option><option value="mono">Monospace</option>
        </select>
      </label>
      {busy && <p className="tb-muted" aria-live="polite">{busy}…</p>}
      {error && <p className="tab-look__error" role="alert">{error}</p>}
    </div>
  );
}
