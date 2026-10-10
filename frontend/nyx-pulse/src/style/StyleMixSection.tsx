/** Settings › Appearance › Style mix: pick a curated mix, or switch any of the twenty styles on and off. */

import { useEffect, useState } from "react";
import { applyMix, currentMix, onMix, PRESETS, STYLES, type StyleId } from "./styleMix";

export function StyleMixSection() {
  const [mix, setMix] = useState<StyleId[]>(currentMix());
  useEffect(() => onMix(setMix), []);
  const preset = PRESETS.find((p) => p.styles.length === mix.length && p.styles.every((s) => mix.includes(s)));
  const toggle = (id: StyleId) => applyMix(mix.includes(id) ? mix.filter((s) => s !== id) : [...mix, id]);
  return (
    <div className="style-mix">
      <div className="style-mix__presets" role="radiogroup" aria-label="Style mixes">
        {PRESETS.map((p) => (
          <button key={p.id} type="button" role="radio" aria-checked={preset?.id === p.id} className="style-mix__preset" onClick={() => applyMix(p.styles)}>
            <b>{p.label}</b>
            <small>{p.hint}</small>
          </button>
        ))}
      </div>
      <div className="style-mix__grid" role="group" aria-label="Styles">
        {STYLES.map((s) => (
          <label key={s.id} className="style-mix__style" title={s.hint}>
            <input type="checkbox" checked={mix.includes(s.id)} onChange={() => toggle(s.id)} />
            <span>{s.label}<small>{s.hint}</small></span>
          </label>
        ))}
      </div>
    </div>
  );
}
