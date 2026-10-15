/** Settings › Appearance › Colour and layout: accent colour (swatches or any colour) and where the navigation bar sits. */

import { useEffect, useState } from "react";
import { fetchDesktopTheme } from "./desktopSync";
import { clearTabOrder } from "../state/tabOrder";
import { mascotShown, setMascotShown } from "../components/mascot/Mascot";
import { ACCENTS, PALETTES, applyAppearance, readAppearance, type DesktopTheme, type NavChoice } from "./appearance";

const SIDES: { id: NavChoice; label: string }[] = [
  { id: "", label: "Look default" }, { id: "left", label: "Left" }, { id: "right", label: "Right" }, { id: "top", label: "Top" }, { id: "bottom", label: "Bottom" },
];

export function AppearanceSection() {
  const [saved, setSaved] = useState(readAppearance());
  const set = (next: Parameters<typeof applyAppearance>[0]) => setSaved(applyAppearance(next));
  const [desktop, setDesktop] = useState<DesktopTheme | null>(null);
  useEffect(() => { void fetchDesktopTheme().then(setDesktop); }, []);
  const [mascot, setMascot] = useState(mascotShown);
  return (
    <div className="appearance">
      <div className="appearance__row">
        <span className="appearance__label">Palette</span>
        <div className="appearance__palettes" role="radiogroup" aria-label="Palette">
          {PALETTES.map((p) => (
            <button key={p.id || "desk"} type="button" role="radio" aria-checked={saved.palette === p.id} title={p.hint}
              className={`appearance__palette${saved.palette === p.id ? " is-on" : ""}`} onClick={() => set({ palette: p.id })}>
              <span className="appearance__palette-dots" aria-hidden="true">
                {p.swatch.map((c) => <i key={c} style={{ background: c }} />)}
              </span>
              {p.label}
            </button>
          ))}
        </div>
        <span className="appearance__hint">Re-tones the Desk look. Your accent colour above still wins if you picked one.</span>
      </div>
      <div className="appearance__row">
        <span className="appearance__label">Accent colour</span>
        <div className="appearance__swatches" role="radiogroup" aria-label="Accent colour">
          {ACCENTS.map((a) => (
            <button key={a.id || "default"} type="button" role="radio" aria-checked={saved.accent === a.hex}
              className={`appearance__swatch${a.hex ? "" : " is-default"}`} style={a.hex ? { background: a.hex } : undefined}
              title={a.label} aria-label={a.label} onClick={() => set({ accent: a.hex })} />
          ))}
          <label className="appearance__custom" title="Any colour">
            <input type="color" value={/^#[0-9a-f]{6}$/i.test(saved.accent) ? saved.accent : "#ff7a2e"}
              onChange={(e) => set({ accent: e.target.value })} aria-label="Pick any accent colour" />
            Custom
          </label>
        </div>
      </div>
      <div className="appearance__row">
        <span className="appearance__label">Sync with desktop</span>
        <label className="appearance__custom" title="Use your desktop's accent colour and tint the app with your wallpaper">
          <input type="checkbox" role="switch" checked={saved.sync} disabled={desktop !== null && !desktop.available}
            onChange={(e) => set({ sync: e.target.checked })} aria-label="Sync with desktop colours" />
          {saved.sync ? "On" : "Off"}
        </label>
        <span className="appearance__hint">
          {desktop === null ? "Looking at your desktop…"
            : !desktop.available ? "Only on Windows."
            : desktop.accent ? <>Accent <span className="appearance__chip" style={{ background: desktop.accent }} aria-hidden="true" /> {desktop.accent}
              {desktop.wallpaper_color && <> · wallpaper <span className="appearance__chip" style={{ background: desktop.wallpaper_color }} aria-hidden="true" /></>}</>
            : "Your desktop's colours could not be read."}
        </span>
      </div>
      <div className="appearance__row">
        <span className="appearance__label">Navigation bar</span>
        <div className="segmented" role="radiogroup" aria-label="Where the navigation bar sits">
          {SIDES.map((s) => (
            <button key={s.id} type="button" role="radio" aria-checked={saved.nav === s.id} aria-pressed={saved.nav === s.id}
              onClick={() => set({ nav: s.id })}>{s.label}</button>
          ))}
        </div>
      </div>
      <div className="appearance__row">
        <span className="appearance__label">Io on the chat box</span>
        <label className="appearance__custom" title="The pixel octopus: one arm lights up per running task">
          <input type="checkbox" role="switch" checked={mascot} aria-label="Show Io on the chat box"
            onChange={(e) => { setMascotShown(e.target.checked); setMascot(e.target.checked); }} />
          {mascot ? "Shown" : "Hidden"}
        </label>
        <span className="appearance__hint">One arm lights up for each task that is running.</span>
      </div>
      <div className="appearance__row">
        <span className="appearance__label">Tab order</span>
        <span className="appearance__hint">Drag a tab to move it.</span>
        <button type="button" className="btn btn-secondary"
          onClick={() => { clearTabOrder(); window.dispatchEvent(new CustomEvent("ichos:tab-order")); }}>Reset order</button>
      </div>
    </div>
  );
}
