/** Settings › Appearance › Style from an image: pick a picture of a look you like, see the app wear it at once, then
 * Keep it or Undo. The colours are read here; a model that can see (when one is set up) adds corners, density and
 * where the navigation sits. See style/imageStyle.ts. */

import { useRef, useState } from "react";
import { api } from "../api";
import { applyAppearance, readAppearance, type NavChoice, type PaletteId } from "./appearance";
import { mergeLooks, paintLook, readImageFile, readSavedLook, saveLook, type ImageLook } from "./imageStyle";

interface Before { palette: PaletteId; nav: NavChoice; look: ImageLook | null }

export function ImageStyleRow({ onChange }: { onChange: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<{ look: ImageLook; image: string } | null>(null);
  const [before, setBefore] = useState<Before | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const kept = readAppearance().palette === "image" ? readSavedLook() : null;

  async function pick(file: File) {
    setBusy(true);
    setStatus("Reading the colours…");
    try {
      const saved = readAppearance();
      const prior: Before = before ?? { palette: saved.palette, nav: saved.nav, look: readSavedLook() };
      setBefore(prior);
      const { look: local, dataUrl } = await readImageFile(file);
      const show = (look: ImageLook) => {
        setPreview({ look, image: dataUrl });
        // Nav first: applyAppearance repaints the saved theme, so the preview goes on after it.
        if (look.nav) applyAppearance({ nav: look.nav });
        document.documentElement.removeAttribute("data-palette");
        paintLook(look, Boolean(saved.accent));
      };
      show(local);
      setStatus("Asking Ichos to look at the layout…");
      const r = await api.post<{ look: ImageLook }>("/api/style/from-image", { image: dataUrl, mime: file.type || "image/png" }, 45_000);
      if (r.ok) {
        show(mergeLooks(local, r.data.look));
        setStatus(r.data.look.notes ? `Ichos: ${r.data.look.notes}` : "Ichos read the colours, corners and layout.");
      } else {
        setStatus("Colours read from the picture. (For corners and layout too, add a model that can see images in Models.)");
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "That image could not be read.");
    } finally {
      setBusy(false);
    }
  }

  function keep() {
    if (!preview) return;
    saveLook(preview.look);
    applyAppearance({ palette: "image", ...(preview.look.nav ? { nav: preview.look.nav } : {}) });
    setPreview(null); setBefore(null);
    setStatus(`Kept${preview.look.name ? ` “${preview.look.name}”` : ""}. Palette › Desk takes it off again.`);
    onChange();
  }

  function undo() {
    if (!before) return;
    saveLook(before.look);
    applyAppearance({ palette: before.palette, nav: before.nav });  // repaints, so the old look comes back
    setPreview(null); setBefore(null);
    setStatus("Back to how it was.");
    onChange();
  }

  const look = preview?.look ?? kept;
  return (
    <div className="appearance__row appearance__image-style">
      <span className="appearance__label">Style from an image</span>
      <input ref={fileRef} type="file" accept="image/*" hidden
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void pick(f); e.target.value = ""; }} />
      <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => fileRef.current?.click()}>
        {busy ? "Looking…" : preview ? "Try another image" : "Pick an image"}
      </button>
      {preview && (
        <span className="appearance__image-actions">
          <button type="button" className="btn btn-primary" onClick={keep}>Keep</button>
          <button type="button" className="btn" onClick={undo}>Undo</button>
        </span>
      )}
      {look && (
        <span className="appearance__image-look" aria-label="Colours of this look">
          {preview && <img src={preview.image} alt="" />}
          {(["background", "sidebar", "panel", "text", "accent"] as const).map((k) => look[k]
            ? <i key={k} title={`${k} ${look[k]}`} style={{ background: look[k] }} /> : null)}
          {look.name && <b>{look.name}</b>}
        </span>
      )}
      <span className="appearance__hint">{status || "A screenshot of an app or site you like. Ichos copies its colours and layout, and you keep it or undo."}</span>
    </div>
  );
}
