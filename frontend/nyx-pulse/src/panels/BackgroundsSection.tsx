/** Settings → Background: upload a GIF, video or picture, or have Nyx make one (Request G8). */

import { useState } from "react";
import { api, uploadFile } from "../api";
import { useBackgrounds, type BackgroundItem } from "../components/BackgroundLayer";
import { pushToast } from "../state/toastStore";

const MOTION_LABELS: Record<string, string> = {
  still: "Still", drift: "Drift", breathe: "Breathe", parallax: "Parallax", embers: "Embers", time: "Time rings",
};

function refresh() {
  window.dispatchEvent(new Event("nyx:background"));
}

export function BackgroundsSection() {
  const data = useBackgrounds();
  const [idea, setIdea] = useState("");
  const [making, setMaking] = useState(false);
  const [uploading, setUploading] = useState(false);
  const active = data?.active ?? null;

  async function patch(item: BackgroundItem, changes: Partial<BackgroundItem>) {
    const result = await api.patch(`/api/backgrounds/${item.id}`, changes);
    if (!result.ok) pushToast(result.error, "warn");
    refresh();
  }

  async function onUpload(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    const up = await uploadFile(file);
    if (!up.ok) { setUploading(false); pushToast(up.error, "warn"); return; }
    const result = await api.post("/api/backgrounds", { upload_id: up.data.id, name: file.name.replace(/\.[^.]+$/, "") });
    setUploading(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast("Background set.", "ok");
    refresh();
  }

  async function generate() {
    if (!idea.trim()) return;
    setMaking(true);
    const result = await api.post<{ background: BackgroundItem & { model?: string } }>("/api/backgrounds/generate", { description: idea.trim() }, 120_000);
    setMaking(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast(`Made “${result.data.background.name}” with ${result.data.background.model ?? "the image model"}.`, "ok");
    setIdea("");
    refresh();
  }

  return (
    <div className="bg-settings">
      <p className="bg-settings__hint">
        Put a picture, GIF or video behind Nyx — or describe one and Nyx makes it, then picks motion that fits.
        Turn on Reduce Motion in Windows to keep it still.
      </p>

      <div className="bg-settings__make">
        <input value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="Describe it, e.g. Loki, god of time, in the TVA"
          aria-label="Describe a background for Nyx to make" onKeyDown={(e) => { if (e.key === "Enter") void generate(); }} />
        <button className="btn btn-primary" disabled={making || !idea.trim()} onClick={() => void generate()}>
          {making ? "Making…" : "Make with AI"}
        </button>
        <label className="btn btn-secondary">
          {uploading ? "Uploading…" : "Upload GIF, Video or Picture"}
          <input type="file" hidden accept="image/*,video/mp4,video/webm" onChange={(e) => { void onUpload(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
      </div>

      {active && (
        <div className="bg-settings__active">
          <div className="bg-settings__row">
            <span className="bg-settings__label">Motion</span>
            <div className="segmented" role="group" aria-label="Motion">
              {(data?.animations ?? []).map((m) => (
                <button key={m} aria-pressed={active.animation === m} onClick={() => void patch(active, { animation: m as BackgroundItem["animation"] })}
                  disabled={active.kind !== "image" && m !== "still" && m !== "embers" && m !== "time"}
                  title={active.kind !== "image" && (m === "drift" || m === "breathe" || m === "parallax") ? "GIFs and videos already move" : undefined}>
                  {MOTION_LABELS[m] ?? m}
                </button>
              ))}
            </div>
          </div>
          <label className="bg-settings__row">
            <span className="bg-settings__label">Dim · {Math.round(active.dim * 100)}%</span>
            <input type="range" className="slider" min={0} max={0.9} step={0.05} value={active.dim}
              style={{ ["--fill" as string]: `${(active.dim / 0.9) * 100}%` }}
              onChange={(e) => void patch(active, { dim: Number(e.target.value) })} />
          </label>
          <label className="bg-settings__row">
            <span className="bg-settings__label">Blur · {active.blur}px</span>
            <input type="range" className="slider" min={0} max={24} step={1} value={active.blur}
              style={{ ["--fill" as string]: `${(active.blur / 24) * 100}%` }}
              onChange={(e) => void patch(active, { blur: Number(e.target.value) })} />
          </label>
        </div>
      )}

      <div className="bg-settings__gallery" role="list">
        <button role="listitem" className={`bg-settings__tile is-none${active ? "" : " is-active"}`}
          onClick={async () => { await api.post("/api/backgrounds/active", { id: null }); refresh(); }}>
          <span>Plain black</span>
        </button>
        {(data?.items ?? []).map((item) => (
          <div key={item.id} role="listitem" className={`bg-settings__tile${active?.id === item.id ? " is-active" : ""}`}>
            <button className="bg-settings__pick" onClick={async () => { await api.post("/api/backgrounds/active", { id: item.id }); refresh(); }}
              aria-label={`Use ${item.name}`} aria-pressed={active?.id === item.id}>
              {item.kind === "video"
                ? <video src={item.url} muted playsInline preload="metadata" />
                : <img src={item.url} alt="" loading="lazy" />}
              <span>{item.name}</span>
            </button>
            <button className="bg-settings__remove" aria-label={`Remove ${item.name}`}
              onClick={async () => { await api.del(`/api/backgrounds/${item.id}`); refresh(); }}>✕</button>
          </div>
        ))}
      </div>
    </div>
  );
}
