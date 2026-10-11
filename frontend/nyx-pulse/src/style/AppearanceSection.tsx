/** Settings › Appearance › Colour and layout: accent colour (swatches or any colour) and where the navigation bar sits. */

import { useState } from "react";
import { ACCENTS, applyAppearance, readAppearance, type NavSide } from "./appearance";

const SIDES: { id: NavSide; label: string }[] = [
  { id: "left", label: "Left" }, { id: "right", label: "Right" }, { id: "top", label: "Top" }, { id: "bottom", label: "Bottom" },
];

export function AppearanceSection() {
  const [saved, setSaved] = useState(readAppearance());
  const set = (next: Parameters<typeof applyAppearance>[0]) => setSaved(applyAppearance(next));
  return (
    <div className="appearance">
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
        <span className="appearance__label">Navigation bar</span>
        <div className="segmented" role="radiogroup" aria-label="Where the navigation bar sits">
          {SIDES.map((s) => (
            <button key={s.id} type="button" role="radio" aria-checked={saved.nav === s.id} aria-pressed={saved.nav === s.id}
              onClick={() => set({ nav: s.id })}>{s.label}</button>
          ))}
        </div>
      </div>
    </div>
  );
}
